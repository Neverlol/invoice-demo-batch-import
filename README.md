# 批量导入开票新分叉

这个目录是与现有 `invoice-demo/` 独立的新版方法分叉。

当前目标不是继续优化“网页逐格填单”，而是转成更贴合真实业务的主线：

1. 助理上传客户原始材料
2. 系统生成结构化草稿
3. 草稿确认后导出成税局官方批量导入模板
4. 在税局 `批量开票` 页面上传模板
5. 若税局返回失败明细，再回到本地修正并重新导入

## 为什么要转主线

结合 `IMG_2138.MOV` 和官方模板 `(V251101版)批量开票-导入开票模板.xlsx`，有几个结论已经很明确：

- 多品类、多行明细的痛点，模板导入天生比网页逐行点 `增行/赋码` 更稳。
- 税局页面的动态交互非常重，逐格填单容易卡在：
  - 增行
  - 商品编码抽屉
  - 税率联动
  - 页面滚动/焦点错乱
- 模板导入把复杂度前移到我们可控的线下结构化阶段，更符合现阶段技术优势。
- 视频里真实路径也更像：
  - 本地整理模板
  - 税局上传
  - 看失败明细
  - 线下修正后再次上传

## 当前分叉的第一版实现

已包含：

- 官方模板副本：
  - `official_templates/(V251101版)批量开票-导入开票模板.xlsx`
- 轻量工作台：
  - `app.py`
  - `templates/lean_*.html`
  - `static/lean.css`
  - `static/lean.js`
- 模板导出器：
  - `tax_invoice_batch_demo/batch_template.py`
- 多品类案例 5 的预览导出脚本：
  - `demo_case5_export.py`
- 现有 workbench 草稿桥接脚本：
  - `export_saved_draft.py`
- 税局失败明细解析脚本：
  - `read_import_failure.py`
- 上传前本地预校验脚本：
  - `validate_batch_template.py`
- CDP 批量导入执行入口：
  - `tax_invoice_batch_demo/batch_runner.py`
- Windows 首次部署资源：
  - `windows_bootstrap/installers`
  - `windows_bootstrap/wheels`
  - `windows_bootstrap/tessdata`
  - `install_windows.bat`
  - `WINDOWS_SETUP.md`

## 当前主线定义

推荐主线：

- `原始材料 -> 结构化草稿 -> 官方模板.xlsx -> 税局批量导入`

保留旧线作为兜底：

- `原始材料 -> 结构化草稿 -> 网页逐格填单`

## 当前边界

第一版先只覆盖这几类字段：

- sheet `1-发票基本信息`
- sheet `2-发票明细信息`
- sheet `4-附加要素信息`

暂未完整承接的能力：

- sheet `3-特定业务信息` 的全字段自动填充
- 税局失败明细回流后的自动修模版

## 数据沉淀与赋码自进化

当前新线按三层数据落盘：

- 正式赋码库：`tax_invoice_demo/data/coding_library_formal_v0.1.csv`
  - 只放已经审核过、可自动命中的映射。
  - 工作台生成草稿时会读取它，但不会在普通保存时直接改写它。
- 本地即时学习规则库：`output/workbench/tax_invoice_demo/本地即时学习赋码规则.csv`
  - 助理在草稿复核页修改赋码大类、税收编码、税率或项目名称并保存后，会立即写入这里。
  - 下一次同一台电脑遇到相同或相似项目，会优先命中本地学习规则，不需要等待云端审核或重新打包。
  - 这不是正式基础库，后续应通过云端候选池审核后再晋升为客户规则或系统规则。
- 客户同步赋码规则：`output/workbench/tax_invoice_demo/客户同步赋码规则.csv`
  - 由中心端审核后下发，优先级高于本地即时学习规则和正式基础库。
  - 用于把“第一天修正过的错误”尽快同步回客户工具，而不是等下一次发新版包。
- 草稿累计明细：`output/workbench/tax_invoice_demo/累计发票明细表.csv` 和 `.xlsx`
  - 每次生成或保存草稿都会按 `draft_id` 覆盖写入最新明细。
  - 用于回看所有工作台生成过的发票明细。
