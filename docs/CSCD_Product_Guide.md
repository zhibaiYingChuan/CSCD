# CSCD 产品使用与验收指南

## 产品定位

CSCD 是一个结构化推理验证系统，面向需要检查论证依据、区分证据边界并保留审计轨迹的复杂问题。

它的主场景是科研推理验证，也适用于技术评审、方案论证和合规审计。RuntimeState、Harness 和测试证据是实现可追溯验证的技术基础，不代表 CSCD 能够控制模型内部推理。

它适合：

- 拆解科研假设和文献综述问题
- 区分事实、待验证假设、合理解释和噪音
- 识别关键验证路径和阻塞点
- 形成分层结论与实验设计草稿
- 保留推理依据、验证反馈和审计轨迹
- 对需要读取、修改、测试和回滚的工程问题进行过程记录

它不承诺：

- 改变模型内部推理或提升底层模型能力
- 消除幻觉或自动保证结论正确
- 替代论文、数据、真实实验或专业审查
- 仅通过模型文本声明完成验证或交付

## 最小运行方式

### 环境变量

```text
LLM_API_URL 或 OPENAI_BASE_URL
LLM_API_KEY 或 OPENAI_API_KEY
LLM_MODEL 或 OPENAI_MODEL
```

模型端点必须兼容 OpenAI Chat Completions 接口。

### MCP

```text
python cscd_mcp_server.py
```

核心调用顺序：

```text
cscd_reason
→ 获取结构化结论、运行时状态和执行证据
→ 必要时读取 cscd://agent-guide
```

### REST

```text
python api_server.py
```

```http
POST /v1/reason
Content-Type: application/json
X-API-Key: <配置的 API Key>

{"question":"检查并测试一个代码修改任务","task_id":"demo"}
```

### Python SDK

```python
from sdk import CSCDClient

client = CSCDClient("http://127.0.0.1:8001", api_key="your-key")
result = client.reason("检查并测试一个代码修改任务")
print(result["reason"])
print(result["execution_evidence"])
```

## 运行时工作空间

每个任务会在 `.cscd/` 下产生持久化数据：

```text
.cscd/
├── workspace/
│   ├── goal.md
│   ├── verified.md
│   ├── open.md
│   └── next.md
├── traces/
│   └── task.jsonl
└── artifacts/
    ├── tests.json
    ├── checkpoints/
    └── patches/
```

关键证据包括：

- `action_planned`
- `action_planning_failed`
- `action_recovery_requested`
- `first_read`
- `first_edit`
- `first_test`
- `verification_completed`
- `ship_blocked`
- `ship`
- `rollback`
- `modules_loaded`

## 阶段与动作

| 阶段 | 主要动作 |
|---|---|
| `anchor` | `read`、`search` |
| `explore` | 读取、搜索、锚定完成、探索完成 |
| `implement` | 读取、搜索、编辑、写入、checkpoint、rollback |
| `verify` | 读取、搜索、运行测试、检查失败、checkpoint、rollback |
| `ship` | checkpoint、rollback、交付 |

## 交付规则

`verification_completed` 和 `ship` 都需要结构化通过测试证据：

```json
{"command":"python -m pytest","returncode":0,"ok":true}
```

只有存在 `ok: true` 或 `returncode: 0` 的测试结果，程序才允许验证完成和交付。

## 恢复规则

### 同进程回滚

checkpoint 保存文件和 RuntimeState 快照；rollback 恢复文件、phase、next_action、测试状态和其他运行字段。

### 跨进程回滚

checkpoint 存储在：

```text
.cscd/artifacts/checkpoints/<point>.json
```

重建 Harness 后仍可加载并恢复 checkpoint。

### 失败重规划

- 空动作计划记录 `action_planning_failed`
- 全部动作失败记录 `action_recovery_requested`
- planner 会在最大步数内继续重规划
- 达到上限记录 `action_loop_exhausted`

## XML 兼容边界

XML 四阶标记仍可被解析，但默认不是主路径。

默认配置：

```yaml
prefer_action_plan: true
legacy_marks_fallback: false
```

只有需要兼容旧样本时才显式开启：

```yaml
legacy_marks_fallback: true
```

## 故障排查

### 没有执行动作

检查模型是否返回 JSON 动作计划：

```json
{"actions":[{"action":"read","path":"src/app.py"}]}
```

然后检查 `.cscd/traces/task.jsonl` 中是否有：

- `action_planned`
- `action_planning_failed`
- `action_recovery_requested`

### 无法 verification_completed

检查 `test_results` 是否存在结构化通过证据。仅有“测试通过”的自然语言不会被接受。

### 无法 ship

检查：

1. 是否执行过 `run_test`
2. 测试结果是否包含 `ok: true` 或 `returncode: 0`
3. 是否成功执行 `verification_completed`
4. 当前 phase 是否允许 `ship`

### 模块没有加载

检查：

1. 当前 phase
2. `modules_loaded` trace
3. 模块文件是否存在
4. `CSCD_JSPACE_MODULES_DIR` 是否指向正确目录

缺失模块不会被伪造为已加载。

## 验收命令

```text
python -m pytest tests/ -q
python -m compileall -q core
git diff --check
```

真实模型端到端验收需要配置有效模型端点；没有模型配置时，系统应返回明确的配置缺失或服务不可用信息，而不是静默成功。
