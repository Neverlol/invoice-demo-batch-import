# 智能开票助手｜Windows 全新安装与 4 Excel 批量测试说明

推荐版本：`full-install-ebc7f2e-plus.zip` 或更新版本。

> 重要：完整安装包不包含任何真实密钥。密钥必须在现场电脑本机单独配置，不要发群、不要提交 Git、不要放进公开 zip。

---

## 1. 解压位置

建议把完整安装包解压到：

```text
C:\InvoiceAssistant
```

解压后应看到：

```text
00_FIRST_INSTALL.bat
01_INSTALL_PRIVATE_CONFIG.bat
02_START_INVOICE_ASSISTANT.bat
首次安装智能开票助手.bat
安装现场私密配置.bat
启动智能开票助手.bat
app.py
tax_invoice_demo\
windows_bootstrap\
test_materials\
```

如果解压后多了一层目录，也可以进入那一层再运行脚本。

---

## 2. 配置密钥文件

### 2.1 编辑私密配置模板

完整安装包内已经带好模板目录：

```text
C:\InvoiceAssistant\_onsite_private_config\
```

里面有：

```text
onsite_secrets.template.json
00_COPY_TEMPLATE_AND_EDIT.bat
```

推荐操作：

```text
1. 进入 C:\InvoiceAssistant\_onsite_private_config\
2. 双击 00_COPY_TEMPLATE_AND_EDIT.bat
3. 脚本会把 onsite_secrets.template.json 复制为 onsite_secrets.json，并自动用记事本打开
4. 只需要把里面的 MiMo API Key 和 sync token 替换成真实值
5. 保存并关闭记事本
```

如果你使用配套私密配置包，则不需要手动编辑模板；直接把私密配置包解压到 C:\InvoiceAssistant 后运行 01_INSTALL_PRIVATE_CONFIG.bat。

说明：

```text
mimo_api_key：大模型识别 / 智能赋码使用。
sync_token：云端同步使用。
sync_tenant：本次沈阳现场 tenant，默认 liaoning-seed-20260506。
delete_source_after_install：建议 true，安装成功后自动删除 onsite_secrets.json。
```

如果现场暂时不需要云端同步，但安装器当前要求 sync 字段存在，可以先填专用测试 token；不要乱填公开字符串。

### 2.2 安装私密配置

双击：

```text
安装现场私密配置.bat
```

或英文入口：

```text
01_INSTALL_PRIVATE_CONFIG.bat
```

成功后会生成：

```text
llm_client.local.json
sync_client.local.json
```

并把下面几个用户环境变量写入当前 Windows 用户：

```text
TAX_INVOICE_MIMO_API_KEY
TAX_INVOICE_SYNC_TOKEN
TAX_INVOICE_SYNC_TENANT
TAX_INVOICE_SYNC_ENDPOINT
```

---

## 3. 首次安装运行环境

双击：

```text
首次安装智能开票助手.bat
```

或英文入口：

```text
00_FIRST_INSTALL.bat
```

安装器会检查 / 准备：

```text
1. Python 3.11
2. .venv 虚拟环境
3. Python 依赖
4. Microsoft Edge / 浏览器组件
5. Tesseract OCR
6. 桌面快捷方式
```

完成后，日常启动用：

```text
启动智能开票助手.bat
```

或桌面快捷方式：

```text
智能开票助手
```

浏览器地址：

```text
http://127.0.0.1:5012
```

---

## 4. 配置验证

PowerShell 进入安装目录：

```powershell
cd C:\InvoiceAssistant
```

检查 LLM 配置：

```powershell
.\.venv\Scripts\python.exe -c "from tax_invoice_demo.llm_adapter import diagnose_llm_config; d=diagnose_llm_config(); print({'enabled':d.enabled,'provider':d.provider,'model':d.model,'api_key_configured':d.api_key_configured,'ready':d.ready,'issues':d.issues})"
```

期望：

```text
enabled: True
provider: mimo_openai
api_key_configured: True
ready: True
issues: []
```

检查客户档案缓存：

```powershell
.\.venv\Scripts\python.exe -c "from tax_invoice_demo.customer_profiles import profile_cache_summary; print(profile_cache_summary())"
```

期望至少看到：

```text
exists: True
seller_count: 16
buyer_count: 71
project_profile_count: 156
```

如果客户档案数量为 0，说明缓存没有随包放好或路径被移动，需要联系技术人员重新放入客户档案缓存。