- 赋码反馈候选池：`output/workbench/tax_invoice_demo/赋码反馈候选池.csv`
  - 没有正式命中、只命中官方分类候选、或助理在草稿里人工修正过赋码/税率的行会进入这里。
  - 助理点击“保存并重建模板”后，如果改过赋码大类、税收编码或税率，系统会标记为 `manual_correction`。
- 批量导入成功明细：`output/batch_import_preview/批量导入成功明细.csv` 和 `.xlsx`
  - 助理确认税局预览正确后点击“标记成功并累计”，写入最终成功样本。

第一阶段不建议把人工修正自动提升为正式赋码库。推荐流程是：

`人工修正 -> 本地即时学习 -> 反馈候选池/Case 事件回传 -> 每日/每周人工审核 -> 合格样本再进入客户规则或正式赋码库`

这样能避免单次误改、不同纳税人税率差异、客户特殊口径直接污染自动命中规则。

## Case 数据回流

新线已经补上本地 `case` 事件队列，默认写入：

- `output/workbench/tax_invoice_demo/_events/pending_events.jsonl`
- `output/workbench/tax_invoice_demo/_events/cases/<case_id>.jsonl`
- `output/workbench/tax_invoice_demo/_events/last_sync_state.json`

如果暂时没有配置中心服务，这些事件只会留在本地，不影响工作台使用。

如果要开始把种子客户试用数据回收到中心端，推荐优先放一份本地配置文件：

- `sync_client.local.json`

可直接从：

- `sync_client.example.json`

复制一份后改成：

```json
{
  "enabled": true,
  "endpoint": "http://你的中心端地址:5021/api/invoice/events",
  "token": "你的token",
  "tenant": "shenyang-seed-a",
  "timeout_seconds": 8
}
```

运行时读取顺序：

1. 环境变量（优先级最高）
2. `sync_client.local.json`
3. `sync_client.json`

也就是说，给种子客户交付时，你只要把已经填好的 `sync_client.local.json` 一起放进目录里，就能开箱自动回传。

中心端审核后的赋码规则可以通过同一套配置下发。默认会从 `endpoint` 自动推导：

```text
http://服务器:5021/api/invoice/events
-> http://服务器:5021/api/invoice/tenants/<tenant>/rules/latest
```

如果需要单独指定，也可以在 `sync_client.local.json` 增加：

```json
{
  "rules_endpoint": "http://服务器:5021/api/invoice/tenants/shenyang-seed-a/rules/latest"
}
```

手动拉取审核规则包：

```bash
python3 tools/pull_rule_package.py
```

工作台首页打开时也会在后台自动尝试拉取一次最新规则包。失败不会阻断开票，仍可用上面的命令手动补拉。

中心端可从客户回传事件里导出赋码候选：

```bash
python3 tools/export_rule_candidates.py --tenant shenyang-seed-a
```

人工审核 CSV 后，把 `status` 改成 `approved`，再发布规则包：

```bash
python3 tools/publish_rule_package_from_csv.py --tenant shenyang-seed-a --csv 候选文件.csv --token 你的token
```

如果你临时联调，也可以继续用环境变量：

- `TAX_INVOICE_SYNC_ENDPOINT`
- `TAX_INVOICE_RULES_ENDPOINT`（可选，不填时按 tenant 自动推导）
- `TAX_INVOICE_SYNC_TOKEN`
- `TAX_INVOICE_SYNC_TENANT`（可选）
- `TAX_INVOICE_SYNC_TIMEOUT`（可选，默认 8 秒）
- `TAX_INVOICE_SYNC_ENABLED`（可选，设为 `0/false/off` 可临时关闭）
- `TAX_INVOICE_SYNC_CONFIG`（可选，显式指定配置文件路径）

手动补发命令：

```bash
python3 tools/flush_case_events.py
```

## 可选：LLM 结构化抽取

LLM 在一期只作为“结构化抽取兜底能力”，不是流程主控。默认关闭。

当前模块准备接的是 **MiniMax M2.7 的 OpenAI-compatible API 直连**，不是 OpenClaw/Hermes。

- 推荐 provider：`minimax_openai` 或 `minimax_m27`
- 不建议在一期把 provider 配成 `openclaw` 或 `hermes`
- OpenClaw/Hermes 后续可以作为飞书/企微入口或编排层，但它应调用本地 `LLMAdapter`/规则引擎，不应替代一期主流程

