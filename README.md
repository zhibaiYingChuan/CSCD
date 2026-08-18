# C-S-C-D 推理编排协议（产品文档）

> **3 秒快速开始**
>
> - **双击** **`start.bat`**（Windows 用户）→ 自动装依赖 + 引导填端点 + 启动服务 + 打开浏览器
> - **配置模型端点**：`LLM_API_URL` / `LLM_API_KEY` / `LLM_MODEL`（与你的 AI 工具共用同一个 Key）
> - **三种接入方式**：WebUI 看板（`http://127.0.0.1:8000`）｜ REST API（端口 8001）｜ MCP Server（stdio）
> - **一条命令启动**：`python start_services.py --all`
>
> 详细部署见 [DEPLOY.md](DEPLOY.md)，开发者接入见 [DEVELOPER.md](DEVELOPER.md)。

***

> **产品定位**：一套 **System Prompt 级别的结构化推理协议**，可注入任何支持 Function Calling /
> System Prompt 注入的模型调用中，强制模型按四阶标记语言
> （`<DECOMPOSE>`→`<CLASSIFY>`→`<SELECT>`→`<COMBINE>`）输出推理轨迹。
>
> 它不是「已证明有效的优化器」，而是一种**可选的、有明确结构的推理框架模板**——价值在于
> 把「拆解-分类-选择-组合」的人类工程方法论**形式化**为机器可执行、可审计、可插拔的协议，
> 可在任何需要显式结构化推理的场景下被尝试使用。验证数据只是效果说明，不是产品存在的必要条件。

***

## 0. 快速开始

**最简单方式（Windows）：双击** **`start.bat`** 自动完成"装依赖 + 引导填端点 + 启动 + 打开浏览器"。
或可视化部署向导：`http://127.0.0.1:8000/deploy`。

```bash
pip install openai
export OPENAI_BASE_URL="https://你的端点"
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL="你的模型名"        # 必填，不预设默认（deepseek-chat/gpt-4o/claude-...）

# 方式一：直接跑编排器（带协议）
python orchestrator.py --model 你的模型 --task "你的任务"

# 方式二：真实双调用思维链对照（带协议 vs 基线，独立上下文）
python run_ab_call.py  --model 你的模型 --task "你的任务"
```

### 一键启动服务（推荐 · 快速使用）

用户配置好模型端点后，一条命令拉起 WebUI 看板 + REST API，并自动检测已配置的端点：

```bash
python start_services.py            # 检查依赖 + 端点就绪 + 接入指引（推荐先跑）
python start_services.py --all      # 一键启动 WebUI(8000) + REST API(8001)
python start_services.py --webui    # 只启动 WebUI 看板
python start_services.py --api      # 只启动 REST API
```

> 端点自动检测：`LLM_API_URL/LLM_API_KEY`、`OPENAI_BASE_URL/OPENAI_API_KEY`、`DEEPSEEK_API_URL/DEEPSEEK_API_KEY` 任一组已配置即自动采用，无需二次配置（与 AI 工具中已配置的 Key 一致）。
> **模型名不预设默认**：请显式配置 `LLM_MODEL`/`OPENAI_MODEL`（如 `deepseek-chat`/`gpt-4o`/`claude-...`/你的本地模型），避免锁死某一家模型。

协议本体（可直接复制的 System Prompt）见 **`cscd-system-prompt.md`**。

***

## 0.1 集成方式：C-S-C-D MCP Server（推荐 · 面向未来）

将协议封装为 **MCP Server**，任何支持 MCP 的 AI 工具（Continue / Cline / Cursor / Claude Desktop）
以标准化方式读取协议并注入模型调用。**核心集成动作永远是：在模型调用前，把协议作为 System Prompt 注入。**

### 启动 Server

```bash
pip install mcp
python cscd_mcp_server.py        # stdio 传输，MCP 客户端直接拉起
```

### 客户端配置（示例）

复制 `.mcp.example.json` 为项目/客户端的 MCP 配置（Continue 的 `mcp.json`、Cline 的 `cline_mcp_settings.json` 等）：

```json
{
  "mcpServers": {
    "cscd-protocol": {
      "command": "python",
      "args": ["cscd_mcp_server.py"],
      "cwd": "${workspaceFolder}/cscd"
    }
  }
}
```

> **可移植性**：`cwd` 请用 `${workspaceFolder}/cscd` 等相对占位符（MCP 客户端通用变量），或替换为你自己的 CSCD 仓库路径，**不要硬编码本机绝对路径**。
> \| 类型 | 名称 | 说明 |
> \|------|------|------|
> \| Resource | `cscd://system-prompt` | 返回完整协议 System Prompt（客户端读取后注入） |
> \| Resource | `cscd://readme` | 协议使用说明与已知边界 |
> \| Resource | `cscd://agent-guide` | **宿主 Agent 调用引导**：何时调用 CSCD、按什么顺序调用（主动调用的规则） |
> \| Tool | `get_cscd_system_prompt()` | 取协议文本 |
> \| Tool | `validate_cscd_trace(trace)` | 校验模型产出是否满足四阶结构（齐全/顺序/非空） |
> \| Tool | `extract_cscd_marks(trace)` | 抽取四阶各段内容，便于审计/比对 |
> \| Tool | `compress_cscd_round(trace, ratio)` | 对一轮轨迹做程序级压缩，返回替代原始全量的 `next_round_context`（替代式压缩） |
> \| Tool | `cscd_reason(question, ...)` | **推理网关高层入口**：一个调用完成复杂度评估→动态轮次→方向Y短路/协议递归→压缩→缓存，直接返回精炼结论 |

> 客户端职责：连接 Server → 读取 `cscd://system-prompt` → 在每次模型调用的 `messages` 开头插入
> `role:"system"` 消息（内容=协议）→ 将模型产出的推理轨迹回传 `validate_cscd_trace` 做一致性底线校验。
> 这把"协议注入"从手写复制升级为标准化的可发现、可校验服务。
>
> **让其他工具可调用 & 让模型主动调用**：
>
> - **接入**：stdio 配置（上）供本地 IDE 用；改为 `mcp.run(transport="sse")` 即可作为 HTTP 常驻服务，
>   供多个工具 / Web 网关共享（推理网关形态）。
> - **主动调用**：读取 `cscd://agent-guide`（宿主 Agent 规则）判断**何时**触发 CSCD（复杂/高歧义/需审计/
>   含不可信输入时），并按「协议路径 1–5 步」或「`cscd_reason` 短路路径」执行。这份 guide 随 MCP 一起分发，
>   任何接入客户端都能拿到一致的主动调用约定，无需手动复制 prompt。
> - **服务端调用网关（方案 B 强制约束）**：MCP 服务端维护会话状态，**必须先调用** **`cscd_reason`** **完成推理，
>   才能使用** **`validate_cscd_trace`** **/** **`extract_cscd_marks`** **/** **`compress_cscd_round`** 三个消费工具；未推理时返回
>   "请先调用 cscd\_reason" 引导。豁免：`get_cscd_system_prompt`（协议注入前置）、`cscd_ledger`（账本辅助）。
>   这从服务端强制 Agent 把 `cscd_reason` 当作必经入口，而非"调了但忽略输出"。新增开关/状态为进程内会话状态，
>   `cscd_reason` 成功返回即标记解锁。
> - **`cscd_reason`** **前置条件**：服务端需设置 `OPENAI_BASE_URL` / `OPENAI_API_KEY`（可选 `OPENAI_MODEL`）环境变量；
>   未设置时返回清晰引导错误，可回退到协议路径自行调用模型。

