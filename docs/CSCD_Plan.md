# CSCD 持续推进与边界文档

## 目的

这份文档用于长期跟踪 CSCD 的推进方向，明确哪些能力已经落地，哪些仍处于过渡期，以及后续每一步应如何收敛。它的作用不是做一次性的方案说明，而是作为后续推进的统一参照，避免实现再次偏向 XML 输出或单次文本推理。

## 当前定位

CSCD 当前定位为结构化推理验证系统，而不是运行时控制系统或模型能力增强器。它通过 DECOMPOSE、CLASSIFY、SELECT、COMBINE 将复杂问题转为可验证、可追溯、可审计的推理框架。

RuntimeState、Harness、反馈修订、工作空间和动作计划是支撑验证记录的实现机制。它们可以约束外部工作流、保存证据和定位失败，但不改变模型内部推理，也不保证结论正确。

当前最重要的工作不是继续宣称控制模型，而是围绕科研推理验证收敛输出格式、证据边界、引用溯源和可复核结论。

## 已实现

### 1. XML 兼容层

- 四阶标记解析和校验仍然存在。
- XML 已经从主协议降级为兼容层。
- 它保留审计价值，但不应再主导流程设计。

### 2. RuntimeState

- 已实现运行时状态模型。
- 支持目标、完成条件、事实、验证结果、开放问题、下一步动作、变更文件、测试命令、测试结果、回滚点、阶段等字段。
- 支持事件驱动的阶段推进和恢复。

### 3. Harness 动作执行

- 已实现动作解析和执行。
- 支持 `read`、`search`、`edit`、`write`、`run_test`、`inspect_failure`、`checkpoint`、`rollback`、`ship`。
- 动作结果会回写到状态和工作空间。

### 4. 工作空间持久化

- 已落地 `.cscd/workspace/`、`.cscd/traces/`、`.cscd/artifacts/`。
- 任务状态、执行痕迹、测试结果和回滚点都会持久化。

### 5. MCP 服务

- 已有 `cscd_reason` 和 gate 机制。
- 外部工具访问可以被推理状态门控。

### 6. 原子缓存

- 已支持已知结论复用。
- 可减少重复生成。

### 7. 程序级压缩

- 已支持替代式压缩。
- 终端输出和审计轨迹分离。

## 过渡中

### 1. 主循环 `run()`

- 目前已经支持动作计划优先。
- 但主循环仍保留四阶标记路径和兼容逻辑。
- 还没有完全切换成 Harness 单一路径。

### 2. 动作计划优先

- 已具备 JSON 动作计划解析能力。
- 真实模型输出仍可能混入四阶标记或自然语言。
- 需要进一步提高动作计划输出稳定性。

### 3. 轨迹锚定

- 目标是让锚定由真实 `read/search` 事件驱动。
- 当前仍需要继续检查是否存在提前写入或隐式晋升。

### 4. 认知模块加载

- J-Space 模块注册和门控已经存在。
- 但模块内容在主流程中的加载和注入仍需继续收敛。

### 5. SHIP 验证

- 已有验证门控。
- 但还需要持续确保它完全依赖真实测试证据，而不是只依赖模型声明。

## 后续推进原则

1. 主循环优先

- 后续改动优先围绕 `CscdEngine.run()` 的主流程收敛。
- 新能力必须服务于主闭环，而不是另起旁路。

2. 动作优先

- 模型输出应优先收敛为动作计划。
- 四阶标记只保留为兼容和审计。

3. 证据优先

- 交付判断必须依赖状态和执行证据。
- 口头声明不作为完成依据。

4. 阶段优先

- 每个阶段只暴露该阶段需要的能力。
- 不提前解锁，也不提前晋升。

5. 文档优先

- 所有关键推进必须先更新这份文档。
- 文档是持续跟进的唯一参照，不再靠口头记忆推进。

## 动作跟进记录

### 记录格式

每次推进都补一条记录，内容必须包含：

- 日期
- 目标
- 修改点
- 证据
- 是否进入下一阶段

### 记录示例

- 2026-08-19：将 XML 从主协议降级为兼容层，动作计划优先解析已接入，验证测试通过。
- 2026-08-19：补齐 `ship` 的验证门控测试，要求验证事件与测试结果共同存在。
- 2026-08-19：主循环默认关闭 `legacy_marks_fallback`，非动作文本只作为观察，不再进入 XML 主路径；兼容旧样本时显式开启该开关。

## P3 当前目标

P3 的目标是把“动作计划优先”稳定成默认路径，并持续削弱四阶标记对主流程的影响。

### P3 要做的事

1. 进一步稳定模型输出协议

- 让模型更稳定地产出 JSON 动作计划。
- 减少混合四阶标记文本对主流程的干扰。

2. 继续削弱 `parse_marks`

