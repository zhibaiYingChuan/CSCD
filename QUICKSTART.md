# CSCD 快速上手指南

> 面向第一用户：从下载到跑通，全程 5 分钟。

---

## 一、你需要准备什么

| 项目 | 说明 |
|------|------|
| Python 3.10+ | 检查方式：`python --version` |
| pip | 检查方式：`pip --version` |
| 模型端点 API Key | 与你的 AI 工具共用同一个 Key（DeepSeek / OpenAI / Anthropic / 本地模型均可） |

> 如果你使用的是 **Windows 且已安装 Python**，直接跳到第二步。

---

## 二、安装依赖

**一键安装（推荐）：**

```bash
pip install fastapi "uvicorn[standard]" openai pydantic mcp
```

> 如果下载速度慢，加国内镜像源：
> ```bash
> pip install -i https://pypi.tuna.tsinghua.edu.cn/simple fastapi "uvicorn[standard]" openai pydantic mcp
> ```

**验证安装：**

```bash
python -c "import fastapi, uvicorn, openai, pydantic; print('依赖检查通过')"
```

---

## 三、配置模型端点

CSCD 会从环境变量自动发现你已配置的模型端点。

**方式 A：设置环境变量（推荐）**

```bash
set LLM_API_URL=https://your-endpoint
set LLM_API_KEY=sk-你的真实Key
set LLM_MODEL=your-model-name
```

> 也支持 `OPENAI_*`、`DEEPSEEK_*`、`ANTHROPIC_*`、`OPENROUTER_*` 等变量名，任一组已配置即可自动采用。

**方式 B：通过 `start.bat` 引导填写**

双击 `start.bat` 后会提示你输入端点信息，填写后自动保存为环境变量。

---

## 四、启动服务

### 推荐方式 1：双击 `launch.bat`（Windows 前台诊断模式）

1. 进入 `cscd/` 目录
2. 双击 `launch.bat`
3. 会出现一个命令行窗口，等待出现以下信息：

```
Uvicorn running on http://127.0.0.1:8000
```

4. 打开浏览器访问 `http://127.0.0.1:8000/deploy` 进入部署向导

> `launch.bat` 的窗口会持续显示日志，不会自动关闭。关闭窗口即停止服务。

### 推荐方式 2：命令行启动

```bash
# 检查依赖 + 端点就绪 + 接入指引
python start_services.py

# 一键启动 WebUI(8000) + REST API(8001)
python start_services.py --all
```

### 方式 3：日常使用 `start.bat`（后台模式）

确认 `launch.bat` 正常后，后续可直接双击 `start.bat`（无窗口后台运行）。

---

## 五、端口配置

| 端口 | 用途 | 修改方式 |
|------|------|---------|
| 8000 | WebUI 看板 + 部署向导 | 设置环境变量 `CSCD_WEBUI_PORT=8000` |
| 8001 | REST API | 设置环境变量 `CSCD_API_PORT=8001` |

**端口被占用时先停止旧服务：**

```bash
# 方式一：双击 stop.bat（会终止所有占用 8000/8001 的进程）
# 方式二：手动找占用进程
netstat -ano | findstr :8000
# 根据 PID 终止进程
taskkill /PID 进程ID /F
```

---

## 六、验证服务是否正常

**WebUI 看板：** 浏览器打开 `http://127.0.0.1:8000`

**REST API 健康检查：**

```bash
curl http://127.0.0.1:8001/health
```

返回如下表示正常：

```json
{"status":"ready","ready":true,"auth_required":true}
```

**部署向导：** 浏览器打开 `http://127.0.0.1:8000/deploy`，页面会显示：
- 环境检测结果
- 模型端点状态
- 一键复制 MCP 配置 / 启动命令

---

## 七、常见报错排查

### 问题 1：页面显示"拒绝连接"（Connection Refused）

| 原因 | 解决 |
|------|------|
| 服务未启动 | 先双击 `launch.bat` 启动服务 |
| 启动后窗口自动关闭 | 双击 `launch.bat`（非 `start.bat`），查看错误信息 |
| 端口配置不一致 | 确认浏览器访问的端口与启动日志中的端口一致 |

### 问题 2：端口被占用（OSError: [Errno 10048] ...）

```bash
# 先停止旧服务
双击 stop.bat
# 或手动终止
netstat -ano | findstr :8000
taskkill /PID 进程ID /F
# 然后重新启动
```

### 问题 3：提示"Python 找不到"或"python 不是内部或外部命令"

- 前往 [python.org](https://www.python.org/downloads/) 下载 Python 3.10+
- 安装时勾选 **"Add Python to PATH"**
- 安装完成后重新打开命令行

### 问题 4：提示"缺少模块"或"ModuleNotFoundError"

```bash
pip install fastapi "uvicorn[standard]" openai pydantic mcp
```

### 问题 5：服务启动后提示"缺少模型名"或"未配置端点"

- 确保已设置 `LLM_API_URL`、`LLM_API_KEY`、`LLM_MODEL` 三个环境变量
- 模型名必须显式设置（如 `deepseek-chat`、`gpt-4o`、`claude-3-opus` 等），不预设默认值
- 如果使用 `start.bat`，按提示输入即可

### 问题 6：终端打印乱码或 ✓✗ 符号报错

在运行前设置：

```bash
set PYTHONIOENCODING=utf-8
```

### 问题 7：调用推理报 429 RateLimit

- 模型端点 TPM（每分钟 Token）配额耗尽
- CSCD 已内置指数退避重试（1 秒 → 2 秒 → 4 秒，最多 3 次），等待片刻即可恢复

### 问题 8：页面显示"not_ready"或 503

- 服务已启动但未检测到模型端点
- 配置环境变量后重启服务
- 或通过 `/deploy` 页面引导配置

---

## 八、快速测试

启动成功后，用以下命令测试推理是否正常：

```bash
curl -X POST http://127.0.0.1:8001/v1/reason ^
  -H "Content-Type: application/json" ^
  -H "X-API-Key: 你的Key" ^
  -d "{\"question\":\"1+1等于几？\"}"
```

返回 `{"reason": "2", ...}` 即表示推理链路正常。

---

## 九、下一步

- **部署向导**：`http://127.0.0.1:8000/deploy` — 可视化配置与启动
- **效果看板**：`http://127.0.0.1:8000` — 查看缓存命中率、Token 节省、精准度
- **MCP 接入**：配置到 Continue / Cline / Claude Desktop，见 `.mcp.example.json`
- **Python SDK**：`from sdk import CSCDClient`，零第三方依赖
- **完整文档**：见 [README.md](README.md) / [DEPLOY.md](DEPLOY.md) / [DEVELOPER.md](DEVELOPER.md)