***

## 1. 架构与实现

### 1.1 设计定位

C-S-C-D 是**协议层（语义契约）**，与**载体层（执行运行时）解耦，遵循**依赖倒置原则：
理论不依赖任何宿主平台，平台只是协议的适配载体。

| 层级     | 组件                            | 通用性要求                 |
| ------ | ----------------------------- | --------------------- |
| 核心理论引擎 | C-S-C-D 四阶递归协议                | 与平台无关（纯提示词/状态机逻辑）     |
| 认知控制层  | J-Space 七机制（选择性加载、桥接推理等）      | 与平台无关（可注入任何对话式 Agent） |
| 启动优化层  | dsh 两阶段锚定**思想**（首轮极简工具→稳定后解锁） | 抽取思想，不绑定 DSH 实现       |
| 执行环境   | CodeBuddy（实际工作环境）             | 适配层仅对接其 Agent/Tool 接口 |

- 协议层：`protocol.md` 定义四阶标记语言（`<DECOMPOSE>/<CLASSIFY>/<SELECT>/<COMBINE>`）与五层架构。
- 载体层：`carriers/` 下任意实现 `Carrier` 接口的运行时。换模型 = 换一个 Carrier，四阶语义不变。

### 1.2 目录结构（产品三层交付）

```
cscd/
│
├── cscd-system-prompt.md    # 【交付物1】协议本体：可直接复制的 System Prompt 模板
│
├── protocol.md              # 语义契约（载体无关，四阶标记语言 + 五层架构）
├── orchestrator.py          # 入口，走 Carrier 接口（默认 OpenAI 载体）
├── run_ab_call.py           # 【验证入口】真实双调用思维链对照（带协议 vs 基线，独立上下文）
├── run_local.py             # 本地打通：CodeBuddy 离线载体跑全链路
├── run_compare.py           # 简单任务对比（Standard vs C-S-C-D）
├── run_compare_bug.py       # 复杂任务对比（跨模块 Bug 排查）
├── bench_log.py             # Token/延迟基线对比日志
├── bench_results.jsonl      # 实验结果记录
├── core/
│   ├── marks.py             # 四阶标记校验（跨载体一致性底线）
│   ├── classify.py          # L1 任务分类（spec/react/weak）
│   ├── assess.py            # L3 复杂度评估 + 策略/预算
│   └── cscd.py              # 四阶递归主循环（协议层核心）
└── carriers/
    ├── base.py              # Carrier 抽象接口
    ├── openai_carrier.py    # 【交付物2】选项A：任意 OpenAI 兼容模型（支持协议/基线双调用）
    ├── codebuddy_carrier.py # 选项C：本会话载体（含离线样本模式；native 为占位骨架）
    └── samples/             # 预生成四阶推理样本（CodeBuddy 真实产出固化）
```

**三层交付物**

1. **协议本体** → `cscd-system-prompt.md`（复制即用的 System Prompt）
2. **载体适配层** → `carriers/`（OpenAI 兼容 / CodeBuddy，Carrier 接口可扩展）
3. **使用文档** → 本 README（前置条件、安装、用法、已知边界）

### 1.3 核心接口

```python
class Carrier:
    def anchor(self, question: str) -> str:   # L2 启动锚定：首轮极简
    def reason(self, prompt, system, budget) -> str:  # L4 四阶推理
    def validate_marks(self, text: str) -> bool:      # 标记校验
```

协议层 `CscdEngine` 仅依赖 `Carrier` 抽象，不感知具体模型或运行时。

***

## 2. 验证方法（务必先读）

### 2.1 目标验证方法（真实多轮 + API 日志）

按架构修正，验证应脱离离线估算，改为在 CodeBuddy 中运行真实多轮任务，
从 API/监控日志读取精确 Token 消耗：

- **对照设计**：同一道题，先用"默认 Agent（无编排）"跑一遍，再用"注入 C-S-C-D 协议
  （修改 System Prompt + 工具状态机）"跑一遍。
- **记录指标**：总 Token（含输入/输出，从 CodeBuddy 监控面板或 API 日志获取）、
  任务成功率（由架构师判定）、是否需要人工修正（额外轮次）。
- **三类通用测试场景**见第 7 章。

### 2.2 当前过渡态（离线样本 + 字数估算）

> ⚠️ 本节以下数据为**过渡态**，非目标方法。当前 `codebuddy_carrier` 为离线样本模式
> （未接入真实外部 API），Token 按**输出中文字数 × 1.6** 粗估，**未计入输入 Token、未计入多轮修正成本**。

| 项        | 说明                                             |
| -------- | ---------------------------------------------- |
| 运行环境     | 单轮、离线载体（CodeBuddy 会话产出固化为样本），**未接入真实外部 API**   |
| Token 计量 | 按**输出中文字数 × 1.6** 粗估；**未计入输入 Token、未计入多轮修正成本** |
| 质量判定     | 两边最终根因与修复方案一致，视为质量对等                           |
| 结论适用范围   | 仅反映"结构化协议在单轮、强模型、显性线索任务上的开销"，**不代表通用结论**       |

> ⚠️ 本实验**无法证实或证伪**文档第六章"Token 节省 20-40%"的声称。该声称的真实前提
> （避免后续修正对话）在本单轮场景下未被触发，故编排层必然只表现为净开销。
> 一旦接入真实端点（见第 5 章），应改用 2.1 的目标方法重测。

***

## 3. 对比结论（核心章节）

### 3.1 简单任务（模块设计题）

| 指标       | Standard | C-S-C-D | 结果      |
| -------- | -------- | ------- | ------- |
| 估算 Token | 1520     | 2200    | 编排 +45% |
| 延迟（估算）   | 2100ms   | 3800ms  | 编排 +81% |
| 准确率增益    | —        | 0%      | 无       |

### 3.2 常规复杂任务（跨模块偶现 Bug 排查，线索 ≥4 且含噪音）

| 指标       | Standard     | C-S-C-D | 结果       |
| -------- | ------------ | ------- | -------- |
| 输出中文字数   | 261          | 630     | 编排 2.41× |
| 估算 Token | 418          | 1008    | 编排 +141% |
| 中间过程     | 200字（合规≤300） | 完整四阶    | —        |
| 最终根因     | 网关幂等校验+重试缺键  | 同左      | 一致 ✅     |
| 准确率增益    | —            | 0%      | 无        |

### 3.3 综合分析

**在强模型（如 DeepSeek V4 级）上，面对"显性线索充分、迷惑性不强"的任务，
强制显式执行 C-S-C-D 四阶递归只会带来约 2.4 倍的 Token 开销，而准确率增益为 0。**

机理：SOTA 模型在预训练阶段已内化"分类-筛噪-组合"能力，能以**隐式压缩推理**完成，
无需把中间状态显式摊开为文字。强制显式化只是把模型本已做对的推理"抄写"出来，徒增结构开销。

**本次测试未能找到 C-S-C-D 四阶协议产生 Token 节省的任务类型。**
初步假设：结构化编排的收益可能不体现在"单轮正确率"，而仅存在于
**"模型内部置信度极低、需强制回溯"的边界场景**（高迷惑性陷阱 + 低置信度）。

***

## 4. 局限性与未来方向

### 4.1 已承认的局限

- **未测试真实 API 计量**：当前为离线粗估，输入 Token 与多轮修正成本未计入。
- **未测试"模型先犯错再由编排修正"的延迟成本**：这是文档声称收益的真正来源，本实验未覆盖。
- **样本规模极小（2 组）**：仅能给出方向性结论，不足以做统计推断。