- 只保留旧样本兼容。
- 不再让它影响主执行路径。

3. 统一动作证据

- 所有动作的结果统一写入工作空间。
- 让 `changed_files`、`test_commands`、`test_results`、`rollback_points` 的来源一致。

4. 固化验证门槛

- `verification_completed` 必须依赖真实测试结果。
- `ship` 必须在验证完成后才能通过。

## 下一阶段：产品完善路线

### 阶段 A：Harness 独占动作闭环

状态：进行中（第一项已完成）

交付物：

- 动作计划为空时记录 `action_planning_failed` 并触发受限重规划。
- 动作失败时自动进入 `inspect_failure` 或回滚策略。
- 只有 `ship` 成功或明确 `ship_blocked` 时结束循环。
- `run()` 与 `Harness.run_loop()` 使用一致的阶段和证据规则。

验收标准：

- 规划失败不会被当作任务完成。
- 动作失败不会静默结束。
- 重规划次数有上限并持久化。
- 失败、恢复、回滚事件可从 trace 重放。

### 阶段 B：阶段化认知模块调度

状态：阶段契约与缺失条件已完成，继续做端到端验收

交付物：

- 每轮根据 `RuntimeState.phase` 重新选择模块。
- 模块正文随当前阶段注入上下文。
- trace 记录实际加载模块和模块版本/路径。
- 阶段变化后下一轮使用新模块集合。

验收标准：

- ANCHOR、EXPLORE、IMPLEMENT、VERIFY、SHIP 的模块集合可测试。
- 未加载模块正文不会进入模型上下文。
- 模块缺失时有明确审计结果，不伪造加载成功。

### 阶段 C：恢复、回滚与交付闭环

状态：核心闭环、跨进程回滚和 ship 阻断恢复验收已完成

交付物：

- checkpoint 与 `changed_files` 建立稳定关联。
- 测试失败进入 `inspect_failure`。
- 回滚后恢复到正确阶段和下一步动作。
- 交付前输出剩余风险和未解决问题。

验收标准：

- 任一失败动作可定位到对应 trace。
- rollback 后文件和状态一致。
- 无通过测试证据不能 ship。
- ship 结果可从事件日志重建。

### 阶段 D：产品化验收

状态：核心验收已完成，真实模型端到端验收待配置环境

交付物：

- MCP、REST、WebUI、SDK 入口行为一致。
- 配置、日志、错误信息和恢复策略统一。
- 建立端到端回归集和发布前检查。
- 形成真实能力与边界报告。

验收标准：

- 核心路径全量测试通过。
- 无敏感信息硬编码。
- 真实模型不可用时有明确降级行为。
- 所有已实现能力与文档状态一致。

## 本阶段动作记录

- 2026-08-19：建立产品完善路线，阶段 A-D 明确交付物和验收标准。
- 2026-08-19：阶段 A 完成失败重规划骨架；空计划和全失败批次均持久化失败证据，并在 max_steps 内继续重规划；新增 2 项回归测试，23 项测试通过。
- 2026-08-19：阶段 B 完成按 phase 动态选择模块、正文加载和 `modules_loaded` trace；阶段白名单优先于 loop 默认模块；新增阶段差异测试，24 项测试通过。
- 2026-08-19：阶段 C 完成 checkpoint 状态快照和 rollback 状态恢复；implement/verify 阶段开放回滚；新增状态一致性测试；全量 43 passed，3 个子测试通过。
- 2026-08-19：阶段 C 补齐跨进程回滚：checkpoint 持久化状态与文件字节，重建 Harness 后仍可恢复；MCP/REST/WebUI/SDK 入口核查确认共享 CscdService/CscdEngine 门面；全量 44 passed，3 个子测试通过。
- 2026-08-19：阶段 B 完成五个 runtime phase 的模块契约与缺失正文审计；阶段 C 完成跨进程 `ship_blocked → test evidence → verification_completed → ship` 验收；全量 47 passed，3 个子测试通过。
- 2026-08-19：阶段 D 完成 MCP/REST/WebUI 运行时证据字段一致性，新增入口契约测试；新增 `docs/CSCD_Product_Guide.md`，全量 49 passed、1 warning、3 个子测试通过。真实模型端到端仍需有效环境配置。
- 2026-08-19：全局代码审查四项问题全部修复：阻断交付不再写 ledger.ship、失败测试不再触发 run() ship、replay 正确恢复 rollback phase/状态、run_test 禁止 shell 组合命令并使用 shell=False；新增回归测试，全量 52 passed、1 warning、3 个子测试通过。

## 边界

- 这套系统的目标是运行时控制，不是通用自治代理。
- 它适合长任务、分阶段执行、证据化交付。
- 它不负责取代完整 IDE，也不负责承诺所有任务一次完成。
- XML 只是一层兼容，不是未来的主方向。

