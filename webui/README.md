# C-S-C-D 部署与推理验证看板

> **网页端 = 部署指南 + 结构化推理验证看板，不是模型能力增强器，也不是在线正确性保证工具。** 用户打开网页后无需输入内容或配置 API Key，即可复制配置完成部署，并查看结构化推理、证据边界和审计轨迹示例。

## 定位

| 板块 | 内容 |
|------|------|
| **① 部署配置区（一键复制）** | MCP 服务配置 JSON、环境变量示例和启动命令，用户复制到自己的工具完成部署 |
| **② 推理验证展示区** | 四阶段推理轨迹、事实与假设分类、关键问题选择、验证反馈和审计记录示例 |

## 功能

- **部署配置**：三个标签页（MCP JSON / 环境变量 / 启动命令），一键复制到剪贴板
- **结构化验证展示**：展示 DECOMPOSE → CLASSIFY → SELECT → COMBINE 轨迹和证据边界
- **审计轨迹示例**：查看推理阶段、验证反馈和结果持久化记录
- **深/浅主题切换**、响应式

> 看板中的示例用于说明产品输出结构和审计方式，不代表模型能力提升、结论自动正确或对所有任务成立。

## 目录结构

```
webui/
├── backend/
│   ├── main.py               # FastAPI 入口（静态托管前端 + API）
│   ├── services/cscd_service.py  # 对接 CscdEngine 的推理门面
│   ├── models/schemas.py     # Pydantic 请求/响应模型
│   └── storage/history.py    # 历史记录（JSONL）
├── frontend/
│   ├── index.html            # 单页应用
│   ├── style.css             # 深/浅主题、响应式
│   └── app.js                # 交互逻辑
└── README.md
```

## 部署

### 前置：安装依赖
```bash
pip install fastapi "uvicorn[standard]" pydantic openai
```

### 1. 本地运行
```bash
cd cscd/webui/backend
export OPENAI_BASE_URL="https://your-endpoint"
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL="your-model-name"     # 可选，默认 deepseek-chat
uvicorn main:app --host 127.0.0.1 --port 8000
# 打开 http://127.0.0.1:8000
```

### 2. 局域网（团队使用）
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 3. 公网部署
建议前置反向代理（Nginx/Caddy）加 HTTPS，把 8000 端口对外暴露为域名。

## API 一览

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 统一健康检查（与 REST API `api_server` 一致） |
| `/api/status` | GET | 服务状态与模型配置 |
| `/api/reason` | POST | 执行一次 CSCD 推理，返回结构化结果 |
| `/api/history` | GET | 历史记录（`?q=` 搜索、`limit/offset` 分页） |
| `/api/history/{id}` | DELETE | 删除一条记录 |
| `/api/export/{id}` | GET | 导出某次调用完整记录（JSON） |
| `/` | GET | 前端页面 |

### `POST /api/reason` 请求体
```json
{
  "question": "设计带权限控制的 TODO 应用后端 API",
  "has_untrusted_input": false,
  "named_modules": null
}
```

### 响应字段（节选）
`reason`（终端精炼结论）、`final_context`、`raw_reason`（四阶轨迹审计）、`summaries`（每轮压缩摘要）、`complexity`/`strategy`、`rounds`/`planned_rounds`、`marks_valid`、`cache_hits`/`cache_saved_tokens`、`total_completion_tokens`。

## Windows 双击启动与排查

项目根目录提供两个启动入口：

- `start.bat`：后台启动模式，适合日常使用；服务进程与启动窗口分离。
- `launch.bat`：前台诊断模式，适合首次启动或排查问题；当前窗口会持续显示 Uvicorn 实时日志。

推荐首次使用时双击 `launch.bat`，确认窗口出现以下信息后再访问 `http://127.0.0.1:8000`：

```text
Uvicorn running on http://127.0.0.1:8000
```

如果页面显示“拒绝连接”：

1. 不要关闭 `launch.bat` 窗口，先复制窗口中的完整错误信息。
2. 如果提示 `No module named ...`，在项目根目录执行：
   `python -m pip install fastapi "uvicorn[standard]" openai pydantic`
3. 如果提示端口被占用，关闭占用 8000 端口的旧服务，或先双击 `stop.bat`。
4. 如果提示 Python 未找到，请安装 Python 3.10+ 并启用 `Add Python to PATH`。
5. 服务正常启动后，打开 `http://127.0.0.1:8000/deploy` 可进入部署向导。

`launch.bat` 不使用 `pythonw`，不会隐藏启动错误。只有确认前台模式正常后，才建议使用 `start.bat`。

## 说明

- 后端未配置模型端点时，`/api/status` 返回 `not_ready`，`/api/reason` 返回 503 与引导信息。
- 历史记录存储于 `backend/data/history.jsonl`；如需换 SQLite/IndexedDB，替换 `storage/history.py` 即可。