### 4.2 推荐架构改造：按需触发器（而非常驻协议）

基于上述结论，更高效的编排形态不是"强制全量跑四阶"，而是 **J-Space 式元认知触发器**：

```
默认路由 ──► Standard 快速直答
                │
                ▼ 触发条件（任一）：
                │   · 输出置信度评分（logprobs）低于阈值
                │   · 工具调用失败 / 矛盾返回
                │   · 用户显式请求深度推理
                ▼
           按需加载 C-S-C-D 四阶协议进行强制回溯
```

该改造使简单任务零开销，复杂/边界任务仍有兜底。本仓库的 `Carrier` 接口与
`core/cscd.py` 已支持此形态——只需在 `orchestrator.py` 增加置信度路由即可，
代码无需废弃。

### 4.3 仍需真实验证的实验

1. 接入 OpenAI 兼容端点，跑同题两遍（Standard + C-S-C-D）得精确 Token/成本。
2. 引入多轮交互场景，测量"Standard 答错→修正"的总成本 vs "C-S-C-D 一次命中"的总成本。
3. 构造高迷惑性陷阱题，验证按需触发器是否在低置信度边界显出收益。

### 4.4 ⚠️ 上游基准数据的可复现性声明

本项目整合了以下上游插件，但对其公开的基准测试数据，需明确以下客观事实：

1. **dsh-anchored-standard**：其 README 底部载明，早期报告的 Project2 得分（98、99、99）系基于旧版 Minimal 系统提示词获得，且当前版本下**未被独立复现**。第三方多环境测试显示其实际能力稳定在 **85-90** 区间（详见上游 issue #65/#51）。本项目未对这些历史高分进行重新验证，故不将其作为编排效果的预期目标。
2. **J-Space Cognition Suite V3.6**：项目方报告了在 HLE、NL2Repo 等基准上的显著提升（如 +7.7），但该数据来自特定环境下的单次运行，未提供多轮平均或置信区间。**本项目在离线单轮场景下亦未复现其"Token 节省"声称**（详见本报告第 3 章对比数据）。

**结论**：本编排器的价值不应直接等同于上游插件的公开跑分。所有数据以本工程独立运行的实测结果为准。

### 4.5 阶段B：程序级混合方案（已实现）

前述章节讨论的是「协议层」编排效果。混合方案（递归内嵌压缩）的完整收益——从源头节省 Token、递归状态级联复用、KV Cache 友好——**仅靠注入 System Prompt 无法兑现**，必须在程序侧强制实现。本仓库已在「协议层验证成功」基础上落地阶段B：

| 组件   | 文件                                | 职责                                                                                                                            |
| :--- | :-------------------------------- | :---------------------------------------------------------------------------------------------------------------------------- |
| 压缩器  | `core/compressor.py`              | `compress_summary(text, ratio)` 确定性抽取四阶 summary，无 summary 时按 ratio 截断；返回 `next_round_context`                                 |
| 主循环  | `core/cscd.py` `CscdEngine.run()` | 多轮四阶推理，每轮 COMBINE 后程序级压缩；**最终回传** **`reason=final_context`（替代式），全量轨迹仅留** **`raw_reason`** **供审计**；按 `config.yaml` 动态调压缩比；支持早停 |
| 配置   | `config.yaml`                     | `compress_ratios`（round\_1/2/3…）、`max_rounds`、`budget_per_round`、`early_stop_on_stable` 等                                     |
| 验证入口 | `run_ab_call.py` `--with-stageB`  | 路径D：四路径对照，输出 `stageB_gen_ratio_vs_A`（累计生成/基线A）、`stageB_final_vs_B_ratio`（最终回传/路径B全量）、`stageB_net_save_rate_vs_A`（净节省率）        |

**关键修正（2026-08-17）：压缩必须「替代」而非「追加」**

此前实现存在结构性缺陷：`CscdEngine.run()` 每轮生成完整四阶轨迹，程序压缩只把摘要塞进"下一轮输入前缀"，而 `reason` 仍回传最后一轮**全量**——导致压缩是"在生成完成后追加摘要"，并未削减已生成的 Token。实测表现为：有 CSCD 的总生成量约为无 CSCD 基线的 **2 倍**（31,000 → 62,000+ Token），压缩机制未生效。

本轮修复：

1. **协议层（修正1）**：`cscd-system-prompt.md` 明确「压缩是替代而非追加」——四阶内部只保留关键结论点，最终结论用 `<<<summary>>>` 包裹，**禁止"全量四阶 + 末尾摘要"双重输出**。
2. **程序层（修正2）**：`CscdEngine.run()` 最终回传 `final_context`（程序级压缩后的摘要，**替代**最后一轮全量）；全量轨迹保留于 `raw_reason` 仅供审计。
3. **诚实计量（修正3）**：`run_ab_call.py` 路径D 新增 `stageB_gen_ratio_vs_A` / `stageB_net_save_rate_vs_A`，直接对比**累计生成量**与无协议基线，揭示多轮递归的真实代价，不再用"最终摘要/B"误导。

**路径D 实测核心结论（真实端点** **`deepseek-v4-flash`** **@ tokenrhythm，2026-08-18，修复后真实数据）**：

| 指标                                 | 值          | 说明                                |
| :--------------------------------- | :--------- | :-------------------------------- |
| 路径A 基线 completion                  | 1203 Token | 无协议常规方案                           |
| 路径D 累计生成 `total_completion_tokens` | 2900 Token | 3 轮递归实际生成总量                       |
| 路径D 最终回传 `final_summary_tokens`    | 143 Token  | 终端收到的压缩摘要（`final_context`，替代式）    |
| `stageB_gen_ratio_vs_A`            | 1.42       | 累计生成是基线的 1.42 倍（多轮递归代价）           |
| `stageB_final_vs_B_ratio`          | 0.13       | 最终回传仅约为路径B全量的 13%（**终端输出削减 87%**） |
| `stageB_net_save_rate_vs_A`        | **-0.416** | 累计生成比基线**多 41.6%**（净成本上升，非节省）     |

- `marks_valid=true`，三处 `truncate` 程序级压缩正常，`raw_reason` 938 Token 仅留审计。
- **诚实解读**：① "替代式压缩"修复生效——终端回传 Token 从路径B全量（约 1100）降至 143，削减 87%；② 但**多轮递归（`max_rounds=3`）使累计生成量高于基线 42%**，这是递归的固有代价，协议层/程序层压缩无法消除"生成过程本身"的消耗；③ 旧 `stageB_save_rate≈0.942` 确属分母造假，真实净指标为 `-0.416`。
- **使净成本转负的手段**：在 `config.yaml` 将简单任务的 `max_rounds` 降为 1（不递归），或仅对复杂度高的任务启用多轮递归。此时 `final_vs_B` 的 87% 削减将直接体现为净节省。

**编排级输出缓存（P1 任务内复用 + H1 硬短路，2026-08-18 已实现）**

前述"替代式压缩"削减的是**终端回传**，多轮递归的**累计生成**仍高于基线。根本原因是：每轮都重新让模型生成完整的四阶轨迹，而上一轮已产出的 `CLASSIFY`/`COMBINE` 结论本可被后续轮直接复用——这正是**编排层（而非 API 层 KV Cache）的输出缓存**。

本仓库在 `CscdEngine.run()` 的递归循环内新增 `RoundCache` 管理层：