## DeepSWE 实验记录

### 2026-08-20：CSCD-only 15 任务运行

状态：环境烟雾测试完成，benchmark 成绩无效。

配置：

- 模型：`deepseek-v4-flash`
- 端点：`https://token.sensenova.cn/v1`
- 模式：CSCD-only，无对照组
- 任务数：15
- 结果文件：`tests/benchmarks/deepswe_results/deepswe_cscd_only_20260820_020303.json`

结果：

- 请求完成：15/15
- 请求错误：0
- `ship_blocked`：15/15
- `run_test`：0
- `verification_completed`：0
- `ship`：0

偏差判定：

- 当前 runner 未接入 Pier/Harbor 任务沙箱。
- `pier`、`uv`、`harbor` 本地不可用；仅检测到 Docker。
- 所有任务实际搜索的是 CSCD 当前仓库，而不是各自 DeepSWE 目标仓库。
- 因此本次结果只能证明 API 调用、状态外化和交付阻断逻辑可运行，不能证明代码任务完成率或 DeepSWE pass rate。

下一次实验硬门禁：

1. 每个任务必须有独立 sandbox root。
2. sandbox root 必须包含目标仓库代码。
3. `runtime_root` 必须指向该任务 sandbox。
4. 必须执行任务 verifier/test.sh。
5. 结果必须同时记录模型动作、改动文件、测试结果和 verifier pass/fail。
6. 未满足以上条件时，实验脚本必须在发起模型调用前阻断。
7. runner 必须强制要求 `--sandbox-root`，并逐任务检查目标工作目录和 verifier。

当前实现：

- `tests/benchmarks/run_deepswe_cscd.py` 已增加 `--sandbox-root` 强制参数。
- 缺少 sandbox、目标任务目录或 `tests/test.sh` 时返回门禁错误码，不创建模型载体、不发起模型请求。
- 每个任务的 `runtime_root/runtime_dir` 绑定到独立 sandbox 子目录。
- `tests/test_deepswe_experiment_gate.py` 已覆盖门禁阻断、目标仓库标志、task.toml/verifier 和无密钥 preflight 报告。
- runner 支持 `--check-only --preflight-report <path>`，只检查环境并生成机器可读报告，不创建模型载体。
- 当前本地仍未准备真实任务沙箱，因此禁止启动 DeepSWE benchmark。
- 2026-08-20 下一步 preflight：Docker daemon 未运行，`deepswe-sandboxes` 不存在，check-only 以错误码 3 阻断；报告为 `tests/benchmarks/deepswe_results/preflight-20260820.json`，未发起模型请求。
- 2026-08-20：已启动 Docker Desktop，daemon 版本 29.6.2 响应；本地未发现 DeepSWE 任务镜像，`deepswe-sandboxes` 仍不存在；preflight 继续以错误码 3 阻断，报告为 `tests/benchmarks/deepswe_results/preflight-20260820-docker-ready.json`，未发起模型请求。
- 2026-08-20：已完成依赖审计（15 个镜像、12 个仓库、4 种语言），15 个镜像已全部拉取（总大小约 50GB）；`deepswe-sandboxes` 根目录已创建，但缺少目标仓库 clone；preflight 按门禁正确阻断，未发起模型请求。
- 2026-08-20：15 个目标仓库已全部克隆到沙箱，preflight check-only 通过（`ready: true`）；沙箱基础已就绪，可启动真实 CSCD-only 实验。
- 2026-08-20：真实 CSCD-only 15 任务实验完成（`deepswe_cscd_only_20260820_033158.json`）：

| 指标 | 值 |
|------|------|
| 任务完成 | 15/15 |
| 任务错误 | 0 |
| 总耗时 | 841.5s (约 14 分钟) |
| 平均耗时 | 56s/任务 |
| read | 21 |
| search | 51 |
| edit | 0 |
| write | 0 |
| run_test | 0 |
| ship_blocked | 15 |
| ship | 0 |

结论：沙箱基础设施（Docker 镜像、目标仓库、runtime_root 绑定、preflight 门禁）全部正常工作，模型能正确搜索目标仓库。但 deepseek-v4-flash 在当前 CSCD 配置下未进入 edit/write/run_test 阶段，因此全部 ship_blocked。这不是沙箱或门禁失败，而是模型动作链未完整执行。

## 结语

后续所有推进都应遵循同一条路径：先更新这份文档，再按文档推进实现，最后用测试和持久证据确认结果。推进目标应围绕结构化推理验证：更清晰的证据分类、更完整的引用溯源、更可复核的验证设计和更稳定的审计输出，避免再次把外部工作流控制误称为模型内部推理控制。

历史文档中的“运行时控制”仅表示外部工作流、动作和状态的编排能力，不表示控制模型内部推理。对外定位统一以“结构化推理验证系统”为准。