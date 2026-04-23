# Git 同步开发说明

这份说明只解决一件事：

`Mac 开发 -> Windows 测试`

以后不再主要靠 LocalSend 来回整个文件夹，而是改成：

`Mac 提交代码 -> 推送远端仓库 -> Windows git pull -> 直接启动测试`

---

## 为什么不用 Docker 解决这个问题

当前你遇到的主要问题是**代码同步效率低**，不是“后端服务环境不一致”。

所以现在最该上的工具是：

- `Git`
- `GitHub / Gitee / 私有 Git 仓库`

而不是 Docker。

Docker 后面仍然有用，但更适合：

- 中央 FastAPI 服务
- PostgreSQL
- 日志同步服务

不适合当前这条税局 live 主线：

- Windows
- Edge 真浏览器
- 人工登录态
- CDP 附着

---

## 当前推荐工作流

### 日常开发

1. 在 Mac 上改代码
2. `git add`
3. `git commit`
4. `git push`
5. 在 Windows 上运行：
   - `update_and_start.bat`

### 首次部署

首次部署仍然可以用你现在的整包目录，因为这个目录里包含：

- Python / Tesseract 安装资源
- wheels
- tessdata

这些大文件**不建议纳入 Git 同步仓库**，否则每次 push / pull 都会很慢。

所以推荐做法是：

- **开发同步仓库**：只同步代码、模板、数据和文档
- **客户交付整包**：仍从你本地完整目录导出

---

## 一、Mac 端首次设置

以下操作在：

`/Volumes/NeverlolDisk/NeverlolDB/1.Project-Current/AI-Tools/VibeCoding/19-skill开发/invoice-demo-batch-import`

目录执行。

### 1. 初始化仓库

```bash
cd /Volumes/NeverlolDisk/NeverlolDB/1.Project-Current/AI-Tools/VibeCoding/19-skill开发/invoice-demo-batch-import
git init
git branch -M main
```

### 2. 添加当前代码

```bash
git add .
git commit -m "init: invoice demo batch import dev repo"
```

### 3. 绑定远端仓库

你可以选：

- GitHub 私有仓库
- Gitee 私有仓库
- 自己的私有 bare repo

例如：

```bash
git remote add origin <你的仓库地址>
git push -u origin main
```

---

## 二、Windows 端首次设置

### 推荐方式：保留现有工作目录，另外准备一份 Git 同步目录

如果你当前 Windows 里已经有一个可运行的：

`C:\invoice-demo-batch-import`

那最稳妥的方式是：

1. 先保留这份目录不动，作为当前可运行副本
2. 安装 Git for Windows
3. 新建一个 Git 同步目录，例如：

```text
C:\invoice-demo-batch-import-git
```

4. 在这个新目录 clone 仓库：

```bat
cd /d C:\
git clone <你的仓库地址> invoice-demo-batch-import-git
```

5. 把老目录里的本地资源复制到新目录：

- `windows_bootstrap\installers`
- `windows_bootstrap\wheels`
- `windows_bootstrap\tessdata`
- 如需保留当前环境，也可复制：
  - `.venv`
  - `output`

6. 后续就用新目录开发测试。

### 为什么推荐这样做

因为这是最稳的，不会碰坏你现在已经能跑的目录。

---

## 三、Windows 端之后的日常使用

以后每次 Mac 推送完，Windows 端只做：

```text
双击 update_and_start.bat
```

这个脚本会：

1. 检查当前目录是否是 Git 仓库
2. 执行 `git fetch origin`
3. 执行 `git pull --ff-only`
4. 拉到最新代码后启动 `start_lean_workbench.bat`

如果你已经开好了税局 Edge，也可以只运行：

```text
update_only.bat
```

---

## GitHub 私有仓库快速接入

如果你决定用 **GitHub 私有仓库**，推荐按下面这套最简单的方式走。

### A. 在 GitHub 网页端创建仓库

参考 GitHub 官方文档：

