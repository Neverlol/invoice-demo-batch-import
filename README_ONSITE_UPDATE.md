# 现场更新说明

适用场景：沈阳现场测试期间，客户 Windows 电脑无法稳定访问 GitHub，不能依赖 `git pull`，也不要手动复制单个文件覆盖。

## 固定目录

项目目录：

```text
C:\invoice-assistant-staging-19d4851\
```

更新相关目录会由脚本自动创建：

```text
updates\latest.zip       # 等待应用的最新更新包
backups\                 # 每次更新前的自动备份
update_logs\             # 更新/回滚日志
VERSION.txt              # 当前已应用版本
```

## 标准更新流程

1. 关闭当前工作台窗口 / Flask 命令行窗口。
2. 把收到的最新更新包复制到：

```text
C:\invoice-assistant-staging-19d4851\updates\latest.zip
```

3. 双击：

```text
APPLY_UPDATE.bat
```

4. 更新完成后，重新双击：

```text
02_START_INVOICE_ASSISTANT.bat
```

5. 浏览器按：

```text
Ctrl + F5
```

## 回滚流程

如果更新后明显异常：

1. 关闭当前工作台窗口 / Flask 命令行窗口。
2. 双击：

```text
RESTORE_LAST_BACKUP.bat
```

3. 重新双击：

```text
02_START_INVOICE_ASSISTANT.bat
```

4. 浏览器按 `Ctrl + F5`。

## 注意事项

- 现场不要运行 GitHub pull。
- 现场不要手动复制单个文件覆盖。
- 每次只使用一个最新累计包，放到 `updates\latest.zip`。
- 更新包不应包含私密配置，例如：
  - `sync_client.local.json`
  - `llm_client.local.json`
  - `onsite_secrets.local.json`
- 如果更新失败，先查看 `update_logs\` 里的最新日志。
