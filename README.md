# C-S-C-D 推理编排协议

> 一套 **System Prompt 级别的结构化推理协议**，可注入任何支持 Function Calling / System Prompt 注入的模型调用中，强制模型按四阶标记语言输出可审计的推理轨迹。
>
> ——它不是「已证明有效的优化器」，而是一种**可选的、有明确结构的推理框架**，把「拆解-分类-选择-组合」的人类工程方法论形式化为机器可执行、可审计、可插拔的协议。

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

## 架构

```
用户任务
  │
  ▼
┌─────────────────────────────────────┐
│  CscdEngine (core/cscd.py)          │
│  · 方向Y 短路（simple 任务基线直答） │
│  · 四阶递归推理                     │
│  · 编排级单原子缓存                 │
│  · 认知控制层（J-Space）            │
│  · 运行时账本外化                   │
│  · 替代式压缩（终端输出削减 87%）    │
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
      "cwd": "${workspaceFolder}/cscd",
      "env": {
        "LLM_API_URL": "https://api.deepseek.com",
        "LLM_API_KEY": "${env:LLM_API_KEY}",
        "LLM_MODEL": "deepseek-chat"
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

## 核心特性

- **四阶递归**：DECOMPOSE → CLASSIFY → SELECT → COMBINE，模型显式输出结构化推理轨迹
- **方向Y 短路**：simple 任务自动走基线直答，零协议开销
- **认知控制层**：工作空间管理（≤5 项激活）、稠密轨符号系统、桥接推理检查点、元认知动作选择
- **编排级缓存**：单原子级复用，同任务内多轮递归命中率可达 1/3 轮次
- **替代式压缩**：终端回传仅保留压缩摘要，削减 87% 输出 Token
- **运行时账本**：推理过程外化到磁盘，支持跨调用/跨会话恢复
- **全维度安全加固**：CORS 收紧、独立鉴权凭证、Key 哈希落盘、管理员区分、输入校验

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
| [cscd-agent-guide.md](cscd-agent-guide.md) | MCP 集成者 | 宿主 Agent 调用规则与工作流 |
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