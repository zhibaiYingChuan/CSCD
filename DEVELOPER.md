# C-S-C-D · 开发者接入文档（Phase 2）

> 面向**开发者（技术用户）** 的接入指南。涵盖：MCP 配置、`cscd_reason` 调用参数、
> 6 工具 + 3 资源 API 参考、常见问题与排错。核心逻辑与架构见 [README.md](README.md)。

---

## 一、架构速览

```
┌──────────────┐    stdio/SSE     ┌──────────────────────────────┐
│  MCP 客户端   │ ──────────────► │  cscd_mcp_server.py (FastMCP) │
│  Continue/    │                  │  · 6 Tools + 3 Resources      │
│  Cline/Claude │ ◄──────────────  │  · _make_engine() 装配引擎     │
└──────────────┘                  └──────────────────────────────┘
                                           │ 复用同一引擎
                                           ▼
                             ┌──────────────────────────┐
                             │  CscdEngine (core/cscd)  │
                             │  方向Y短路/四阶递归/压缩/ │
                             │  单原子缓存/认知控制/账本  │
                             └──────────────────────────┘
                                           │
                                           ▼
                          OpenAICarrier → 真实模型端点
                          (LLM_API_URL / OPENAI_BASE_URL)
```

---

## 二、模型端点配置

`cscd_reason`/`cscd_ledger` 通过环境变量读取端点，支持两套变量（`LLM_*` 优先）：

| 变量 | 说明 |
|------|------|
| `LLM_API_URL` / `OPENAI_BASE_URL` | OpenAI 兼容端点 URL |
| `LLM_API_KEY` / `OPENAI_API_KEY` | API Key |
| `LLM_MODEL` / `OPENAI_MODEL` / `CSCD_MODEL` | 模型名（默认 `deepseek-chat`） |

> 未配置端点时，`cscd_reason` 返回清晰引导错误；配置后即可发起真实推理。

---

## 三、MCP 客户端接入配置

### 3.1 Continue
编辑 `~/.continue/config.json` 的 `mcpServers`。**路径用相对占位符，不要写死绝对路径**。`cwd` 应指向仓库根目录（克隆后即为产品根目录）：
```json
{
  "mcpServers": [
    {
      "name": "cscd-protocol",
      "command": "python",
      "args": ["cscd_mcp_server.py"],
      "cwd": "${workspaceFolder}",
      "env": {
        "LLM_API_URL": "https://your-endpoint",
        "LLM_API_KEY": "${env:LLM_API_KEY}",
        "LLM_MODEL": "your-model-name"
      }
    }
  ]
}
```

### 3.2 Cline
编辑 `cline_mcp_settings.json`，`cwd` 指向你的仓库根目录（克隆后即为产品根目录）：
```json
{
  "mcpServers": {
    "cscd-protocol": {
      "command": "python",
      "args": ["cscd_mcp_server.py"],
      "cwd": "${workspaceFolder}",
      "env": { "LLM_API_URL": "https://your-endpoint",
               "LLM_API_KEY": "${env:LLM_API_KEY}", "LLM_MODEL": "your-model-name" }
    }
  }
}
```

### 3.3 Claude Desktop
编辑 `claude_desktop_config.json`。`args` 用脚本**相对路径**（配合 `cwd`），或写你的**绝对安装路径**：
```json
{
  "mcpServers": {
    "cscd-protocol": {
      "command": "python",
      "args": ["cscd_mcp_server.py"],
      "cwd": "${workspaceFolder}",
      "env": { "LLM_API_URL": "https://your-endpoint",
               "LLM_API_KEY": "${env:LLM_API_KEY}", "LLM_MODEL": "your-model-name" }
    }
  }
}
```

> **可移植性**：`${workspaceFolder}` / `${env:VAR}` 是 MCP 客户端的通用变量占位符，会自动替换为你当前工作区路径与已设置的环境变量，避免硬编码本机绝对路径。若你的客户端不支持变量，请把 `cwd`/`args` 替换为你的实际路径。
> ⚠️ 必须在 `env` 中透传 `LLM_*`/`OPENAI_*`（或让服务进程继承），否则子进程读不到端点，`cscd_reason` 会报缺配置。

---

## 四、运行时工作空间与阶段

### 4.1 持久化结构

每个任务会在 `.cscd/` 下产生可审计数据（目录可用 `CSCD_RUNTIME_DIR` 覆盖）：

