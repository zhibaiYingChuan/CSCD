# C-S-C-D 通用推理编排协议

> **定位：模型/载体无关的编排语义层，不是某个工具的私有协议。**
> C-S-C-D 描述"该怎么拆解、分类、选择、组合"，是一层协议契约；
> 底层执行载体可以是 DSH、crewAI、CodeBuddy，或任意 OpenAI 兼容模型——
> 它们都只是"跑这套语义的运行时"，可任意替换。
>
> 本文件是五层架构 + 四阶递归的"契约"，所有执行载体都遵守同一套标记语言
> （`<DECOMPOSE>` / `<CLASSIFY>` / `<SELECT>` / `<COMBINE>`），从而可跨载体复现。

## 一、四阶递归（核心循环）

每一轮推理严格按以下顺序执行，并显式输出结构化标记：

1. **拆解 Decompose**：将当前问题递归拆至不可分原子，输出 `<DECOMPOSE>` 列表。
2. **分类 Classify**：将每个原子归入 `事实 / 假设 / 噪音` 三类，输出 `<CLASSIFY>`。
3. **选择 Select**：仅从"事实"池选取权重最高的 3 个原子进入操作，输出 `<SELECT>`。
4. **组合 Combine**：将操作结果与"假设"池碰撞，生成新事实；若产生新子目标，递归回步骤 1，输出 `<COMBINE>`。

循环终止条件：无新子目标 且 当前轮已产出可执行结论。

## 二、五层架构（模型无关映射）

| 层 | 职责 | 本系统实现 |
|----|------|-----------|
| L1 任务分类路由 | 识别 spec / react / weak | `classify_task()` 规则 + Prompt |
| L2 启动锚定 | 首轮极简工具集，确认后放开 | 首轮仅允许"思考/输出"，二次确认后放开全部工具 |
| L3 推理策略 | 复杂度评估后选 AoT/GoT/Hybrid/FaR | `assess_complexity()` + 模式切换 |
| L4 认知控制 | 工作空间/桥接/元认知/失效恢复 | C-S-C-D 四阶循环 + 置信度早停 |
| L5 多Agent协作 | 角色分解子任务并汇总 | 单进程内按角色分发 + 汇总验证 |

## 三、任务分类定义

- **spec**：复杂、需先计划再执行（走完整五层 + 完整四阶）。
- **react**：简单、直接执行（跳过 L3 重策略，轻量四阶）。
- **weak**：模糊、模型自路由（先做一次澄清或最小假设再分类）。

## 四、Token 预算（自适应复杂度）

| 复杂度 | 推理预算上限 | 策略 |
|--------|-------------|------|
| simple | 512 | react 轻量 |
| medium | 2048 | AoT |
| complex | 8192 | GoT / Hybrid |

超出预算触发确定性早停：基于置信度信号（如连续两轮结论一致）提前终止。

## 五、验收标准

| 指标 | 基线(Standard) | 目标(C-S-C-D) | 验证 |
|------|----------------|---------------|------|
| 输出Token | 100% | ≤80% | Token日志 |
| 总Token | 100% | ≤85% | Token日志 |
| 端到端延迟 | 100% | ≤150% | 计时 |
| 成本 | 100% | ≤20% | API账单 |

## 六、启动锚定协议（L2 · 校准自 dsh-anchored-standard 真实机制）

> 校准来源: xiaobright/dsh-anchored-standard（README 原始内容）。
> 真实核心不是"简单剥离上下文"，而是 **context-gate 屏蔽自动注入 + 工具 schema 锚定 + 持久事件驱动 Promotion**。

### 6.1 两阶段（Bootstrap / Promotion）

- **Bootstrap（引导阶段 · Request #1）**：
  - `tool-bootstrap`：**仅暴露 Minimal 真实工具对** `[bash, str_replace_editor]`（不解锁发现/检索/执行外工具）。
  - `context-gate`：**在统一注入路径屏蔽所有自动注入**（AGENTS.md 摘要、skill 目录提醒等），首轮零注入。
  - 可选 `bootstrapMaxTokens` 输出预算上限（默认不启；issue #11 验证 1024 cap 也可锚定）。
- **Promotion（晋升）**：由首个**持久事件**触发 —— 首次持久 `tool/call` **或** `assistant/message`（二者先到为准）。
  阶段状态由持久事件推导，故 resume/reload 可保留（非内存标记）。
- **Resident catalog（常驻目录 · Request #2+）**：引导对 + 发现工具（`dev_tool_search`/`skill_search`/`skill_load`）+ 模型显式解锁工具；恢复标准注入。

### 6.2 三个首请求杠杆（issue #11，决定性递减）

1. **工具 schema（决定性）**：真实 Minimal 对锚定 5/5；标准族 schema 全落标准风 11/11。
2. **输出预算**：首请求 1024 cap 也可锚定（26/32）；基础模式默认不启。
3. **注入提醒**：有 skill 目录时锚定 0/9 失效 → 故用 `context-gate` 在统一路径屏蔽。

### 6.3 本系统落地语义

- `Carrier.anchor()` 实现 Bootstrap：首轮零注入 + 仅锚定工具对。
- `Carrier` 维护 `promotion_state`（持久事件推导，resume 安全）；首次持久动作后进入常驻阶段。
- 目的：降低首轮噪声，提升事实锚定准确率（与 dsh 实测锚定效应一致）。
