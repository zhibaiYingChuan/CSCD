# C-S-C-D · 部署指南

> 面向**所有用户**：从仓库下载 → 部署 → 使用。核心原则是**可视化操作、零命令行摩擦**。

---

## 一、快速上手（30 秒）

用户从代码仓库下载整个仓库到本地后：

### 方式 A：Windows 双击（最简单）

1. 下载仓库，进入 `cscd/` 目录
2. **双击 `start.bat`**
3. 脚本自动完成：检查 Python → 安装依赖 → 引导填写端点 → 启动服务 → 打开浏览器

### 方式 B：可视化部署向导（网页）

1. 下载仓库，进入 `cscd/` 目录
2. 打开浏览器访问 **`http://127.0.0.1:8000/deploy`**（需先启动一次服务）
   - 或本地静态打开 `webui/frontend/deploy.html`
3. 按向导逐步操作：检测环境 → 填端点 → 复制启动命令 → 打开看板

### 方式 C：命令行（开发者）

```bash
cd cscd
python start_services.py            # 检查依赖 + 端点就绪 + 接入指引
python start_services.py --all      # 一键启动 WebUI(8000) + REST API(8001)
```

---

## 二、前置条件

| 依赖 | 说明 |
|------|------|
| Python 3.10+ | 必需，`start.bat` 会检查 |
| 模型端点 | OpenAI 兼容端点（`LLM_*` 或 `OPENAI_*`），**与你的 AI 工具共用同一个 Key**，自动检测 |

**模型名不预设默认**：请显式配置 `LLM_MODEL`/`OPENAI_MODEL`（如 `deepseek-chat`/`gpt-4o`/`claude-...`/你的本地模型）。

---

## 三、部署后能做什么

| 入口 | 地址 | 用途 |
|------|------|------|
| **部署向导** | `http://127.0.0.1:8000/deploy` | 可视化引导部署（第一入口） |
| **看板** | `http://127.0.0.1:8000` | 部署配置面板 + 效果展示（复制配置、看效果数据） |
| **REST API** | `http://127.0.0.1:8001` | 面向 SDK / 第三方调用的推理接口 |
| **MCP Server** | stdio | 接入 Continue / Cline / Claude Desktop（配置见 `.mcp.example.json`） |
| **Python SDK** | `from sdk import CSCDClient` | 应用内调用 |

---

## 四、排错

| 问题 | 解决 |
|------|------|
| 网页打不开 | 服务未启动。运行 `python start_services.py --all` 或双击 `start.bat` |
| 报"缺少模型名" | 设置 `LLM_MODEL`/`OPENAI_MODEL`（不预设默认） |
| 报 429 限流 | 端点 TPM 配额耗尽，已内置指数退避重试，等待恢复 |
| 复制配置后服务起不来 | MCP 配置的 `cwd` 用 `${workspaceFolder}` 占位符，或替换为你的实际路径 |

---

## 五、开发者

完整接入文档见 [DEVELOPER.md](DEVELOPER.md)。