启用方式推荐使用本地配置文件：

- 从 `llm_client.example.json` 复制一份为 `llm_client.local.json`
- `llm_client.local.json` 已被 `.gitignore` 排除，不会提交到仓库
- API Key 推荐放在环境变量里，不要直接写进配置文件

示例：

```json
{
  "enabled": true,
  "provider": "minimax_openai",
  "region": "global",
  "endpoint": "https://api.minimax.io/v1/chat/completions",
  "model": "MiniMax-M2.7",
  "api_key_env": "TAX_INVOICE_MINIMAX_API_KEY",
  "timeout_seconds": 45,
  "max_retries": 2
}
```

`region` 可选：

- `global`：默认使用 `https://api.minimax.io/v1/chat/completions`
- `cn`：国内网络优先使用 `https://api.minimaxi.com/v1/chat/completions`

如果你手动填写了 `endpoint`，则以 `endpoint` 为准；没有填写时才根据 `region` 自动选择。

运行时读取顺序：

1. 环境变量（优先级最高）
2. `llm_client.local.json`
3. `llm_client.json`

支持的环境变量：

- `TAX_INVOICE_LLM_ENABLED`
- `TAX_INVOICE_LLM_PROVIDER`
- `TAX_INVOICE_LLM_REGION`
- `TAX_INVOICE_LLM_ENDPOINT`
- `TAX_INVOICE_LLM_MODEL`
- `TAX_INVOICE_LLM_API_KEY`
- `TAX_INVOICE_LLM_API_KEY_ENV`
- `TAX_INVOICE_LLM_TIMEOUT`
- `TAX_INVOICE_LLM_MAX_RETRIES`
- `TAX_INVOICE_LLM_CONFIG`

当前触发策略：

- 规则解析已经能提取买方和明细时，不调用 LLM。
- 买方、税号、明细或金额缺失时，才尝试调用 LLM。
- LLM 返回结果必须通过 JSON Schema 校验；失败会自动重试。
- 重试后仍失败时，回退到规则解析结果，不阻断工作台。

联调 LLM 配置：

```bash
python3 tools/llm_smoke_test.py --config-only
```

配置通过后，做一次真实抽取测试：

```bash
python3 tools/llm_smoke_test.py --text "辽宁恒润电力科技有限公司 91210102MABWM3X12T 500 普票 代理记账和税务申报"
```

输出里会包含当前读取到的 provider / endpoint / model、API Key 是否配置、模型调用是否成功、返回 JSON 是否通过字段校验。API Key 只显示脱敏预览，不会明文打印。

模型如果偶尔返回 Markdown 代码块包裹的 JSON，当前 Adapter 会自动剥离代码块后再解析。

## 最小中心接收端

当前仓库已内置一个最小中心接收端，用于一期接住种子客户的 `case` 事件数据。

启动方式：

```bash
python3 start_sync_center.py
```

默认地址：

```text
http://127.0.0.1:5021
```

主要接口：

- `GET /api/invoice/events/health`

云服务器部署步骤见：

- `CLOUD_SYNC_CENTER_DEPLOY.md`
- `POST /api/invoice/events`
- `GET /api/invoice/tenants/<tenant>/events`
- `GET /api/invoice/tenants/<tenant>/cases/<case_id>`

如果需要开启 token 鉴权，可设置：

- `TAX_INVOICE_CENTER_TOKEN`
- `TAX_INVOICE_CENTER_HOST`
- `TAX_INVOICE_CENTER_PORT`
- `TAX_INVOICE_CENTER_DB`

接收端当前使用：

- `Flask`
- `SQLite`

它是第一阶段的最小中心数据平面，不是最终大平台。当前目的只有一个：**先把种子客户真实业务数据接住并可追溯。**

## 当前可直接使用的命令

### 0. Windows 首次部署

新线包可以单独复制到 Windows，不需要同时复制旧版 `invoice-demo`。

首次部署按这个顺序执行：

```text
1. windows_bootstrap\launch_prerequisites.bat
2. windows_bootstrap\install_tessdata_if_needed.bat
3. install_windows.bat
```

详细中文步骤见：

```text
invoice-demo-batch-import/WINDOWS_SETUP.md
```

## Git 同步开发

