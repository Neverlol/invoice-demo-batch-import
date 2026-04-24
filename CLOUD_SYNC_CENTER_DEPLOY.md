# 云端数据回传中心部署

本文件用于把一期 `sync_center` 部署到云服务器。目标是先接住种子客户 Windows 工具回传的 case 事件，不在第一期引入复杂后台。

## 推荐环境

- Ubuntu 22.04 LTS
- 2C2G 起步，推荐 2C4G
- 开放端口：
  - `22`：SSH
  - `5021`：一期同步 API

后续正式对外建议加 Nginx/Caddy 和 HTTPS；第一轮小范围联调可以先用 `http://服务器IP:5021`。

## 目录约定

服务器上推荐放在：

```bash
/opt/invoice-demo-batch-import
```

如果放在其他目录，需要同步修改：

- `deploy/tax-invoice-sync-center.service`
- `/etc/tax-invoice-sync-center.env` 中的数据库路径

## 1. 准备服务器

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git curl
```

把项目代码放到：

```bash
sudo mkdir -p /opt/invoice-demo-batch-import
sudo chown -R "$USER":"$USER" /opt/invoice-demo-batch-import
```

如果服务器能访问 Git 仓库：

```bash
git clone <你的仓库地址> /opt/invoice-demo-batch-import
```

如果不能访问 Git，就先用压缩包或 scp 上传整目录。

## 2. 安装运行环境

```bash
cd /opt/invoice-demo-batch-import
bash deploy/setup_sync_center_runtime.sh
```

该脚本会：

- 创建 `.venv`
- 安装 `Flask + gunicorn`
- 创建 `output/sync_center`

## 3. 配置 token 和数据库

```bash
sudo cp deploy/sync-center.env.example /etc/tax-invoice-sync-center.env
sudo nano /etc/tax-invoice-sync-center.env
```

至少修改：

```text
TAX_INVOICE_CENTER_TOKEN=换成你自己的长随机token
TAX_INVOICE_CENTER_DB=/opt/invoice-demo-batch-import/output/sync_center/invoice_sync_center.sqlite3
```

token 会用于 Windows 客户端上报鉴权。

## 4. 安装 systemd 服务

```bash
sudo cp deploy/tax-invoice-sync-center.service /etc/systemd/system/tax-invoice-sync-center.service
sudo systemctl daemon-reload
sudo systemctl enable --now tax-invoice-sync-center
```

查看状态：

```bash
sudo systemctl status tax-invoice-sync-center --no-pager
```

查看日志：

```bash
journalctl -u tax-invoice-sync-center -f
```

## 5. 验证接口

服务器本机：

```bash
curl http://127.0.0.1:5021/api/invoice/events/health
```

本地电脑访问：

```bash
curl http://服务器公网IP:5021/api/invoice/events/health
```

如果访问不到，检查：

- 云服务器安全组是否开放 `5021`
- Ubuntu 防火墙是否开放 `5021`
- systemd 服务是否正在运行

Ubuntu 防火墙命令：

```bash
sudo ufw allow 5021/tcp
```

## 6. Windows 客户端配置

在发给种子客户的 Windows 包里放：

```text
sync_client.local.json
```

内容示例：

```json
{
  "enabled": true,
  "endpoint": "http://服务器公网IP:5021/api/invoice/events",
  "rules_endpoint": "",
  "token": "与服务器 TAX_INVOICE_CENTER_TOKEN 一致",
  "tenant": "shenyang-seed-a",
  "timeout_seconds": 8
}
```

客户正常使用工作台时，case 事件会自动尝试回传。网络失败时会先留在本地 pending 队列。

手动补发：

```bat
python tools\flush_case_events.py
```

## 7. 查询数据

健康检查：

```bash
curl http://127.0.0.1:5021/api/invoice/events/health
```

查询某个租户最近事件：

```bash
curl -H "Authorization: Bearer 你的token" \
  "http://127.0.0.1:5021/api/invoice/tenants/shenyang-seed-a/events?limit=20"
```

查询单个 case：

```bash
curl -H "Authorization: Bearer 你的token" \
  "http://127.0.0.1:5021/api/invoice/tenants/shenyang-seed-a/cases/CASE_ID"
```

## 8. 发布审核后的赋码规则包

一期先不做管理后台。你在中心端人工审核 `local_learned_rules_saved`、失败明细和成功样本后，可以直接用 API 给某个种子客户发布规则包。

示例：

```bash
curl -X POST \
  -H "Authorization: Bearer 你的token" \
  -H "Content-Type: application/json" \
  "http://127.0.0.1:5021/api/invoice/tenants/shenyang-seed-a/rules" \
  -d '{
    "version": "2026-04-24-a",
    "note": "人工审核后的第一批客户赋码规则",
    "rules": [
      {
        "raw_alias": "代理记账和税务申报",
        "normalized_invoice_name": "代理记账和税务申报",
        "tax_category": "纳税申报代理",
        "tax_code": "3040802050000000000",
        "tax_treatment_or_rate": "0.03",
        "decision_basis": "种子客户人工确认"
      }
    ]
  }'
```

查询最新规则包：

```bash
curl -H "Authorization: Bearer 你的token" \
  "http://127.0.0.1:5021/api/invoice/tenants/shenyang-seed-a/rules/latest"
```

Windows 客户端可手动拉取：

```bat
python tools\pull_rule_package.py
```

拉取后写入：

```text
output\workbench\tax_invoice_demo\客户同步赋码规则.csv
```

## 9. 从回传数据导出规则候选

中心端收到客户工具的 `local_learned_rules_saved` 事件后，可以导出一张候选审核 CSV：

```bash
python tools/export_rule_candidates.py --tenant shenyang-seed-a
```

输出位置类似：

```text
output/sync_center/rule_candidates/shenyang-seed-a_20260424_153000_规则候选.csv
```

审核方式：

- 保留要发布的行；
- 或把要发布的行 `status` 改成 `approved`；
- 不确定的行继续保持 `pending_review`。

把审核通过的 CSV 发布为客户规则包：

```bash
python tools/publish_rule_package_from_csv.py \
  --tenant shenyang-seed-a \
  --csv output/sync_center/rule_candidates/shenyang-seed-a_规则候选.csv \
  --token 你的token \
  --version 2026-04-24-a \
  --note "第一批审核通过赋码规则"
```

如果你只是内部快速验证，可以加 `--include-pending`，但发给客户前不建议这么做。

## 10. 备份

第一期核心数据是 SQLite 文件：

```bash
/opt/invoice-demo-batch-import/output/sync_center/invoice_sync_center.sqlite3
```

建议每天备份：

```bash
mkdir -p ~/invoice-sync-backups
cp /opt/invoice-demo-batch-import/output/sync_center/invoice_sync_center.sqlite3 \
  ~/invoice-sync-backups/invoice_sync_center_$(date +%Y%m%d_%H%M%S).sqlite3
```

## 11. 当前边界

当前中心端只负责：

- 接收 case 事件
- 去重
- 按 tenant 查询事件
- 按 case 查询 timeline
- 发布/查询最新客户赋码规则包
- 导出本地学习规则候选

暂不负责：

- 远程控制税局网页
- 多用户后台
- 原始文件长期存储
- 自动训练模型
- 规则审核后台界面

这些都属于后续阶段。