| 组件           | 位置                                             | 职责                                                                                          |
| ------------ | ---------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `RoundCache` | `core/cscd.py`                                 | 每轮 `carrier.reason()` 后用 `marks.parse_marks()` 抽取四阶切片，以 `DECOMPOSE` 原子指纹为 key 存入；下一轮开始前先查缓存 |
| 探针来源         | `run()` 的 `last_decompose`                     | 用**上一轮完整轨迹**的 DECOMPOSE 段（非压缩摘要，后者已丢失原子列表）作指纹，确保命中                                          |
| H1 硬短路       | `run()` 循环                                     | 命中且 `need_review` 为空 → 直接复用缓存的 `CLASSIFY`/`COMBINE`，**完全跳过** **`carrier.reason()`**         |
| H2 兜底        | `run()` 循环                                     | 未命中或 `need_review` 非空 → 回退轻量模型调用（置信度校准）                                                     |
| 计量           | `CscdResult.cache_hits` / `cache_saved_tokens` | 命中轮次计数与估算避免的 Token（含 prompt+completion 历史均值 `DEFAULT_SAVED_PER_HIT`）                        |

**与 API 级 KV Cache 的区别**：本机制不触碰宿主推理引擎的 KV 缓存，纯粹在编排层把模型已生成的结论结构化存下、按原子复用。它降的是**调用次数**（省一次 `reason()` 即省一轮完整生成），而非单次请求的 prompt/completion 拆分。

**单原子级复用（2026-08-18 修订）**：真实递归中 DECOMPOSE 原子逐轮演进，整轮指纹匹配命中率趋近 0。改为按单个原子存储结论 `atom -> (classify_line, combine_line, need_review)`，下一轮对每个原子先查单原子缓存：全部命中且无需回溯 → 整轮硬短路；部分命中 → 命中结论拼成强上下文注入 prompt，模型仅补全未命中原子（H2 轻量化）。`_align()` 用原子首词关键词把 CLASSIFY/COMBINE 行归属到原子。

**单元验证（`_verify_cache.py`，假 Carrier，零真实 Token）**：complex 任务 `planned_rounds=3` 时，carrier 调用 **2 次**（第 3 轮原子与第 1 轮完全一致 → H1 硬短路命中 1 次），`cache_hits=1`，估算节省 2400 Token，真实 `total_completion_tokens` 从 900 降至 600。单原子级短路在任务内场景真实生效。

**真实端点验证（tokenrhythm / deepseek-v4-flash，2026-08-18）**：同一 complex 电商积分系统任务，`planned_rounds=3`：

- `cache_hits: 1`，`cache_saved_tokens: 6000`（命中原子数 × 1200 估算均值）
- `stageB_gen_ratio_vs_A: 1.57`（较整轮级缓存前的 3.26 降近半——缓存减少了真实生成）
- `stageB_final_vs_B_ratio: 0.30`（终端回传仅为路径B全量 30%，替代式压缩生效）
- `stageB_net_save_rate_vs_A: -0.5723`（净增 57%，较整轮级缓存前的 -2.26 大幅改善）
- `summaries[2]` 已出现 `[缓存·积分获取模块...]` 注入上下文，证明 H2 轻量化注入工作正常

**待校准**：`DEFAULT_SAVED_PER_HIT=1200` 为估算均值，待用真实 `prompt_tokens+completion_tokens` 替换；P2 跨任务持久（`store` 替换为文件/数据库后端）已预留接口，核心逻辑不变。

**多维度审计修复（2026-08-18）**：经全项目审计并修复以下三处：

1. **H1 硬短路轨迹缺失 SELECT 段**（功能缺陷）——硬短路构造的等价轨迹只有 `DECOMPOSE/CLASSIFY/COMBINE`，缺 `SELECT`，导致 `validate_marks` 误报 `missing=[SELECT]`、`marks_valid=False`、审计字段失真。已补齐 SELECT 段（用命中原子的 classify 结论作为事实池筛选结果），构造轨迹四阶完整，`marks_valid=True`。
2. **方向Y 短路前仍调用 anchor()**（性能浪费）——simple 任务短路走基线前先执行了 `carrier.anchor()`，浪费一次模型调用。已将 `anchor()` 调用移到 Y 短路判定之后（仅协议路径需要锚定），短路路径 `anchor=""`，省一次模型调用。
3. **预算来源分裂**（设计不一致）——`run()` 固定用 `budget_per_round`(2048)，与 `assess.py` 的复杂度档位（simple=512/medium=2048/complex=8192）不一致。已统一为按复杂度取 `budget_for(complexity)`，`config.yaml` 显式配置仍可覆盖（向后兼容）。

**code review 修复（2026-08-18，经 cscd MCP + LRC 记忆）**：
4\. **H1 硬短路轮污染** **`prev_summary`** **→ 终端回传混入** **`[缓存·]`** **调试前缀**（质量缺陷）——硬短路轮构造的等价轨迹含 `[缓存·]` 拼接文本，其 `compress_summary()` 结果被赋给 `prev_summary`，最终成为 `final_context` 回传终端。已修复：仅 H2/模型轮更新 `prev_summary`，硬短路轮保留上一轮精炼摘要。修复后终端回传恢复为精炼结论（如 `积分系统采用双表结构`），硬短路轮的审计轨迹仍留存于 `summaries` 供审计。回归验证：`_verify_cache.py`（cache\_hits=1、marks\_valid=True）、`_verify_y.py`（Y 短路正常）、H1 极端场景探针（raw\_reason/final\_context 均非空且精炼）全部通过。

**推理时认知控制层（2026-08-18，J-Space/dsh 机制补全）**：

此前 CSCD 只实现「**编排层控制**」（四阶任务拆解/分类/选择/组合），缺失 J-Space 的「**推理时认知控制层**」与 dsh 的「**首轮轨迹锚定**」——即模型在生成每个 Token 时，如何被动态约束"能激活什么信息 / 如何记录推理状态 / 如何响应置信度 / 首轮看到什么"。新增 `core/cognition.py` 并接入 `CscdEngine.run()`：

| 机制                       | 来源                      | 落地方式                                                  |
| :----------------------- | :---------------------- | :---------------------------------------------------- |
| 工作空间状态管理（≤5 项激活）         | J-Space capacity        | 每轮从 DECOMPOSE 原子取前 `WORKSPACE_LIMIT` 项，注入 system      |
| 稠密轨符号系统（`✓/?/✗/≈`）       | J-Space shorthand       | 要求模型用符号记录推理状态，`_extract_cognition` 确定性解析              |
| 桥接推理检查点                  | J-Space deep-reasoning  | COMBINE 前强制输出"已激活中间概念"，解析入 `bridged_concepts`         |
| 元认知动作选择（信任/重试/独立路径/经验验证） | J-Space self-monitoring | 每轮结束强制选择动作，解析入 `metacognition`                        |
| 首轮轨迹锚定（工具白名单 + 晋升）       | dsh                     | `TrajectoryAnchoring`：首轮仅 `read/search`，持久输出后晋升解锁完整工具 |

- 新增开关：`config.yaml` 的 `cognitive_control`（总开关）与 `trajectory_anchoring`（dsh 锚定）。
- 审计字段：`CscdResult.cognition`（workspace/稠密轨/桥接/元认知/anchored/anchor\_round/tool\_whitelist），已透传到 MCP `cscd_reason` 与 WebUI `/api/reason`。
- 单元验证（假载体）：认知指令注入 system ✅、首轮白名单 `['read','search']` 晋升解锁完整工具 ✅、解析出 `workspace/dense_track='✓?≈'/bridged=['双表结构','账期批次']/metacognition='信任'` ✅；既有 `_verify_cache.py`（cache\_hits=1）、`_verify_y.py`（方向Y）无回归；MCP `cscd_reason` 缺配置引导正常。