如果你已经开始进入：

- Mac 开发
- Windows 实机测试

不要再长期靠 LocalSend 来回传整个文件夹。

当前推荐做法：

- 用 Git 同步代码
- 用 Windows 保留真实税局测试环境
- 用整包目录做客户交付

新增文件：

- `GIT_SYNC_SETUP.md`
- `update_and_start.bat`
- `update_only.bat`

推荐流程：

1. Mac 改代码并 `git push`
2. Windows 双击 `update_and_start.bat`
3. 自动 `git pull --ff-only` 后启动工作台

说明：

- `.gitignore` 已排除 `output/`、`.venv/`、`__pycache__/`、大体积 bootstrap 安装资源
- 这样 Git 仓库更轻，日常同步更快
- 但你本地完整目录仍然保留这些资源，可继续打整包交付客户

### 1. Windows 推荐启动顺序

先关闭所有 Edge 窗口，然后双击：

```text
invoice-demo-batch-import/start_edge_cdp.bat
```

这个脚本会用 `--remote-debugging-port=9222` 启动真实 Edge。随后在这个 Edge 里人工打开对应省份电子税务局、登录并切换企业主体。

确认 CDP 端口可用：

```text
http://127.0.0.1:9222/json
```

看到 JSON 后，再双击：

```text
invoice-demo-batch-import/start_lean_workbench.bat
```

执行过程中不要关闭这个 Edge 窗口。

### 2. 启动轻量工作台

```bash
python3 invoice-demo-batch-import/start_lean_workbench.py
```

Windows 可双击：

```text
invoice-demo-batch-import/start_lean_workbench.bat
```

默认地址：

```text
http://127.0.0.1:5012
```

轻量工作台只保留：

- 信息输入
- 文件上传
- 发票草稿式预览和修正
- 明细批量修改：赋码大类、税收编码、税率可一键应用到全部明细
- 官方批量导入模板下载
- 税局失败明细回流
- 成功后累计到 `批量导入成功明细.xlsx`
- CDP 启动批量导入后，会尝试：
  - 等待税局处理结果
  - 成功时点击 `预览发票`
  - 失败时下载失败明细并解析字段原因

### 3. 导出内置样例

```bash
python3 invoice-demo-batch-import/demo_case5_export.py
```

会输出：

- `output/batch_import_preview/case5_batch_import_preview.xlsx`

### 4. 从现有 workbench 草稿导出

```bash
python3 invoice-demo-batch-import/export_saved_draft.py 6232135c5a \
  -o output/batch_import_preview/from_draft_6232135c5a.xlsx
```

### 5. 从现有批量草稿导出

```bash
python3 invoice-demo-batch-import/export_saved_draft.py f69eeb7611 \
  -o output/batch_import_preview/from_batch_f69eeb7611.xlsx
```

其中：

- `6232135c5a` 是单草稿 `draft_id`
- `f69eeb7611` 是批量草稿 `batch_id`

也可以直接传 `draft.json` 或 `batch.json` 路径。

### 6. 上传前本地预校验

```bash
python3 invoice-demo-batch-import/validate_batch_template.py \
  output/batch_import_preview/from_draft_6232135c5a.xlsx
```

当前校验会先拦截：

- 基础 sheet / 明细 sheet 缺失
- 发票流水号缺失或重复
- 基本信息与明细信息流水号无法关联
- 专票缺少购买方纳税人识别号
- 官方模板下拉项填了非法值
- 税率误填成 `13%` 这类百分号格式
- 商品编码误填成不能直接开票的汇总类目

### 7. 读取税局下载失败明细

```bash
python3 invoice-demo-batch-import/read_import_failure.py \
  /path/to/NSR-蓝字发票开具-批量导入开票-下载失败明细模板.xlsx \
  -o output/batch_import_preview/import_failure_report.json
```

脚本会输出：

- 失败发票流水号
- 发票类型
- 购买方信息
- 税局返回的失败原因
- 识别出的失败 sheet
- 识别出的失败字段

## 下一步建议

1. 把现有草稿页面对接到模板导出器
2. 用税局失败明细继续扩展本地预校验规则
3. 做失败明细到草稿字段的回写提示
4. 继续补机动车/建筑服务/旅客运输等强特定业务模板化