```text
.cscd/
├── workspace/          # 当前状态投影
│   ├── goal.md         # 目标与完成条件
│   ├── verified.md     # 已验证事实
│   ├── open.md         # 开放问题
│   └── next.md         # 下一步动作
├── traces/
│   └── task.jsonl      # 事件日志，可重放恢复
└── artifacts/
    ├── tests.json      # 交付物、测试结果、变更文件
    ├── checkpoints/    # <point>.json 跨进程回滚点
    └── patches/
```

### 4.2 关键事件

`traces/task.jsonl` 中每行含 `ts` / `event` / `state` / `payload`：

| 事件 | 含义 |
|------|------|
| `action_planned` | 记录本轮动作计划 |
| `action_planning_failed` | 规划器返回空计划 |
| `action_recovery_requested` | 本批动作全失败，要求重新规划 |
| `action_loop_exhausted` | 达到最大重规划步数仍未交付 |
| `first_read` / `first_edit` / `first_test` | 轨迹锚定与阶段推进依据 |
| `modules_loaded` | 本轮实际加载的 J-Space 模块 |
| `verification_completed` | 验证完成（需通过的测试证据） |
| `ship` / `ship_blocked` | 交付成功或被证据门禁阻断 |
| `checkpoint` / `rollback` | 回滚点保存与恢复 |

### 4.3 阶段与可用动作

| 阶段 | 可用动作 |
|------|---------|
| `anchor` | `read`、`search` |
| `explore` | `read`、`search`、`anchor_completed`、`exploration_completed` |
| `implement` | `read`、`search`、`edit`、`write`、`checkpoint`、`rollback`、`implementation_completed` |
| `verify` | `read`、`search`、`run_test`、`inspect_failure`、`checkpoint`、`rollback`、`verification_completed` |
| `ship` | `read`、`search`、`checkpoint`、`rollback`、`ship` |

阶段只能前进，不能后退；`rollback` 事件可恢复到 checkpoint 记录的阶段。

### 4.4 交付门禁

`verification_completed` 与 `ship` 都要求存在结构化通过的测试证据：

```json
{"command": "python -m pytest", "returncode": 0, "ok": true}
```

只有 `ok: true` 或 `returncode: 0` 的结果才被认可。
模型的自然语言声明（如"测试通过"）不构成证据。

跨进程回滚点位于 `.cscd/artifacts/checkpoints/<point>.json`，
进程重启后仍可加载并恢复文件与状态。

---

## 五、Tool / Resource API 参考

### 5.1 Tools（6 个）

| 工具 | 说明 |
|------|------|
| `cscd_reason(question, has_untrusted_input, named_modules, task_id)` | 高层推理网关：一个调用完成复杂度评估→动态轮次→方向Y短路/协议递归→压缩→单原子缓存→认知控制→账本外化，返回精炼结论 |
| `cscd_ledger(task_id, action, payload)` | 运行时状态外化账本：`view`（查看）/`resume`（恢复）/`note`（记录）/`ship`（定稿） |
| `get_cscd_system_prompt()` | 获取四阶协议 System Prompt |
| `validate_cscd_trace(trace)` | 校验轨迹四阶结构（齐全/顺序/非空，容错标签漂移） |
| `extract_cscd_marks(trace)` | 抽取四阶各段内容 |
| `compress_cscd_round(trace, ratio)` | 程序级压缩，返回替代原始全量的 `next_round_context` |

### 5.2 `cscd_reason` 参数详解

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `question` | str | 必填 | 用户问题 |
| `has_untrusted_input` | bool | false | 含不可信输入时强制 introspection，禁用方向Y 短路 |
| `named_modules` | list | null | 显式指定加载的 J-Space 模块名 |
| `task_id` | str | null | 账本 ID；同一 ID 多次调用把状态追加到同一账本，支持 resume |

**返回字段**：

| 字段 | 说明 |
|------|------|
| `reason` | 终端回传精炼结论（替代式，已压缩） |
| `final_context` | 程序级压缩后最终输出 |
| `complexity` / `strategy` / `task_type` | 复杂度 / 推理策略 / 任务类型 |
| `rounds` / `planned_rounds` | 实际轮次 / 计划轮次 |
| `marks_valid` / `missing_marks` | 四阶轨迹是否合规 / 缺失段 |
| `path_taken` / `path_reason` | **本次实际走的路径**（`protocol` / `baseline_shortcut`）及原因 |
| `route` / `route_score` | 动态路由结果（fast/standard/deep）与复杂度评分 |
| `pass_level` / `loaded_modules` / `missing_modules` | J-Space 通行级、**实际**加载到的模块、计划加载但缺失的模块 |
| `cache_hits` / `cache_saved_tokens` | 缓存命中轮数 / 节省 Token |
| `total_completion_tokens` | 累计输出 Token |
| `cognition` | 认知控制审计（workspace/稠密轨/桥接/元认知/锚定） |
| `ledger` | 账本审计（task_id/count/last_ship） |
| `delivery_artifact` / `execution_evidence` | 交付物与执行证据 |

