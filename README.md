# C-S-C-D 结构化推理验证系统

> CSCD（Decompose–Classify–Select–Combine）是一个结构化推理验证系统。
>
> 它不承诺改变模型的内部推理、提升模型能力或消除幻觉；它将复杂问题转化为可验证、可追溯、可审计的推理框架，帮助用户区分证据、假设、解释和噪音，并形成分层结论。
>
> CSCD 的主场景是科研假设验证，也适用于技术评审、方案论证和合规审计等需要追踪推理依据的复杂问题。

---

## 快速开始

| 步骤 | 操作 |
|------|------|
| 1. 安装依赖 | `pip install fastapi "uvicorn[standard]" openai pydantic mcp` |
| 2. 配置端点 | 设置 `LLM_API_URL`、`LLM_API_KEY`、`LLM_MODEL`（与你的 AI 工具共用同一个 Key） |
| 3. 启动服务 | 双击 `start.bat`（Windows）或 `python start_services.py --all` |
| 4. 打开看板 | 浏览器访问 `http://127.0.0.1:8000` |

> 更详细的指引见 [QUICKSTART.md](QUICKSTART.md)（新用户上手指南）。

---

## 核心能力

CSCD 通过四个阶段处理复杂问题：

| 阶段 | 能力 | 输出 |
|------|------|------|
| **DECOMPOSE 拆解** | 将复杂问题拆成可验证的原子子问题 | 问题清单、边界和依赖 |
| **CLASSIFY 分类** | 区分事实、假设、合理解释和噪音 | 证据类别与不确定性 |
| **SELECT 选择** | 识别最关键的路径、阻塞点和验证优先级 | 关键子问题与选择理由 |
| **COMBINE 组合** | 基于证据形成分层结论 | 已成立、待验证、不能成立的结论 |

### 能力边界

CSCD：

- 让推理过程更结构化、可追溯和可审计；
- 帮助发现证据缺口、隐含假设和论证风险；
- 输出可继续执行的验证问题和实验设计草稿。

CSCD 不保证：

- 改变模型内部推理或提升模型本身能力；
- 消除幻觉；
- 自动保证结论正确；
- 用结构化格式替代论文、数据或真实实验。

---

## 典型使用场景

### 科研推理验证

适合研究生、博士后和独立研究者，用于：

- 拆解科研假设；
- 整理文献综述问题；
- 区分实验事实与待验证主张；
- 识别关键验证路径；
- 形成实验设计草稿；
- 记录结论的证据边界。

### 复杂问题结构化

适合技术评审、架构决策和合规审计，用于：

- 追踪决策依据；
- 标注假设和不确定性；
- 识别风险与阻塞点；
- 形成可复核的论证框架。

---

## 架构

```
用户任务
  │
  ▼
┌─────────────────────────────────────┐
│  CscdEngine (core/cscd.py)          │
│  · 四阶段结构化推理                 │
│  · 证据、假设和风险边界分类         │
│  · 关键问题选择与验证优先级         │
│  · 运行轨迹和结论审计               │
│  · 结果压缩与跨调用留痕             │
└──────────────┬──────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│  OpenAICarrier → 真实模型端点         │
│  (LLM_API_URL / OPENAI_BASE_URL 等)  │
│  内置指数退避重试 + 空响应回退        │
└──────────────────────────────────────┘
```

---

## 接入方式

| 方式 | 入口 | 适用场景 |
|------|------|---------|
| **MCP Server** | `python cscd_mcp_server.py` | 接入 Continue / Cline / Claude Desktop 等 MCP 客户端 |
| **WebUI 看板** | `http://127.0.0.1:8000` | 部署向导 + 效果看板（复制配置、查看数据） |
| **REST API** | `http://127.0.0.1:8001` | 面向 SDK / 第三方调用的推理接口 |
| **VS Code 扩展** | `vscode/` | 在 VS Code 中直接运行推理 |
| **Python SDK** | `from sdk import CSCDClient` | 应用内调用（零第三方依赖） |

### MCP 配置示例

```json
{
  "mcpServers": {
    "cscd-protocol": {
      "command": "python",
      "args": ["cscd_mcp_server.py"],
      "cwd": "${workspaceFolder}",
      "env": {
        "LLM_API_URL": "https://your-endpoint",
        "LLM_API_KEY": "${env:LLM_API_KEY}",
        "LLM_MODEL": "your-model-name"
      }
    }
  }
}
```

### REST API 调用示例

