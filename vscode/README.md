# C-S-C-D Reasoning · VS Code 扩展（Phase 3）

在 VS Code 中通过 C-S-C-D 结构化推理协议执行推理，查看四阶轨迹、认知控制审计、账本与效果看板。

## 功能

- **`C-S-C-D: 运行推理`** —— 输入任务，通过 WebUI 后端 `/api/reason` 执行 C-S-C-D 推理，在输出面板展示：
  - 最终精炼结论（替代式压缩）
  - 认知控制审计（工作空间 / 稠密轨 / 桥接概念 / 元认知动作 / 首轮锚定）
  - 账本信息（task_id / 条目数）
  - 完整四阶轨迹
- **`C-S-C-D: 打开效果看板`** —— 在浏览器打开部署配置面板 + 效果展示看板。

## 前置条件

1. 启动 C-S-C-D WebUI 后端（提供 `/api/reason`）：
   ```bash
   cd cscd/webui/backend
   export LLM_API_URL="https://your-endpoint"
   export LLM_API_KEY="sk-..."
   export LLM_MODEL="your-model-name"
   uvicorn main:app --host 127.0.0.1 --port 8000
   ```
2. 配置模型端点（`LLM_*` 或 `OPENAI_*`），否则 `/api/reason` 返回 503 引导错误。

## 安装（开发模式）

```bash
# 在 VS Code 中打开 cscd/vscode 目录
# 按 F5 启动扩展开发主机；或：
#   1. 代码包成 .vsix（npx @vscode/vsce package）
#   2. 安装：code --install-extension cscd-reasoning-0.1.0.vsix
```

## 配置

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `cscd.reasonApiUrl` | `http://127.0.0.1:8000/api/reason` | 推理后端 API |
| `cscd.dashboardUrl` | `http://127.0.0.1:8000` | 效果看板地址 |

## 说明

- 扩展通过 **HTTP 调用 WebUI 后端**（Phase 1 API），复用同一 `CscdEngine`，无需额外 MCP 客户端依赖。
- 亦可改为直接以 MCP 客户端方式接入（需要 `@modelcontextprotocol/sdk`），见 `DEVELOPER.md`。