**运行时状态外化账本（P4，2026-08-18，MCP 可用性增强）**：

J-Space 最后一个缺口——把推理过程中的认知控制状态、四阶轨迹、审计字段**外化到磁盘账本**，实现跨调用/跨会话的持久化与恢复（对应 J-Space `seam/note/ship/resume` 子命令）。新增 `core/ledger.py`：

| 能力       | 说明                                                               |
| :------- | :--------------------------------------------------------------- |
| `note`   | 记录每轮认知状态 + 轨迹摘要（`round_idx`/`cognition`/`marks_valid`/`summary`） |
| `seam`   | 记录接缝点——此处可中断，之后可从 `resume` 恢复续跑                                  |
| `ship`   | 定稿交付物（精炼结论），标记任务完成                                               |
| `resume` | 从最后一个 note/seam 恢复上下文                                            |

- **账本目录**：`.cscd/ledger/{task_id}.jsonl`（追加式，不重写历史），可用 `CSCD_LEDGER_DIR` 环境变量覆盖。
- **接入** **`CscdEngine.run()`**：`run(..., task_id=..., persist_ledger=True)`；每轮 `dump_round` 外化认知状态 + `seam` 标记接缝，结束 `ship` 交付物；`CscdResult.ledger` 返回审计（task\_id/count/last\_ship）。directionY 短路分支也记录 note+ship。
- **MCP 新增** **`cscd_ledger`** **工具**（view/resume/note/ship），`cscd_reason` 新增 `task_id` 参数支持续跑同一账本；`tools/list` 现返回 **6 个工具**。
- **WebUI**：`/api/reason` 透传 `ledger` 字段。
- 验证：账本 note/seam/ship/resume 全通过；run() 集成（假载体）ledger count=8、last\_ship 正常、resume 恢复 seam ✅；既有缓存/方向Y 无回归；MCP 服务 `tools/list` 6 工具、`cscd_ledger` 真实调用返回 `{count:0, entries:[]}` ✅。

**真实端到端可用性验证 + 修复（2026-08-18，模型 deepseek-v4-flash @ token.sensenova.cn）**：

用本机 `LLM_API_URL/LLM_API_KEY/LLM_MODEL` 真实端点发起完整推理，验证并修复两个真实问题：

1. **`marks.py`** **容错解析（真实模型标签漂移）**——真实模型输出可能只写开标签缺闭合（`<DECOMPOSE>...` 无 `</DECOMPOSE>`），或方括号变体（`[原子列表]`/`[可执行结论]`），导致 `validate_marks` 误判四段全缺、`marks_valid=false`。修复：`MARKS` 正则改为「优先闭合对 + 回退到下一标签/结尾」，`parse_marks` 兼容方括号别名（`[原子列表]`/`[分类]`/`[选择]`/`[可执行结论]`）。修复后完整四阶轨迹 `marks_valid=true`。
2. **`openai_carrier.py`** **推理模型空响应/限流处理**——①推理模型（deepseek）可能 `content` 为空（内容在 `reasoning_content`），导致链路拿到空文本；修复为 content 空时回退 `reasoning_content`，且空响应纳入重试。②对 429/连接错误加**指数退避重试**（1s/2s/4s，最多 3 次），提升真实端到端可用性。

**真实端到端实测（complex 电商积分任务）**：`marks_valid=true`、`missing=[]`、完整 `raw_reason` 四阶全闭合 + 元认知动作"信任"；认知控制层真实生效（workspace 5 原子 / 稠密轨 `✓≈` / 桥接 `['积分余额汇总','积分变动明细','积分有效期过期清理','一致性保证']` / 元认知 `重试` / dsh 锚定 `anchor_round=2`）；`cache_hits=1`；`reason` 为替代式精炼结论；账本 count=8 含 ship。通过 MCP 服务 `cscd_reason` 真实调用返回 `"SQL 是一种用于管理关系数据库的标准编程语言..."`（simple 任务）。

**端点说明**：本机真实端点变量是 `LLM_API_URL`/`LLM_API_KEY`/`LLM_MODEL`（非 OPENAI\_*）；`_make_engine()`/`CscdService`* *已支持 LLM\_*（优先）与 OPENAI\_\* 两套变量。MCP 客户端如需通过服务调用 `cscd_reason`，须在 MCP 配置 `env` 中透传 LLM\_\* 变量（见 `.mcp.example.json`）。

**路径C（文本压缩版）状态**：协议层格式铁律已写入 `run_ab_call.py` 路径C 压缩提示词（保留 `<DECOMPOSE>` 原样尖括号、禁 `[阶段名]: COMBINE` 变体），但**待环境依赖恢复后实测验证**（当前因 `openai`/`pydantic` 依赖冲突暂缓重跑）。路径D 程序级已实现"替代式"压缩且标记零漂移，故路径C 验证不阻塞整体结论。

**诚实边界（与阶段A一致）**：

- 阶段B 在程序侧实现了「**替代式**级联压缩 + 递归上下文复用」，这是确定性的、不依赖模型自律。
- 但 **KV Cache 前缀构建、显存占用下降、递归深度翻倍** 仍属推理引擎/框架运行时能力；本仓库通过「压缩摘要作为下一轮输入前缀」在协议/程序接口层面逼近，不声称直接操控宿主 KV Cache。
- `final_context` 削减的是**终端回传 Token**；**累计生成 Token** 因多轮递归仍可能高于基线，需按任务复杂度权衡 `max_rounds`。相关指标以重跑 `run_ab_call.py --with-stageB` 为准。

***

## 5. 如何使用

```bash
# 本地打通（无需 API）：用 CodeBuddy 离线样本跑全链路
python run_local.py

# 简单任务对比
python run_compare.py

# 复杂任务对比
python run_compare_bug.py

# 接入真实 OpenAI 兼容模型（设置环境变量后）
export OPENAI_BASE_URL="https://api.deepseek.com"
export OPENAI_API_KEY="sk-..."
python orchestrator.py --model deepseek-chat --task "你的问题"
```

### 通过 MCP 的 `cscd_reason` 一次拿结论（推理网关形态）

```bash
# 服务端配置模型端点（供 cscd_reason 内部驱动 CscdEngine.run()）
export OPENAI_BASE_URL="https://api.deepseek.com"
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL="deepseek-chat"      # 可选，默认 deepseek-chat

# 本地 stdio 模式（供 IDE 工具）：
python cscd_mcp_server.py

# 服务化（供多个工具/网关共享）：将 cscd_mcp_server.py 末尾改为
#   mcp.run(transport="sse")   # 或 "streamable-http"
# 即可用 URL 接入，任何 MCP-over-HTTP 客户端可调用 cscd_reason。
```

调用示例（任意 MCP 客户端）：`cscd_reason("设计带权限的 TODO 后端 API")` →
返回 `{reason, final_context, complexity, strategy, rounds, marks_valid, cache_hits, ...}`，
`reason` 即最终精炼结论。simple 任务自动走方向Y 短路（基线直答），medium/complex 走协议+缓存。

### 网页端（Phase 1 · 部署配置面板 + 效果展示看板）