> **先看 `path_taken`，再读 `marks_valid`。**
>
> | `path_taken` | 含义 | `reason` 是什么 | `marks_valid` |
> |-------------|------|----------------|---------------|
> | `protocol` | 执行了四阶递归 | 四阶轨迹 | true 表示结构完整 |
> | `baseline_shortcut` | 任务判为 simple，走基线直答省 Token | **直接答案，无四阶结构** | **false 属正常** |
>
> `baseline_shortcut` 不是故障，也不是「脏数据」——它表示本次**没有**做结构化拆解。
> `path_reason` 会说明触发原因与如何强制走协议：把问题描述得更具体
> （涉及多因素权衡、需区分事实与假设），或传 `has_untrusted_input=true`。
>
> 仅当 `path_taken=protocol` 且 `marks_valid=false` 时才是真异常，
> 此时按 `missing_marks` 排查模型输出。
>
> `missing_modules` 非空表示 J-Space 模块目录不可用（该第三方套件不随本仓库分发）。
> 此时认知控制层退化为仅使用 `cognition` 中的基础规则，不影响四阶协议执行。
> 如需启用，请安装 J-Space 后设置 `CSCD_JSPACE_MODULES_DIR` 指向其 `modules` 目录。

### 5.3 Resources（3 个）

| Resource | 用途 |
|----------|------|
| `cscd://system-prompt` | 协议规范（注入被推理模型） |
| `cscd://agent-guide` | 宿主 Agent 调用引导（何时触发/调用顺序） |
| `cscd://readme` | 协议使用说明与已知边界 |

---

## 六、完整调用示例

### 6.1 一次推理 + 账本续跑
```
# 调用1：执行推理（task_id 固定，便于续跑）
cscd_reason(question="设计带权限的 TODO 后端", task_id="todo-api")

# 调用2：查看该任务的推理账本
cscd_ledger(task_id="todo-api", action="view")

# 调用3：从最后一个 seam/note 恢复上下文
cscd_ledger(task_id="todo-api", action="resume")
```

### 6.2 协议插件形态（细粒度控制，宿主 Agent）
1. `get_cscd_system_prompt()` → 注入 system
2. 发起模型推理，产出四阶轨迹
3. `validate_cscd_trace(trace)` → 校验，失败则重试补全
4. `extract_cscd_marks(trace)` → 抽取各段审计
5. `compress_cscd_round(trace, ratio)` → 压缩，用 `next_round_context` 替代全量

---

## 七、常见问题与排错（FAQ）

| 问题 | 原因与解决 |
|------|-----------|
| `cscd_reason` 报"需要配置模型端点" | 服务进程未读到端点变量。在 MCP 配置 `env` 透传 `LLM_*`/`OPENAI_*`，并重启服务 |
| 调用报 429 RateLimit | 端点 TPM 配额耗尽。`openai_carrier` 已内置指数退避重试（1s/2s/4s），等待配额恢复 |
| `marks_valid=false` | 容错解析已覆盖标签漂移（缺闭合/方括号变体）；若仍失败，说明确实缺失某段，按 `missing_marks` 补全 |
| 修改代码后工具仍报旧行为 | MCP 客户端缓存了 `tools/list`。重启客户端/MCP 服务刷新 |
| `cscd_reason` 返回空 reason | 可能命中缓存但无新结论；或端点返回空（已回退 `reasoning_content`）。可换 `task_id` 重试 |
| Windows GBK 终端打印 ✓✗ 报错 | 运行前设 `PYTHONIOENCODING=utf-8` |

---

## 八、从代码调用（非 MCP，Python）

```python
import os
from carriers.openai_carrier import OpenAICarrier
from core.cscd import CscdEngine, load_config

carrier = OpenAICarrier(
    os.getenv("LLM_MODEL") or "your-model-name",
    os.getenv("LLM_API_URL"), os.getenv("LLM_API_KEY"),
)
engine = CscdEngine(carrier, load_config())
r = engine.run("设计电商积分系统", task_id="points-system")
print(r.reason)        # 精炼结论
print(r.cognition)     # 认知控制审计
print(r.ledger)        # 账本审计
```