- [Creating a new repository](https://docs.github.com/articles/creating-a-new-repository)
- [Cloning a repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository?platform=windows)

实际操作：

1. 打开 GitHub，右上角 `+`
2. 点击 `New repository`
3. 仓库名建议直接用：

```text
invoice-demo-batch-import
```

4. 选择：

- `Private`

5. **不要勾选**：

- `Add a README file`
- `.gitignore`
- `Choose a license`

原因是你本地已经有完整目录，如果新仓库再预置文件，第一次 push 容易多一次不必要的合并。

6. 创建完成后，复制仓库 HTTPS 地址，例如：

```text
https://github.com/<你的用户名>/invoice-demo-batch-import.git
```

### B. Mac 端首次推送

在 Mac 里执行：

```bash
cd /Volumes/NeverlolDisk/NeverlolDB/1.Project-Current/AI-Tools/VibeCoding/19-skill开发/invoice-demo-batch-import
git init
git branch -M main
git add .
git commit -m "init: invoice demo batch import dev repo"
git remote add origin https://github.com/<你的用户名>/invoice-demo-batch-import.git
git push -u origin main
```

如果 GitHub 弹认证：

- 直接按浏览器登录流程完成即可
- 或使用 GitHub Personal Access Token

### C. Windows 端 clone

Windows 安装完 Git for Windows 后，在命令行执行：

```bat
cd /d C:\
git clone https://github.com/<你的用户名>/invoice-demo-batch-import.git invoice-demo-batch-import-git
```

然后把原来目录里的大资源复制过去：

- `windows_bootstrap\installers`
- `windows_bootstrap\wheels`
- `windows_bootstrap\tessdata`

如需保留现有测试环境，也可以复制：

- `.venv`
- `output`

### D. 以后每天怎么用

#### Mac

```bash
git add .
git commit -m "你的修改说明"
git push
```

#### Windows

双击：

```text
update_and_start.bat
```

就可以自动：

- `git fetch`
- `git pull --ff-only`
- 启动工作台

### E. 认证建议

为了减少你后面反复输密码，推荐：

- Mac：用 GitHub Desktop 或系统钥匙串保存认证
- Windows：安装 Git for Windows 时保留 `Git Credential Manager`

这样后续 `git push / pull` 基本就能自动记住登录态。

---

## 四、哪些内容不建议进 Git

当前 `.gitignore` 已排除以下内容：

### 运行产物

- `output/`
- `*.log`
- `*.sqlite`
- `*.db`

### Python 运行环境

- `.venv/`
- `__pycache__/`
- `*.pyc`

### 本地同步状态

- `pending_events.jsonl`
- `pending_uploads/`
- `last_sync_state.json`

### 大体积 Windows 安装资源

- `windows_bootstrap/installers/`
- `windows_bootstrap/wheels/`
- `windows_bootstrap/tessdata/`

这些资源仍然保留在你的本地目录里，不会因为 `.gitignore` 消失，只是不参与日常代码同步。

---

## 五、推荐的 Git 使用原则

### 1. 每次功能点尽量单独 commit

例如：

- `fix: batch preview locator`
- `feat: add llm adapter skeleton`
- `ui: tighten lean input composer`

### 2. Windows 不直接改主代码

推荐流程：

- Mac 开发
- Windows 只验证
- 如果 Windows 测出问题，记录后回到 Mac 修

后续如果你要进一步提效，再加：

- Mac 直接 SSH / 远程桌面到 Windows 修 live 问题

### 3. 交付客户时仍然从“完整本地目录”打包

也就是：

- Git 仓库用于同步开发
- 客户交付包仍然从你当前完整目录导出

这样既保证开发轻量，也不影响客户部署。

---

## 六、下一步最值得做的提效项

完成 Git 同步后，下一步最值得加的是：

1. `update_and_start.bat`
2. `update_only.bat`
3. 后续视情况增加：
   - Mac 到 Windows 的远程修补能力
   - 中央服务 Docker 化

当前不要优先折腾：

- Docker 承载税局 live 执行
- 本地大模型替代
- 多机共享文件夹方案

这些都不如 Git 直接有效。