> **网页端 = 部署指南 + 效果看板，不是在线试用工具。** 用户打开网页后无需输入任何内容、无需配置 API Key，
> 只做两件事：**① 复制配置完成部署**（MCP 配置 JSON / 环境变量 / 启动命令，一键复制）+ **② 查看真实效果数据**
> （Token 节省率、缓存命中率、精准度对比、推理轨迹示例——均为真实端点 `deepseek-v4-flash` 实测预设数据）。

位置：`webui/`（FastAPI 静态托管 + 纯 HTML/CSS/JS 前端）。

```bash
# 本地运行
cd cscd/webui/backend
uvicorn main:app --host 127.0.0.1 --port 8000
# 打开 http://127.0.0.1:8000
```

页面：部署配置区（MCP JSON / 环境变量 / 启动命令三标签一键复制）→ 效果看板（指标卡 + 缓存命中率进度条 + 精准度对比表 + 可展开四阶轨迹示例）→ 深/浅主题。数据源：`ab_call_results.jsonl`（路径D vs 基线A）、`defect_probe_results.jsonl`（缺陷排查精准度）。部署方式：本地 / 局域网（`--host 0.0.0.0`）/ 公网（反向代理加 HTTPS）。详见 `webui/README.md`。

### 开发者文档（Phase 2）

**[DEVELOPER.md](DEVELOPER.md)** —— 开发者接入完整指南：MCP 配置（Continue/Cline/Claude Desktop）、`cscd_reason` 参数与返回字段详解、6 工具 + 3 资源 API 参考、完整调用示例、FAQ 排错指南、Python 代码调用示例。

### VS Code 扩展（Phase 3）

`vscode/` —— VS Code 扩展骨架（`cscd-reasoning`），提供两个命令：

- **`C-S-C-D: 运行推理`**：通过 WebUI 后端 `/api/reason` 执行推理，在输出面板展示精炼结论、认知控制审计（工作空间/稠密轨/桥接/元认知/锚定）、账本信息与完整四阶轨迹。
- **`C-S-C-D: 打开效果看板`**：浏览器打开部署配置面板 + 效果展示看板。

扩展通过 HTTP 调用 WebUI 后端（复用同一 `CscdEngine`），无需额外 MCP 客户端依赖。安装/配置见 `vscode/README.md`。验证：命令注册、激活、结构化结果渲染均通过。

### REST API + Python SDK（Phase 4 · 规模化）

面向第三方 / Agent / 多租户的规模化接口，复用同一 `CscdEngine`：

- **`api_server.py`**（独立 REST API，端口 8001）：`GET /health`、`POST /v1/reason`（执行推理）、`GET /v1/usage`（用量统计）、`GET /v1/usage/all`（管理员）。
  - **API Key 鉴权（自动发现）**：请求头 `X-API-Key` 须在白名单内。白名单**自动扫描**用户已配置的模型 Key（`CSCD_API_KEYS` / `LLM_API_KEY` / `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` / `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY`）——集成到 AI 工具时用户已配置过端点，无需二次配置。未配置任何 Key 则不鉴权（内网模式）。
  - **用量统计/计费审计**：每次调用落盘 `.cscd/usage.jsonl`（api\_key/token/轮次/缓存命中/复杂度）。
  - 服务化部署：`CSCD_API_PORT` 指定端口，可配 systemd/Docker/反向代理。
- **`sdk/`（Python SDK）**：`CSCDClient(base_url, api_key)`，提供 `reason()` / `health()` / `usage()` / `usage_all()`，仅标准库 urllib，零第三方依赖。

```python
from sdk import CSCDClient
client = CSCDClient("http://127.0.0.1:8001", api_key="your-key")
r = client.reason("设计带权限的 TODO 后端 API")
print(r["reason"], r["cognition"], r["ledger"])
print(client.usage())
```

启动：`export LLM_API_URL/LLM_API_KEY/LLM_MODEL`（可选 `CSCD_API_KEYS`），`python api_server.py`。
验证：鉴权（401/200）、真实推理（reason/ledger/cognition）、用量累计（calls≥1）、SDK 端到端全部通过。

***

## 6. 工程调优记录

### 6.1 L1 分类规则的中文适配修正

**问题**：原 `classify_task()` 规则 `len(question) < 15 -> react` 基于英文/Token 启发式，
对中文极不友好。中文信息密度高、字符数远小于等效英文，导致短计划任务
（如「实现模块设计」仅 6 字）被错误踢进 `react` 快通道，**不加载任何认知模块**，
直接违背"spec 应走 full/loop 加载四阶/J-Space 模块"的设计初衷。

**修正**（不触碰 J-Space / dsh 原始代码，仅在编排器入口加固）：
将硬编码长度阈值替换为 **意图关键词命中 + 长度兜底** 的组合规则——

1. 计划性意图词命中（设计/计划/架构/实现/规划/spec/模块/流程/方案…）→ 强制 `spec`，无论多短；
2. 中文 >20 字不直接下结论，交 `weak` 由模型二次评估（至少不误判 react）；
3. 仅极简短指令（编译/重启等）走 `react`。

**修正前后对比验证**（离线，对典型中文任务分类）：

| 任务                 | 旧规则     | 新规则    | 结论             |
| ------------------ | ------- | ------ | -------------- |
| 实现模块设计（6字）         | react ❌ | spec ✅ | 核心偏差修复         |
| 设计用户登录API          | react ❌ | spec ✅ | 核心偏差修复         |
| 规划数据迁移流程           | react ❌ | spec ✅ | 核心偏差修复         |
| 微服务订单Bug排查…（长）     | spec    | spec   | 一致（长题本就不误判）    |
| 编译代码 / 重启服务        | react   | react  | 极简指令未被误伤       |
| 帮我看下这个函数为什么报错（13字） | react   | react  | 无意图词，合理走 react |

**说明**：修正仅改变**路由判定**，不改变四阶协议本身。即便正确进入 `spec`，
在强模型 + 显性线索任务上四阶仍可能表现为净 Token 开销（见第 3 章），
但至少证明路由机制对中文计划任务不再失效。

***

## 7. 验证场景（离线仿真方法演进记录 · 不构成产品效果承诺）

> ### ⚠️ 已知边界（诚实声明）
>
> 第 7、8 章为**早期离线仿真**的方法演进记录，**不构成产品的效果承诺**，原因如下：
>
> 1. 离线仿真无法发起真正独立的模型调用，比较的是「两种输出风格」而非「两种执行路径的思维链」，
>    属方法学反例（详见架构核验结论）。
> 2. 本系统作为**产品**的价值不在"已证明节省 Token"，而在结构化、可审计、可插拔的推理框架。
> 3. 真正验证协议是否影响「直接模型调用的思维链」，需用 `run_ab_call.py` 接入真实端点做独立双调用对照——
>    该验证在本环境尚**未完成规模化执行**，故产品不宣称任何性能结论。
>    下方数据仅作历史追溯，最终可信入口见 `run_ab_call.py` 与 `cscd-system-prompt.md`。

> 不再依赖 DSH 的 Project2 基准。改为在 **CodeBuddy 当前会话的内置模型**中直接执行三类通用测试场景
> （选项B确认：内置模型即足以验证，无需任何外部 API 端点或 key）。
> 每类场景用"默认 Agent（无编排）"与"注入 C-S-C-D 协议"对照，记录 Token 与质量指标。
> Token 计量：CodeBuddy 响应元数据不暴露计数。计量走 `carriers/codebuddy_carrier._count_tokens()`，
> 优先用 `tiktoken(cl100k_base)` 精确分词；tiktoken 不可用时降级为字符/1.6 近似。
> 当前环境已通过国内 PyPI 镜像（清华 tuna）成功安装 `tiktoken 0.13.0` + `regex 2026.7.19`，
> 故下表数据均为 **tiktoken 精确计量**（非字符/1.6 估算）。
> 注：中文 token 数约为字符数的 1.6–2.5 倍，故精确计量下的绝对值显著高于早期估算，
> 但**相对倍率趋势与早期估算一致**（编排恒为净开销，模糊场景倍率最高）。