```bash
curl -X POST http://127.0.0.1:8001/v1/reason \
  -H "Content-Type: application/json" \
  -H "X-API-Key: 你的Key" \
  -d '{"question":"设计带权限的 TODO 后端 API"}'
```

返回 `reason`（精炼结论）、`cognition`（认知控制审计）、`ledger`（账本审计）等字段。

### Python SDK 调用示例

```python
from sdk import CSCDClient
client = CSCDClient("http://127.0.0.1:8001", api_key="your-key")
r = client.reason("设计带权限的 TODO 后端 API")
print(r["reason"])
```

---

## 技术能力

- **四阶段结构化协议**：DECOMPOSE → CLASSIFY → SELECT → COMBINE
- **证据边界标注**：区分事实、待验证假设、合理解释和噪音
- **关键路径选择**：识别最需要优先验证的子问题
- **运行轨迹审计**：保存推理阶段、验证反馈、动作和交付证据
- **反馈修订支持**：在有真实验证器时记录失败证据和后续修订
- **多种接入方式**：MCP、REST API、WebUI、CLI、Python SDK 和 VS Code
- **结果持久化**：通过 Workspace、Trace 和 Ledger 保存可追溯记录

这些是结构化验证和审计能力，不代表模型内部推理被修改，也不代表结论自动正确。

---

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_API_URL` / `OPENAI_BASE_URL` | 模型端点 URL | — |
| `LLM_API_KEY` / `OPENAI_API_KEY` | API Key | — |
| `LLM_MODEL` / `OPENAI_MODEL` | 模型名 | `deepseek-chat` |
| `CSCD_API_KEY` | REST API 独立鉴权凭证（推荐） | 回退到模型 Key |
| `CSCD_ADMIN_KEY` | 管理员接口 /v1/usage/all 鉴权 | — |
| `CSCD_ALLOW_ORIGINS` | CORS 允许源（逗号分隔） | `http://127.0.0.1:8000,http://localhost:8000` |
| `CSCD_WEBUI_PORT` | WebUI 端口 | 8000 |
| `CSCD_API_PORT` | REST API 端口 | 8001 |
| `CSCD_TIMEOUT` | 模型调用超时（秒） | 60 |

---

## 文档索引

| 文档 | 目标读者 | 内容 |
|------|---------|------|
| [QUICKSTART.md](QUICKSTART.md) | 新用户 | 依赖安装、启动、端口配置、常见报错排查 |
| [DEPLOY.md](DEPLOY.md) | 所有用户 | 部署方式（双击/网页/命令行） |
| [DEVELOPER.md](DEVELOPER.md) | 开发者 | MCP 配置、API 参考、FAQ、代码调用 |
| [protocol.md](protocol.md) | 协议研究者 | 四阶标记语言 + 五层架构规范 |
| [cscd-system-prompt.md](cscd-system-prompt.md) | 集成者 | 可直接复制的 System Prompt 模板 |
| [cscd-agent-guide.md](cscd-agent-guide.md) | MCP 集成者 | 宿主 Agent 调用规则、验证门禁与审计工作流 |
| [docs/CSCD_Product_Guide.md](docs/CSCD_Product_Guide.md) | 产品与科研用户 | 产品定位、科研场景、能力边界和验收方式 |
| [webui/README.md](webui/README.md) | WebUI 用户 | 看板功能、API 一览、Windows 启动排查 |
| [vscode/README.md](vscode/README.md) | VS Code 用户 | 扩展安装与配置 |
| `.mcp.example.json` | MCP 用户 | MCP 客户端配置示例 |

---

## 项目结构

```
cscd/
├── core/              # 协议引擎（cscd/assess/classify/cognition/compressor/ledger/marks）
├── carriers/          # 载体（OpenAI 兼容 + CodeBuddy + 预置样本）
├── sdk/               # Python SDK（零第三方依赖）
├── webui/             # 前端 + 后端（FastAPI 静态托管）
├── vscode/            # VS Code 扩展
├── api_server.py      # REST API（端口 8001）
├── cscd_mcp_server.py # MCP Server（stdio）
├── orchestrator.py    # CLI 入口
├── config.yaml        # 推理配置（轮次/预算/缓存）
├── start.bat / launch.bat / stop.bat / start_services.py  # 启动脚本
└── *.md               # 文档
```

---

## 许可

C-S-C-D 协议本体为开放协议，可自由复制、修改、集成到任何工具链中。

本仓库代码按 MIT 许可证开源。