# Windows 部署与测试步骤

这个目录是新版“批量导入开票”工作台，可以单独复制到 Windows 电脑使用，不需要同时复制旧版 `invoice-demo`。

## 复制内容

把整个 `invoice-demo-batch-import` 文件夹复制到 Windows，例如：

```text
C:\invoice-demo-batch-import
```

不要只复制其中几个脚本。首次部署需要同时包含：

- `windows_bootstrap\installers`：Python 与 Tesseract 安装器
- `windows_bootstrap\wheels`：Python 依赖离线安装包
- `windows_bootstrap\tessdata`：中英文 OCR 数据
- `tax_invoice_demo\data`：赋码库/分类库基础数据
- `official_templates`：税局官方批量导入模板

## 第一次部署

在 Windows 文件夹中按顺序执行：

1. 进入 `C:\invoice-demo-batch-import\windows_bootstrap`
2. 双击 `launch_prerequisites.bat`
3. 安装 Python 时勾选 `Add python.exe to PATH`
4. 按提示安装 Tesseract OCR
5. 双击 `install_tessdata_if_needed.bat`
6. 返回 `C:\invoice-demo-batch-import`
7. 双击 `install_windows.bat`

`install_windows.bat` 会创建本目录自己的 `.venv`，并优先使用随包携带的离线 wheels 安装依赖。

## 每次实际测试

1. 关闭所有 Edge 窗口
2. 双击 `start_edge_cdp.bat`
3. 在这个 Edge 窗口中手工打开对应省份电子税务局
4. 手工登录并切换到目标企业主体
5. 在 Edge 地址栏访问 `http://127.0.0.1:9222/json`，确认能看到 JSON
6. 双击 `start_lean_workbench.bat`
7. 在工作台上传材料或输入开票信息，生成草稿
8. 修正草稿后导出/执行批量导入

执行过程中不要关闭用 `start_edge_cdp.bat` 打开的 Edge。

## 成功标准

第一阶段以走到税局“预览发票”为成功标准：

- 税局批量导入提示处理成功
- 工作台或税局页面能打开 `预览发票`
- 发票抬头、明细、税率、金额、备注与草稿一致

暂不要求程序点击最终“批量开具/发票开具”，最终开具仍由人工确认。

## 数据保存位置

所有运行数据默认保存在 `C:\invoice-demo-batch-import\output` 下：

- 草稿与上传原始材料：`output\workbench\tax_invoice_demo\<draft_id>`
- 草稿累计明细：`output\workbench\tax_invoice_demo\累计发票明细表.xlsx`
- 赋码反馈候选池：`output\workbench\tax_invoice_demo\赋码反馈候选池.csv`
- Case 事件队列：`output\workbench\tax_invoice_demo\_events`
- 批量导入模板和失败明细：`output\batch_import_preview`
- 批量导入成功明细：`output\batch_import_preview\批量导入成功明细.xlsx`

第一阶段试用时，建议每天或每周备份整个 `output` 文件夹。不要只备份生成的模板，因为赋码反馈候选池和累计明细都在 `output` 里面。

## 可选：把试用数据回传到中心端

如果你已经把中心接收端跑起来，例如在 Mac 上执行：

```bash
python3 start_sync_center.py
```

推荐给试用客户直接放一份：

```text
invoice-demo-batch-import\sync_client.local.json
```

可以从：

```text
invoice-demo-batch-import\sync_client.example.json
```

复制并改成类似：

```json
{
  "enabled": true,
  "endpoint": "http://你的Mac或服务器地址:5021/api/invoice/events",
  "token": "你的token",
  "tenant": "shenyang-seed-a",
  "timeout_seconds": 8
}
```

这样客户双击启动工作台时，就会自动尝试把 `case` 事件回传到你的中心端，不需要再手工执行 `set`。

如果你只是临时联调，也可以在 Windows 的终端里先设置：

```bat
set TAX_INVOICE_SYNC_ENDPOINT=http://你的Mac或服务器地址:5021/api/invoice/events
set TAX_INVOICE_SYNC_TOKEN=你的token
set TAX_INVOICE_SYNC_TENANT=shenyang-seed
```

之后工作台写入事件时会自动尝试补发。

也可以手动执行：

```bat
python tools\\flush_case_events.py
```

## 常见问题

如果 `start_lean_workbench.bat` 打不开页面，先重新运行 `install_windows.bat`。

如果 CDP 连接失败，先关闭所有 Edge，再重新运行 `start_edge_cdp.bat`。

如果 `http://127.0.0.1:9222/json` 打不开，说明当前 Edge 不是用调试端口启动的。

如果图片 OCR 不生效，确认 Tesseract 已安装，并重新执行 `windows_bootstrap\install_tessdata_if_needed.bat`。

## Git 同步开发建议

如果你已经开始进入频繁迭代阶段，建议不要再长期用 LocalSend 反复传整个文件夹。

当前推荐：

- Mac 作为主开发机
- Windows 作为真实税局测试机
- 两边共享一个 Git 远端仓库

具体步骤见：

```text
invoice-demo-batch-import\GIT_SYNC_SETUP.md
```

Windows 侧后续可直接使用：

- `update_only.bat`
- `update_and_start.bat`

来拉最新代码并启动工作台。