| 场景         | 任务类型                                | 为何适合验证编排                                             | 状态          |
| ---------- | ----------------------------------- | ---------------------------------------------------- | ----------- |
| **长文档修订**  | 给定 5000 字技术文档，要求按 5 条冲突的评审意见修改      | 测试"工作集过载"和"表征漂移"是否被缓解（对应 J-Space 选择性加载 + 广播枢纽）       | ✅ 已验证（内置模型） |
| **多工具调研**  | 要求顺序调用 3 个工具（网页搜索 → 读取文件 → 对比数据）并汇总 | 测试"无控制重试"和"过早完成"是否被抑制（对应 dsh 锚定 + 启动后解锁扩展工具）         | ✅ 已验证（内置模型） |
| **模糊需求澄清** | 需求描述含歧义和矛盾点，要求先澄清再设计方案              | 测试"分类筛噪"和"桥接推理"是否提升准确率（对应 C-S-C-D 四阶 + J-Space 桥接推理） | ✅ 已验证（内置模型） |

### 7.1 场景设计要点

- **验证模式术语澄清**：本第 7 章所用方法为 **「离线仿真验证」**——
  由本会话内置模型对固化任务真实产出两段文本（Standard / C-S-C-D），再离线计量其 Token 与比对质量，
  **并非「在线实时推理验证」（即在 Agent 运行时由协议实时驱动多轮交互、并读取运行时 API 计数）**。
  两者的 Token 倍率数据等效（文本长度为真实产出），但离线仿真**无法体现实时多轮交互的耗时与推理变异性**，
  故其生态效度低于在线实时验证。如需切换到在线实时推理验证，需接入第 5 章真实端点并改用运行时计数。
- **长文档修订**：冲突评审意见需触发 `broadcast`（同一约束一改全改）与 `capacity`（仅登台必要段落），
  对照默认 Agent 是否出现"改了 A 忘了 B"的表征漂移。
- **多工具调研**：编排侧在首轮仅暴露核心工具（锚定思想），首个工具调用后解锁扩展工具；
  对照默认 Agent 是否出现工具调用失控或未完成全部 3 步即宣告完成。
- **模糊需求澄清**：编排侧强制 `<CLASSIFY>` 先分离事实/假设/噪音，再做 `<SELECT>`；
  对照默认 Agent 是否直接基于歧义假设产出错误方案。

### 7.2 长文档修订 · 实测单场景对比（CodeBuddy 内置模型真实执行）

执行脚本：`verify_long_doc_revision_real.py`。
**本会话内置模型真实产出**两段文本（约 600 字草稿 + 5 条冲突评审意见），非 `samples/` 离线样本。
任务：团队周报系统草稿（PG 单表 240 万行 / 本地盘附件 / LIKE 搜索 >3s / 手动部署），
5 条意见（对象存储 / ES / 读写分离 / 异步导出 / 容器化），冲突在(2)(3)数据链路与(1)(5)过渡期。

| 指标                 | Standard（无编排）         | C-S-C-D（四阶编排）                   | 结果           |
| ------------------ | --------------------- | ------------------------------- | ------------ |
| 输入 Token（含 System） | 569                   | 665                             | 协议注入 +96     |
| 输出 Token           | 438                   | 680                             | 编排 1.55×     |
| 总 Token            | 1007                  | 1345                            | **编排 1.34×** |
| 覆盖 5 条意见           | 完整                    | 完整                              | 一致 ✅         |
| 冲突处理               | 串行先(1)后(5) + PG 写入口统一 | broadcast 声明 PG 唯一写源 + 先(1)后(5) | 一致 ✅         |
| 准确率增益              | —                     | 0%                              | 无            |

**质量差异（可见）**：两路径单次任务准确率对等；差异在**可追溯性/可维护性**——
C-S-C-D 显式分离事实/假设/噪音并 `broadcast` 声明"同步链路唯一性"，若后续追加第 6 条评审，
四阶结构更易增量修订；Standard 为散文式，增量修改需重读全文。本次未触发"工作集过载/表征漂移"。

**结论**：在"长文档修订 + 冲突评审"任务上，内置模型本身已能正确识别并解决约束冲突，
强制四阶编排未提升单次准确率，仅表现为约 1.34× 的 Token 开销（低于第 3 章 Bug 题 2.41×，
因本场景任务更长、四阶标记占比更小）。这与第 3 章核心结论一致——**强模型在显性线索充分任务上，
显式四阶只增开销无收益**。编排的潜在收益（增量可维护性、低置信度边界防错）需更复杂场景验证。

### 7.3 多工具调研 · 实测单场景对比（CodeBuddy 内置模型真实执行）

执行脚本：`verify_multi_tool_research_real.py`。
**本会话内置模型真实产出**两段文本（三步调研任务：搜索→读本地文件→交叉对比），非 `samples/` 离线样本。

| 指标                 | Standard（无编排） | C-S-C-D（四阶编排）               | 结果           |
| ------------------ | ------------- | --------------------------- | ------------ |
| 输入 Token（含 System） | 265           | 377                         | 协议注入 +112    |
| 输出 Token           | 414           | 521                         | 编排 1.26×     |
| 总 Token            | 679           | 898                         | **编排 1.32×** |
| 三步全部完成             | 是             | 是                           | 一致 ✅         |
| 过早完成               | 否             | 否（broadcast 闸门：前置未完成不给最终建议） | 一致 ✅         |
| 准确率增益              | —             | 0%                          | 无            |

**质量差异（可见）**：两路径均完成三步且未过早完成；差异在**约束显式性**——
C-S-C-D 将"未读内部笔记前不得给建议"提升为 `broadcast` 闸门，后续若模型倾向跳步，四阶结构更易审计跳步点；
Standard 仅靠散文自律。本次未触发"无控制重试/过早完成"问题（内置模型本身守序）。

### 7.4 模糊需求澄清 · 实测单场景对比（CodeBuddy 内置模型真实执行）

执行脚本：`verify_ambiguous_clarify_real.py`。
**本会话内置模型真实产出**两段文本（含歧义与矛盾需求的智能客服系统），非 `samples/` 离线样本。

| 指标                 | Standard（无编排）        | C-S-C-D（四阶编排）            | 结果           |
| ------------------ | -------------------- | ------------------------ | ------------ |
| 输入 Token（含 System） | 301                  | 401                      | 协议注入 +100    |
| 输出 Token           | 205                  | 590                      | 编排 2.88×     |
| 总 Token            | 506                  | 991                      | **编排 1.96×** |
| 先澄清后方案             | 否（先给方案，末尾补"数值未确认"）   | 是（CLASSIFY 显式隔离事实/假设/噪音） | C-S-C-D 优 ✅  |
| 假设泄漏风险             | 高（首响<2s/95% 直接采用未确认） | 低（四项量化单列，不锁架构）           | C-S-C-D 优 ✅  |
| 准确率增益              | —                    | 防错收益（降低基于歧义产错方案）         | 有（结构性）       |

