# 智能开票助手交付包说明

## 为什么文件名改成英文/数字

Windows 自带解压工具有时会把 ZIP 里的中文文件名解析成乱码。

所以现场交付包从本版开始，助理需要点击的文件统一改成英文/数字文件名：

```text
00_FIRST_INSTALL.bat
01_INSTALL_PRIVATE_CONFIG.bat
02_START_INVOICE_ASSISTANT.bat
03_START_TAX_BROWSER.bat
04_START_WORKBENCH.bat
05_OPEN_GUIDE.bat
README_ONSITE_CN.md
```

文件内容仍然是中文提示。

## 新电脑安装顺序

如果是第一次在这台电脑上使用：

```text
1. 解压公开完整安装包到 C:\invoice-assistant\ 或 C:\智能开票助手\
2. 如果需要 MiMo / 阿里云 / 云端客户档案，解压私密配置包到同一目录
3. 双击 01_INSTALL_PRIVATE_CONFIG.bat
4. 双击 00_FIRST_INSTALL.bat
5. 以后每天双击桌面“智能开票助手”
```

如果暂时没有私密配置包，也可以先跳过第 3 步，只测试本地界面和基础流程。

## 日常启动

优先：

```text
02_START_INVOICE_ASSISTANT.bat
```

分步：

```text
03_START_TAX_BROWSER.bat
04_START_WORKBENCH.bat
```

## 私密配置包目录

推荐私密配置包使用英文目录名，避免乱码：

```text
_onsite_private_config/
  onsite_secrets.json
```

旧版中文目录 `_现场私密配置` 仍兼容，但不再推荐。

## 不要操作的技术文件

现场助理不用打开：

```text
app.py
tax_invoice_demo/
tax_invoice_batch_demo/
templates/
static/
tools/
windows_bootstrap/
.venv/
output/
```