---

## 5. 用今天 4 个 Excel 测试批量开票能力

测试材料在：

```text
test_materials\juteng_batch_excel_20260506\
```

包含：

```text
01_plastic_bucket.xls
02_i_beam.xls
03_dry_mix_plaster_mortar.xls
04_fire_extinguisher.xls
batch_test_input.txt
```

### 5.1 首页操作

打开：

```text
http://127.0.0.1:5012
```

建议填写：

```text
销售主体：沈阳聚腾商贸有限公司
```

文本区粘贴 `batch_test_input.txt` 内容，或使用：

```text
购买方：中铁二局集团有限公司
税号：91510100MA61RKR7X3
本次网采材料开一个点。4个Excel分别开票，每个Excel对应一张发票草稿。图片/文本只作为买方、票种、税点和备注参考。
```

勾选：

```text
批量开具发票
```

上传 4 个 Excel：

```text
01_plastic_bucket.xls
02_i_beam.xls
03_dry_mix_plaster_mortar.xls
04_fire_extinguisher.xls
```

点击生成草稿。

### 5.2 预期结果

应生成一个批量草稿包，里面有 4 张子草稿：

```text
一个 Excel = 一张子草稿
Excel 内多行 = 该发票的多行明细
```

预期金额：

```text
01_plastic_bucket.xls：102 行，合计 122326.40
02_i_beam.xls：19 行，合计 104560.72
03_dry_mix_plaster_mortar.xls：9 行，合计 72970.00
04_fire_extinguisher.xls：13 行，合计 36385.00
```

预期赋码能力：

```text
- 明细项目会先参考沈阳聚腾商贸有限公司的客户历史档案；
- 历史命中的项目会带出品类 / 编码 / 历史口径；
- 文本里明确“开一个点”时，税率以本次文本 1% 为准；
- 如果同一项目历史出现多个品类/编码，系统按最高频推荐并提示人工复核。
```

### 5.3 现场观察重点

```text
1. 是否生成 4 张子草稿；
2. 每张子草稿明细行数是否接近预期；
3. 金额合计是否接近预期；
4. 项目名称、规格型号、单位、数量、单价、金额是否从 Excel 带出；
5. 客户档案赋码是否命中；
6. 税率是否按文本里的“一点”处理；
7. 助理是否理解每个 Excel 单独开票。
```

---

## 6. 常见问题

### 6.1 运行安装脚本乱码

优先运行英文/数字入口：

```text
00_FIRST_INSTALL.bat
01_INSTALL_PRIVATE_CONFIG.bat
02_START_INVOICE_ASSISTANT.bat
```

### 6.2 LLM ready=False

检查：

```text
llm_client.local.json 是否存在；
api_key 是否真实；
endpoint / model 是否正确；
当前网络是否能访问 MiMo 接口。
```

### 6.3 客户档案数量为 0

检查是否存在：

```text
output\workbench\tax_invoice_demo\客户档案缓存.json
```

### 6.4 批量 Excel 没有生成 4 张草稿

检查：

```text
1. 是否勾选“批量开具发票”；
2. 是否一次上传了 4 个 Excel；
3. Excel 是否没有被 WPS/Excel 占用；
4. 是否上传成压缩包而不是直接上传 Excel 文件。
```

---

## 7. 后续调整策略

本次沈阳现场以完整安装包为主，不在现场叠加小更新包。

如果后续还有调整，重新输出新的完整安装包和配套私密配置包。
现场处理方式：

```text
1. 关闭当前工作台；
2. 备份或删除旧的 C:\InvoiceAssistant；
3. 解压新的完整安装包到 C:\InvoiceAssistant；
4. 解压配套私密配置包到 C:\InvoiceAssistant；
5. 运行 01_INSTALL_PRIVATE_CONFIG.bat；
6. 需要时重新运行 00_FIRST_INSTALL.bat；
7. 启动系统验证。
```

一句话：现场拿一套新的完整包重新落成，不靠小更新包叠补丁。

---

## 8. 安全提醒

```text
不要把 llm_client.local.json 发给客户或群里。
不要把 sync_client.local.json 发给客户或群里。
不要把 _onsite_private_config 发给客户或群里。
不要把填写真实 key 的 onsite_secrets.json 放进公开安装包。
```

完整安装包可以复制到 Windows；真实密钥只在现场电脑本机配置。