**质量差异（可见）**：本场景是三类中最显出编排价值的一处——Standard 先给方案、末尾才补说明
（假设泄漏，若未确认数值偏差大会产出错误方案）；C-S-C-D 在 `<CLASSIFY>` 显式隔离"事实 vs 待澄清假设"，
方案前先抛澄清清单（首响阈值/准确率/方言种类/月预算），降低基于歧义假设锁死架构的风险。
这是第 3 章"准确率增益 0%"结论的**重要边界修正**：在模糊/矛盾需求下，编排的结构性防错收益可见。

### 7.5 三类场景汇总对比（CodeBuddy 内置模型真实执行）

| 场景     | Standard 总 Token | C-S-C-D 总 Token | 编排倍率       | 准确率增益 | 编排可见收益       |
| ------ | ---------------- | --------------- | ---------- | ----- | ------------ |
| 长文档修订  | 1007             | 1345            | 1.34×      | 0%    | 增量可维护性（追溯性）  |
| 多工具调研  | 679              | 898             | 1.32×      | 0%    | 约束显式性（跳步审计）  |
| 模糊需求澄清 | 506              | 991             | 1.96×      | 结构性防错 | 假设隔离（先澄清后方案） |
| **均值** | —                | —               | **≈1.54×** | —     | —            |

**核心发现（编排的结构性防错收益）**：
模糊需求澄清场景证明——在低置信度/高歧义任务上，C-S-C-D 的 `<CLASSIFY>` 显式隔离「事实 vs 待澄清假设」、
方案前先抛澄清清单，能**结构性降低基于歧义假设锁死错误架构的风险**（Standard 首响即直接采用未确认数值，
假设泄漏）。这是本项目最有价值的发现，将第 3 章"准确率增益 0%"从"普适结论"修正为"显性线索充分场景下的结论"，
确立了编排收益的**真实适用边界**：强模型 + 显性线索充分 ⇒ 仅净开销；低置信度/高歧义 ⇒ 结构性防错增益。
该发现已从「边界说明」提升为「核心发现」。

**总体结论（三类场景真实执行后）**：

1. **Token 开销**：强制四阶在所有场景均表现为净开销（1.32×–1.96×，均值约 1.54×），
   与第 3 章"强模型显性线索任务上显式四阶只增开销"一致；模糊需求场景倍率最高（因澄清结构占比大）。
2. **准确率增益**：在长文档修订、多工具调研（显性线索充分）上为 0%；但在**模糊需求澄清**上，
   编排通过假设隔离产生**结构性防错收益**——这是第 3 章未覆盖的边界，证明编排收益确实存在于
   "低置信度/高歧义"场景（与第 3 章 3.3 的初步假设吻合）。
3. **验证完成声明**：第 7 章三类场景已在 CodeBuddy 内置模型真实执行完毕（非离线样本），
   协议有效性得到可量化、可审计的支撑；计量采用 **tiktoken(cl100k\_base) 精确分词**（已安装可用），
   相对倍率趋势与早期字符/1.6 估算一致。

### 7.6 执行优先级与剩余项

- 已落地：`codebuddy_carrier.py` 新增 `native=True` 本会话原生执行模式；
  `run_verify_native.py` 提供三类场景构造与计量框架；三类场景均已真实跑通（见表 7.2–7.5）。
- 计量诚实性：若后续接入真实端点（第 5 章环境变量），可将 `measure()` 替换为 API 返回的真实计数；
  当前经 `tiktoken(cl100k_base)` 精确分词（已通过国内镜像安装），中文 token 约为字符数 1.6–2.5 倍，
  绝对值高于早期字符/1.6 估算，但相对倍率趋势一致。
- 「超级玛丽网页版」补充场景：按架构师建议暂未纳入；若后续追加，作为 7.7 额外验证场景单独设计
  （需明确其测试维度与无协议/有协议对比方法）。

***

## 8. 路径对比实验（离线仿真方法演进记录 · 同属已知边界）

> 本章为早期「离线仿真」方法演进记录，与第 7 章同属 ⚠️ 已知边界声明范畴：
> 其对照仍发生在 agent 自演层，**未真正发起独立模型调用**，故不构成产品效果承诺。
> 真正验证入口见 `run_ab_call.py`。

### 8.0 方法学纠错：文本对比 ≠ 路径对比

第 7 章原三类场景存在**根本性混淆**：比较的是「两种输出风格的 Token 差异」（同一人用直答风 vs 四阶风写两段话），
而非「两种执行路径的 Token 差异」（模型在有无协议约束下**实时生成**的区别）。预设文本无法模拟协议对推理行为的实际影响。

**修正后的实验设计原则**（架构师转发指令）：

1. **唯一变量** = 是否注入 C-S-C-D System Prompt；任务指令两路径**逐字一致**。
2. **独立会话**：两路径分属独立文件（`pathA_standard.py` / `pathB_cscd.py`），互不 import，消除上下文污染。
3. **模型实时生成**：产出由内置模型在受控/非受控下实时产出，非预设风格模板。
4. **旧数据作废**：第 7 章「离线文本风格对比」数据不再作为最终验证依据，仅留存供方法演进追溯。

### 8.1 实验任务（两路径一致）

> 设计带权限控制的 TODO 应用后端 API：用户注册/登录（JWT）、TODO CRUD、共享空间（owner/editor/viewer 三级角色）、删除权仅 owner、含数据模型+接口清单+鉴权中间件伪代码。

### 8.2 路径对比实测（CodeBuddy 内置模型实时生成，tiktoken 精确计量）

| 指标                 | 路径A（无协议）           | 路径B（有协议/C-S-C-D）                   | 结果           |
| ------------------ | ------------------ | ---------------------------------- | ------------ |
| 输入 Token（含 System） | 252                | 484                                | 协议注入 +232    |
| 输出 Token           | 486                | 737                                | 编排 1.52×     |
| **总 Token**        | **738**            | **1221**                           | **编排 1.65×** |
| 需求覆盖（5 条）          | 完整                 | 完整                                 | 一致 ✅         |
| 权限边界清晰度            | 中（viewer 创建权仅一句带过） | 高（CLASSIFY 隔离事实/假设/噪音，role 枚举单列）   | B 优          |
| 冲突一致性              | 删除权文字说明，未统一声明      | `broadcast` 统一删除权唯一来源，所有 DELETE 一致 | B 优          |
| 可追溯性               | 散文式，权限散落           | 四阶集中，决策点定位快                        | B 优          |

### 8.3 结论（真正的路径对比）

1. **Token 开销**：受协议约束实时生成，编排仍表现为 **1.65× 净开销**（输入+232 来自协议注入，输出+251 来自四阶结构），
   与第 3 章「强模型显性线索任务上强制四阶只增开销」一致。
2. **质量增益**：本次单次任务两路径方案完整性对等（准确率增益≈0%），但 B 在
   **权限边界显式性、冲突一致性（broadcast）、可追溯性**三个维度有结构性优势——
   这与第 7 章「核心发现」（低置信度/高歧义场景编排有结构性防错收益）方向吻合，
   本任务属「中等复杂、权限冲突明确」场景，已能观测到一致性审计收益。
3. **方法论收敛**：第 7 章离线文本风格对比**作废**；本章路径对比为当前可信的最终验证依据。
   若后续接真实端点（第 5 章），可将 `_count_tokens` 替换为运行时 API 计数，进一步逼近在线实时推理验证。

***

*本文档刻意保留"未达标"的原始数据，因为准确圈定理论的适用边界，
比证明理论有效更具工程价值。*
