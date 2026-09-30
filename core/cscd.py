"""
C-S-C-D 四阶递归主循环（协议层核心，载体无关）
=============================================
本模块不调用任何模型，只负责：装配 Prompt、驱动 Carrier 执行、
校验四阶标记、并按协议决定是否递归（产生新子目标时回到 DECOMPOSE）。
"""

from dataclasses import dataclass, field
from typing import Optional
from types import SimpleNamespace
import json
import re
import sys
import yaml
from pathlib import Path

from core.classify import classify_task, TaskType
from core.assess import (assess_complexity, select_strategy, budget_for,
                         pass_level_for, select_route, score_task_complexity, Complexity)
from core.marks import validate_marks, parse_marks
from core.jspace_modules import select_modules, load_selected_modules, load_phase_modules, modules_context
from core.harness import Harness
from core.compressor import compress_summary
from core.cognition import (
    CognitionState, TrajectoryAnchoring, build_cognition_system,
    WORKSPACE_LIMIT,
)
from core.runtime_state import RuntimeState, RuntimeWorkspace
from core.routing import Router

PERSONA = """你是一个遵循 C-S-C-D（分类-选择-组合-拆解）四阶递归理论的推理系统。
在每一轮推理中，你必须严格按以下顺序输出结构化标记：
1. <DECOMPOSE> 将问题递归拆至不可分原子（列表）
2. <CLASSIFY> 将每个原子归入 事实/假设/噪音 三类
3. <SELECT> 仅从事实池选取权重最高的3个原子
4. <COMBINE> 将操作结果与假设池碰撞，生成新事实；若有新子目标则递归
循环终止：无新子目标且已产出可执行结论。
若置信度足够（连续两轮结论一致），可提前终止（确定性早停）。"""

TASK_RULES = """任务分类标准:
- spec: 复杂、需先计划再执行 -> 走完整五层+完整四阶
- react: 简单、直接执行 -> 轻量四阶，跳过重策略
- weak: 模糊、模型自路由 -> 先最小澄清/假设再分类"""

# 配置加载（config.yaml 不存在时回退内置默认）
# 查找顺序：包内（安装态，由 pyproject 的 data-files 分发到 core/）→ 项目根（开发态）。
# 这样 pip/uvx 安装后仍能读到随包分发的配置，而不是静默退回下面的内置默认。
_PKG_CONFIG = Path(__file__).parent / "config.yaml"
_PROJECT_CONFIG = Path(__file__).parent.parent / "config.yaml"
_CONFIG_PATH = _PKG_CONFIG if _PKG_CONFIG.exists() else _PROJECT_CONFIG

# 内置默认：仅在 config.yaml 完全缺失时兜底，故必须与 config.yaml 的关键项保持一致。
# prefer_action_plan 默认 False 是刻意的：四阶协议模式才是 CSCD 主业，
# 动作执行模式只服务于代码工程闭环。若此处为 True，一旦配置文件丢失，
# 四阶协议将不被执行且 marks_valid 退化为恒 True 的伪造值。
_DEFAULT_CONFIG = {
    "compress_ratios": {"round_1": 0.6, "round_2": 0.5, "round_3": 0.4, "round_default": 0.4},
    "max_rounds": 3,
    "rounds_by_complexity": {"simple": 1, "medium": 2, "complex": 3},
    "budget_per_round": 2048,
    "temperature": 0.3,
    "early_stop_on_stable": True,
    "simple_shortcut_to_baseline": True,
    "marks_blocking": False,
    "prefer_action_plan": False,
    "legacy_marks_fallback": False,
}


def load_config() -> dict:
    if _CONFIG_PATH.exists():
        try:
            with _CONFIG_PATH.open(encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            # 合并默认，避免缺键
            merged = dict(_DEFAULT_CONFIG)
            for k, v in cfg.items():
                if isinstance(v, dict) and isinstance(merged.get(k), dict):
                    merged[k].update(v)
                else:
                    merged[k] = v
            return merged
        except Exception:
            return dict(_DEFAULT_CONFIG)
    return dict(_DEFAULT_CONFIG)


def _count_tokens(text: str) -> int:
    """轻量 Token 估算（字符/4），用于 final_summary_tokens 计量，避免硬依赖 tiktoken。"""
    if not text:
        return 0
    return max(1, len(text) // 4)


def _extract_delivery_artifact(text: str) -> dict:
    """从模型输出提取交付物，不让摘要覆盖代码和测试证据。"""
    if not text:
        return {}
    code_blocks = re.findall(r"```(?:[A-Za-z0-9_+-]+)?\n(.*?)```", text, re.DOTALL)
    changed_files = []
    for match in re.findall(r"(?:修改文件|文件变更|changed files?)\s*[:：]\s*(.+)", text, re.IGNORECASE):
        changed_files.extend(re.findall(r"[A-Za-z0-9_./\-]+\.(?:py|ts|tsx|js|go|rs|java|md|yaml|yml|json)", match))
    tests = [line.strip() for line in text.splitlines() if re.search(r"(?:pytest|npm test|cargo test|go test|测试验证|test)", line, re.IGNORECASE)]
    return {
        "code_blocks": code_blocks,
        "changed_files": list(dict.fromkeys(changed_files)),
        "test_plan": tests,
    }


def _ratio_for_round(cfg: dict, round_idx: int) -> float:
    """按轮次取压缩比（round_1 / round_2 ... 或 round_default）。"""
    ratios = cfg.get("compress_ratios", {})
    key = f"round_{round_idx}"
    return float(ratios.get(key, ratios.get("round_default", 0.4)))


def _rounds_for_complexity(cfg: dict, complexity: str) -> int:
    """阶段C：按任务复杂度动态取递归轮次，并与 max_rounds 硬上限取 min。

    simple 任务返回 1（不递归，净省 Token）；complex 才多轮深挖。
    缺失配置时降级为 max_rounds，保证向后兼容。
    """
    cap = int(cfg.get("max_rounds", 3))
    mapping = cfg.get("rounds_by_complexity", {})
    dynamic = int(mapping.get(complexity, cap))
    return max(1, min(dynamic, cap))  # 至少 1 轮，且不超过硬上限


@dataclass
class CscdResult:
    task_type: TaskType
    complexity: Complexity
    strategy: str
    budget: int
    anchor: str
    reason: str
    marks_valid: bool
    missing_marks: list = field(default_factory=list)
    recursed: bool = False  # 是否检测到新子目标并递归
    # ---- RoutingGen 风格动态路由字段 ----
    route: str = "standard"         # fast/standard/deep
    route_score: int = 0              # 0-10 任务复杂度评分
    # ---- J-Space 通行级校准字段 ----
    pass_level: str = "fast"        # J-Space 闸门: fast/full/loop
    loaded_modules: list = field(default_factory=list)  # 实际按需加载的模块
    missing_modules: list = field(default_factory=list)  # 计划加载但缺失的模块（J-Space 未安装时非空）
    untrusted_input: bool = False   # 不可信输入标志（强制 introspection）
    # ---- 阶段B：程序级级联压缩字段 ----
    rounds: int = 1                 # 实际递归轮次
    summaries: list = field(default_factory=list)   # 每轮压缩摘要（next_round_context）
    compress_methods: list = field(default_factory=list)  # 每轮压缩方式
    total_completion_tokens: int = 0  # 累计输出 Token（需 Carrier 支持 last_usage）
    raw_reason: str = ""            # 最后一轮完整轨迹（仅审计，不回传终端）
    final_context: str = ""        # 程序级压缩后的最终输出（替代式，回传终端）
    # ---- 阶段C：动态递归轮次字段 ----
    planned_rounds: int = 1        # 按复杂度动态计划的轮次（min(复杂度映射, max_rounds)）
    complexity_driven: bool = False  # 是否因复杂度降低了轮次（simple/medium 时为真）
    # ---- 编排级输出缓存（P1 任务内复用 + H1 硬短路）----
    cache_hits: int = 0            # 命中缓存、跳过 carrier.reason() 的轮次数
    cache_saved_tokens: int = 0    # 估算因命中而避免的 Token（含 prompt+completion 历史均值）
    # 缓存适用性：单原子缓存以四阶轨迹的 DECOMPOSE 为探针。若整轮模型始终输出
    # JSON 动作计划（prefer_action_plan 默认开启），则不存在原子，缓存天生不适用。
    # 必须区分「不适用」与「适用但未命中」——把前者报成 0 命中率会让看板展示虚假指标。
    cache_applicable: bool = False  # 本次运行是否存在可供缓存复用的四阶原子
    # ---- 推理时认知控制层（J-Space/dsh 补全，2026-08-18）----
    cognition: dict = field(default_factory=dict)  # 认知控制审计（workspace/稠密轨/桥接/元认知/锚定）
    # ---- 运行时状态外化账本（P4，2026-08-18）----
    ledger: dict = field(default_factory=dict)  # 账本审计（task_id/count/最后交付物）
    # ---- 工程交付物与执行证据（与 reasoning summary 分离）----
    delivery_artifact: dict = field(default_factory=dict)
    execution_evidence: list = field(default_factory=list)
    # ---- 硬性失败信息（仅保留调用异常，不再因格式失败 abort）----
    error: str = ""  # 非空表示本次运行因校验失败提前中止，reason/final_context 含错误信息


# 编排级输出缓存（P1：任务内复用；H1：硬短路 + need_review 兜底）
#
# 单原子级复用（2026-08-18 修订）：
# - 真实递归中 DECOMPOSE 原子列表逐轮演进，整轮指纹匹配命中率趋近 0；
# - 改为按「单个原子」存储结论：atom -> (classify_line, combine_line, need_review)；
# - 下一轮对每个原子先查单原子缓存：全部命中且无需回溯 -> 整轮硬短路；
#   部分命中 -> 把命中结论拼成强上下文注入 prompt，模型仅补全未命中原子（H2 轻量化）；
# - store 为可插拔字典，P2 跨任务持久时仅需替换为文件/数据库后端，核心逻辑不变。
DEFAULT_SAVED_PER_HIT = 1200  # 单次命中避免的 Token 估算均值（prompt+completion），待真实数据校准


@dataclass
class _AtomEntry:
    atom: str                         # 归一化原子文本（不含行首序号）
    classify: str = ""                # 该原子的 CLASSIFY 结论行
    combine: str = ""                 # 该原子的 COMBINE 结论行
    need_review: bool = False         # 置信度信号（待回溯则 True）


class RoundCache:
    """单原子级编排缓存：在 run() 多轮递归间复用模型已生成的逐原子结论。"""

    def __init__(self, store: dict = None):
        # store: atom(归一化) -> _AtomEntry；P2 升级点：替换为持久后端
        self.store = store if store is not None else {}

    @staticmethod
    def _atoms(text: str) -> list:
        """从 DECOMPOSE 段抽取归一化原子行（去行首序号、strip）。"""
        if not text:
            return []
        out = []
        for ln in text.splitlines():
            s = ln.strip()
            m = re.match(r"^\s*(\d+[.、]|\-|\*)\s*(.*)$", s)
            body = m.group(2).strip() if m else s
            if body:
                out.append(body)
        return out

    @staticmethod
    def _keyword(atom: str) -> str:
        """取原子首词（去标点）作为模糊匹配关键词。"""
        w = re.split(r"[\s，。、：:（）()\-]", atom)[0].strip("-* ")
        return w

    def _align(self, atoms: list, section_text: str) -> dict:
        """将 CLASSIFY/COMBINE 段按行对齐到原子：含原子关键词的行归属该原子。"""
        if not section_text:
            return {a: "" for a in atoms}
        lines = [ln.strip() for ln in section_text.splitlines() if ln.strip()]
        assign = {a: [] for a in atoms}
        for ln in lines:
            for a in atoms:
                if self._keyword(a) and self._keyword(a) in ln:
                    assign[a].append(ln)
                    break  # 归属首个匹配原子
        return {a: "\n".join(v) for a, v in assign.items()}

    def put(self, reason_text: str, need_review: tuple = ()) -> None:
        """从一轮轨迹抽取逐原子结论写入缓存。

        Args:
            reason_text: 本轮完整四阶轨迹。
            need_review: compressor 抽取的待回溯项（非空则整轮标记置信度不足）。
        """
        sec = parse_marks(reason_text)
        atoms = self._atoms(sec.get("DECOMPOSE") or "")
        if not atoms:
            return
        cls_map = self._align(atoms, sec.get("CLASSIFY") or "")
        com_map = self._align(atoms, sec.get("COMBINE") or "")
        nr_set = set(need_review)
        for a in atoms:
            # 若原子已在缓存且本次未带来新结论，保留旧值；否则覆盖
            self.store[a] = _AtomEntry(
                atom=a,
                classify=cls_map.get(a, ""),
                combine=com_map.get(a, ""),
                need_review=bool(nr_set),
            )

    def lookup(self, atoms_text: str):
        """查单原子缓存，返回 (hit_atoms, miss_atoms, context_str)。

        - hit_atoms: 命中且 need_review=False 的原子列表
        - miss_atoms: 未命中或需回溯的原子列表
        - context_str: 命中结论拼装的可注入上下文（供 H2 轻量化补全）
        """
        atoms = self._atoms(atoms_text)
        hit, miss = [], []
        ctx_lines = []
        for a in atoms:
            e = self.store.get(a)
            if e is not None and not e.need_review and (e.classify or e.combine):
                hit.append(a)
                if e.classify:
                    ctx_lines.append(f"[缓存·{a}] 分类: {e.classify}")
                if e.combine:
                    ctx_lines.append(f"[缓存·{a}] 结论: {e.combine}")
            else:
                miss.append(a)
        return hit, miss, "\n".join(ctx_lines)


def _extract_cognition(reason_text: str, prev: "CognitionState") -> "CognitionState":
    """从一轮模型轨迹中提取推理时认知信号（稠密轨/工作空间/桥接/元认知）。

    采用**确定性解析**（非模型自律）：
    - 工作空间：取本轮 DECOMPOSE 原子前 WORKSPACE_LIMIT 项；
    - 稠密轨：扫描轨迹中 ✓/?/✗/≈ 符号出现情况生成状态串；
    - 桥接概念：取 COMBINE 段中"已激活/中间概念"标记后的概念行；
    - 元认知动作：匹配 信任/重试/独立路径/经验验证 之一。
    解析不到时保留前值（前一轮认知状态），保证审计字段不丢失。
    """
    import re as _re
    new = prev or CognitionState()

    sections = parse_marks(reason_text)
    decomp = sections.get("DECOMPOSE") or ""
    combine = sections.get("COMBINE") or ""

    # 工作空间：DECOMPOSE 原子前 N 项（容量受限）
    atoms = [ln.strip() for ln in decomp.splitlines()
             if _re.match(r"^\s*(\d+[.、]|\-|\*)", ln)]
    if atoms:
        new.workspace = atoms[:WORKSPACE_LIMIT]

    # 稠密轨：统计符号出现
    dense = ""
    for sym, name in (("✓", "ok"), ("✗", "fail"), ("?", "check"), ("≈", "assume")):
        if sym in reason_text:
            dense += sym
    new.dense_track = dense or new.dense_track

    # 桥接概念：COMBINE 段中「已激活中间概念」之后的行
    m = _re.search(r"(?:已激活(?:中间)?概念|桥接概念)\s*[:：]\s*(.+)", combine)
    if m:
        new.bridged_concepts = [c.strip() for c in m.group(1).split("、") if c.strip()]

    # 元认知动作：匹配任一可选动作
    for act in ("信任", "重试", "独立路径", "经验验证"):
        if f"动作:{act}" in combine or f"元认知:{act}" in combine or act in combine:
            new.metacognition = act
            break

    # 机制3 桥接推理：解析 UNDERSTAND 步骤
    understand_m = _re.search(r"<UNDERSTAND>(.*?)</UNDERSTAND>", reason_text, _re.DOTALL)
    if understand_m:
        new.bridged_concepts = [line.strip() for line in understand_m.group(1).splitlines()
                                if line.strip() and not line.strip().startswith("<")]
        new.require_understand = False  # 已完成 UNDERSTAND
    return new

    return new


def _finalize_cognition(cognition: "CognitionState",
                        anchoring: "TrajectoryAnchoring") -> dict:
    """收尾：把锚定状态合并进认知审计字典。

    机制1 动态锚定：anchored 状态来自 cognition 自身（由 _extract_cognition 更新），
    不再依赖 anchoring 对象上的合成标志。
    """
    if cognition is None:
        return {"anchored": False}
    audit = cognition.to_audit()
    # 锚定状态已由 _extract_cognition 通过 RuntimeState 事件更新到 cognition
    audit["anchored"] = cognition.anchored
    audit["anchor_round"] = cognition.anchor_round
    audit["tool_whitelist"] = cognition.tool_whitelist
    return audit


class CscdEngine:
    """协议层编排器：依赖 Carrier 抽象，不依赖具体模型/运行时。

    阶段B：run() 在程序侧驱动多轮四阶推理，每轮 COMBINE 后调用 compressor
    做确定性压缩，将摘要拼入下一轮输入前缀，实现「混合方案」的级联压缩递归。
    """

    def __init__(self, carrier, config: dict = None):
        self.carrier = carrier
        self.config = config or load_config()

    def execute_actions(self, task_id: str, plan_text: str, root=None, state=None) -> list[dict]:
        """显式执行模型动作计划，不改变既有 carrier.reason() 调用链。"""
        from core.harness import Harness
        runtime_state = state or RuntimeState(task_id=task_id)
        workspace = RuntimeWorkspace(runtime_state.task_id, root=root)
        return Harness(root=root, workspace=workspace).run_action_plan(runtime_state, plan_text)

    def execute_action_loop(self, task_id: str, planner, root=None, state=None, max_steps: int = 20) -> dict:
        """执行规划器与工具之间的 P1 闭环，并返回最终状态与执行历史。"""
        from core.harness import Harness
        runtime_state = state or RuntimeState(task_id=task_id)
        workspace = RuntimeWorkspace(runtime_state.task_id, root=root)
        history = Harness(root=root, workspace=workspace).run_loop(
            runtime_state, planner, max_steps=max_steps,
        )
        return {"state": runtime_state.to_dict(), "history": history}

    def run(self, question: str,
            has_untrusted_input: bool = False,
            named_modules: list = None,
            task_id: str = None,
            persist_ledger: bool = True) -> CscdResult:
        task_type = classify_task(question)
        complexity = assess_complexity(question, task_type)
        strategy = select_strategy(complexity)
        route_task = {"title": question, "description": question, "language": "", "test_cases": []}
        routing_cfg = self.config.get("routing", {}).get("thresholds", {})
        router = Router()
        if routing_cfg:
            from core.routing import RouteConfig
            router = Router(RouteConfig(
                fast_max=int(routing_cfg.get("fast", router.config.fast_max)),
                deep_min=int(routing_cfg.get("deep", router.config.deep_min)),
            ))
        route_decision = router.select(route_task)
        route_score = route_decision.score
        route = route_decision.name

        # ---- 推理时运行状态：驱动阶段、工作空间、轨迹和交付物 ----
        runtime_state = RuntimeState(
            task_id=task_id or "untitled",
            goal=question,
            next_action="确认完成条件并读取相关代码",
        )
        runtime_root = Path(self.config.get("runtime_root", Path(__file__).parent.parent)).resolve()
        runtime_dir = Path(self.config.get("runtime_dir", runtime_root / ".cscd"))
        runtime_workspace = RuntimeWorkspace(runtime_state.task_id, root=runtime_dir)
        harness = Harness(root=runtime_root, workspace=runtime_workspace)
        workspace_enabled = bool(self.config.get("runtime_workspace", True))
        if workspace_enabled:
            runtime_workspace.record(runtime_state, "anchor_started")

        # ---- 运行时状态外化账本（P4）：兼容旧审计格式 ----
        # 由 config 控制是否外化（默认开启），可用显式 task_id 复用同一账本续跑
        ledger = None
        if persist_ledger and self.config.get("runtime_ledger", True):
            from core.ledger import Ledger, dump_round
            ledger = Ledger(task_id=task_id)
            ledger.note(question=question, task_type=str(task_type),
                        complexity=str(complexity), strategy=strategy)
        # 统一预算来源：按复杂度取 assess 层档位（simple=512 / medium=2048 / complex=8192）。
        # 允许 config 显式覆盖（budget_per_round）以保持向后兼容。
        budget = int(self.config.get("budget_per_round", budget_for(complexity)))

        # J-Space 通行级闸门（fast/full/loop）+ 按需模块选择
        pass_level = pass_level_for(complexity, has_untrusted_input)
        # selected 是「计划加载」，loaded_content 是「实际读到正文」的模块。
        # 两者在 J-Space 未安装时会不一致（第三方套件不随本仓库分发）。
        # 审计字段必须报告实际加载结果，否则会把未加载的模块记成已加载。
        selected = select_modules(pass_level, named_modules or [], has_untrusted_input)
        loaded_content = load_selected_modules(pass_level, named_modules or [], has_untrusted_input)
        loaded = list(loaded_content.keys())
        missing_modules = [name for name in selected if name not in loaded_content]
        loaded_context = modules_context(loaded_content)

        base_system = (
            f"{PERSONA}\n\n{TASK_RULES}\n\n"
            f"本轮任务类型: {task_type}；推理策略: {strategy}（据此调整四阶深度）\n"
            f"J-Space 通行级: {pass_level}；已加载模块: {', '.join(loaded) or '无(fast 直接答)'}"
            + (f"\n\n{loaded_context}" if loaded_context else "")
        )

        # ---- 推理时认知控制层（J-Space/dsh 补全）----
        # 认知状态：工作空间 + 稠密轨 + 桥接 + 元认知
        cognition = CognitionState()
        # dsh 首轮轨迹锚定状态机（是否启用由 config 控制）
        anchoring = TrajectoryAnchoring(
            enabled=bool(self.config.get("trajectory_anchoring", True))
        )
        # 认知控制注入开关（默认开启；P3 稠密轨/桥接可由 config 关闭以兼容既有任务）
        cognitive_enabled = bool(self.config.get("cognitive_control", True))

        # 阶段C：动态递归轮次 = min(复杂度映射, max_rounds 硬上限)
        # simple 任务=1 轮（不递归，净省 Token），complex=3 轮深挖
        planned_rounds = _rounds_for_complexity(self.config, complexity)
        max_rounds = planned_rounds
        complexity_driven = planned_rounds < int(self.config.get("max_rounds", 3))
        early_stop = bool(self.config.get("early_stop_on_stable", True))

        # 方向Y：simple 任务短路走基线直答（净成本=基线，不产生协议骨架开销）
        # 仅在无不可信输入（简单任务无需四阶校验）时生效；untrusted 仍走协议
        y_shortcut = (
            self.config.get("simple_shortcut_to_baseline", False)
            and complexity == "simple"
            and not has_untrusted_input
        )
        if y_shortcut:
            # 短路走基线直答：仍需写入完整阶段终点，保证恢复语义一致。
            base_text = self.carrier.reason_baseline(question)
            usage = getattr(self.carrier, "last_usage", None) or {}
            comp = int(usage.get("completion_tokens", 0))
            runtime_state.execution_evidence.append({"kind": "baseline_shortcut", "status": "completed"})
            # 基线短路没有执行 read/search 或测试，不得伪造锚定和交付事件。
            runtime_state.next_action = "基线直答完成，等待显式工程动作或验证证据"
            if workspace_enabled:
                runtime_workspace.record(runtime_state, "baseline_shortcut", {
                    "round": 1,
                    "ship_blocked": True,
                    "reason": "短路路径没有动作执行和测试证据",
                })
                runtime_state.delivery_artifact = {"reasoning_summary": base_text}
                runtime_workspace.record(runtime_state, "artifact")
            return CscdResult(
                reason=base_text,            # 终端回传即基线文本（替代式：不附加协议骨架）
                raw_reason=base_text,
                final_context=base_text,
                complexity=complexity,
                task_type=task_type,
                strategy=strategy,
                route=route,
                route_score=route_score,
                budget=budget,
                anchor="",                   # 短路路径无锚定
                pass_level=pass_level,
                loaded_modules=loaded,
                missing_modules=missing_modules,
                untrusted_input=has_untrusted_input,
                recursed=False,
                rounds=1,
                planned_rounds=1,
                complexity_driven=True,     # 因 simple 短路，标记复杂度驱动
                total_completion_tokens=comp,
                cache_hits=0,
                cache_saved_tokens=0,
                summaries=[],
                compress_methods=[],
                # 短路路径根本没有协议轨迹，不能声称四阶校验通过。
                # 此前硬编码 True，等于用伪造值冒充审计结果——
                # 调用方无法区分「四阶合规」与「压根没走四阶」。
                marks_valid=False,
                missing_marks=[],
                # 方向Y 短路：simple 直答，认知控制不施加（无多轮推理）
                cognition=CognitionState(anchored=False).to_audit(),
                # 短路路径：账本记录一次 note + ship（无多轮轨迹）
                ledger=({
                    "task_id": ledger.task_id,
                    "count": len(ledger.entries),
                    "last_ship": ledger.last_ship(),
                } if ledger else {}),
            )

        # L2 启动锚定：仅协议路径需要（Y 短路已提前返回），首轮极简锚定
        anchor = self.carrier.anchor(question)

        summaries: list = []
        compress_methods: list = []
        prev_summary = ""
        last_reason = ""
        last_vr_ok = False
        last_missing = []
        total_tokens = 0
        rounds = 0
        cache_hits = 0
        cache_saved = 0
        cache_applicable = False  # 是否存在任一四阶轮次可供缓存复用
        last_decompose = ""   # 上一轮完整轨迹的 DECOMPOSE 段（缓存探针来源）

        # 编排级输出缓存（P1 任务内复用）：跨轮次复用已生成的四阶结论
        cache = RoundCache()

        last_attempt_ok = True  # 跟踪最后一次模型调用的四阶校验结果

        for r in range(1, max_rounds + 1):
            rounds = r
            ratio = _ratio_for_round(self.config, r)

            # ---- 推理时认知控制（每轮动态）----
            # 锚定晋升只能由实际 Harness 动作事件触发，不能由轮次推断。
            tools = runtime_state.allowed_tools()
            action_mode = bool(self.config.get("prefer_action_plan", True))
            # 组装认知控制 System 注入（注入到 reason 调用的 system）
            phase_loaded, phase_module_content = load_phase_modules(
                runtime_state.phase,
                pass_level,
                has_untrusted_input,
            )
            if workspace_enabled:
                runtime_workspace.record(runtime_state, "modules_loaded", {
                    "round": r,
                    "phase": runtime_state.phase,
                    "modules": phase_loaded,
                    "loaded_content": list(phase_module_content),
                })
            cognition_system = modules_context(phase_module_content)
            if cognitive_enabled:
                # 机制2 工作空间限制：每轮根据当前阶段设置 focus
                if not cognition.focus:
                    cognition.focus = ["理解代码结构", "定位问题"]
                # 机制3 桥接推理：在 implement 阶段要求 UNDERSTAND
                if runtime_state.phase in ("implement", "verify"):
                    cognition.require_understand = True
                cognition_system = f"{cognition_system}\n\n" + build_cognition_system(
                    cognition, anchoring, r,
                    anchored=runtime_state.promoted,
                    tools=tools,
                )

            # 拼接上一轮摘要作为本轮上下文前缀（级联压缩核心）
            if prev_summary:
                prompt = (
                    f"[上一轮递归压缩摘要]\n{prev_summary}\n\n"
                    f"[本轮新任务] 基于上述摘要继续：{question}"
                )
            else:
                prompt = f"请按 C-S-C-D 协议处理：{question}"

            # ---- 单原子级缓存查询（H1 硬短路 + H2 轻量化补全）----
            # 探针用上一轮完整轨迹的 DECOMPOSE 原子列表（非压缩摘要，后者已丢失原子）
            hit_atoms, miss_atoms, cache_ctx = ([], [], "")
            if last_decompose:
                hit_atoms, miss_atoms, cache_ctx = cache.lookup(last_decompose)

            # 本轮是否为 H1 硬短路轮（后续「是否回写缓存 / 是否更新 prev_summary」共用此判定）
            is_cache_hit_round = bool(hit_atoms and not miss_atoms)

            if is_cache_hit_round:
                # H1 硬短路：本轮所有原子均已缓存且无需回溯 -> 直接复用，跳过模型调用
                cache_hits += 1
                cache_saved += DEFAULT_SAVED_PER_HIT * len(hit_atoms)
                # 用缓存结论构造等价四阶轨迹供压缩层消费
                # 注意：四阶协议要求 DECOMPOSE/CLASSIFY/SELECT/COMBINE 四段齐全。
                # 命中原子的 SELECT 结论取自缓存 classify（视为已通过事实池筛选），
                # 补齐 SELECT 段保证 validate_marks 通过，避免审计字段失真。
                select_lines = [f"{i+1}. {a}" for i, a in enumerate(hit_atoms)]
                reason_text = (
                    f"<DECOMPOSE>\n" + "\n".join(f"{i+1}. {a}" for i, a in enumerate(hit_atoms))
                    + f"\n</DECOMPOSE>\n<CLASSIFY>\n{cache_ctx}\n</CLASSIFY>\n"
                    f"<SELECT>\n" + "\n".join(select_lines)
                    + f"\n</SELECT>\n<COMBINE>\n{cache_ctx}\n</COMBINE>"
                )
                if self.config.get("legacy_marks_fallback", False):
                    vr = validate_marks(reason_text)
                    last_vr_ok = vr.ok
                    last_missing = vr.missing.copy()
                else:
                    vr = SimpleNamespace(ok=True, missing=[])
                    last_vr_ok = True
                    last_missing = []
                # 命中轮不发起模型调用，不累加 total_tokens
                # H1 硬短路轮：本轮 DECOMPOSE 即命中原子集合，供下轮探针
                last_decompose = "\n".join(f"{i+1}. {a}" for i, a in enumerate(hit_atoms))
            else:
                # H2 轻量化：未命中原子需模型补全；命中结论作为强上下文注入，减少重复生成
                if cache_ctx:
                    prompt = (
                        f"[已缓存的原子结论，直接复用，勿重复生成]\n{cache_ctx}\n\n"
                        + prompt
                    )
                # 分阶段动态注入：只把当前状态投影给模型，不重复注入全部历史。
                runtime_state.round_index = r
                runtime_state_prompt = (
                    "[CSCD 运行时状态]\n"
                    f"阶段: {runtime_state.phase}\n"
                    f"目标: {runtime_state.goal}\n"
                    f"已验证: {', '.join(runtime_state.verified[-5:]) or '暂无'}\n"
                    f"开放问题: {', '.join(runtime_state.open_questions[-5:]) or '暂无'}\n"
                    f"下一步: {runtime_state.next_action or '由当前阶段决定'}\n"
                    f"允许动作: {', '.join(runtime_state.allowed_tools())}\n"
                    + ("IMPLEMENT 阶段必须明确 changed_files。\n" if runtime_state.phase == "implement" else "")
                    + ("VERIFY 阶段必须记录 test_commands 和 test_results。\n" if runtime_state.phase == "verify" else "")
                    # 输出格式必须二选一并显式声明优先级。原实现无条件要求 JSON 动作计划，
                    # 与 PERSONA 的 XML 四阶要求直接冲突——真实端点已复现模型因此陷入权衡、
                    # 把整段英文独白当作正文输出，四阶协议完全未执行。
                    + (
                        "[输出格式·本轮最高优先级] 本轮为动作执行模式：只输出一个 JSON 动作计划，"
                        "不要输出 C-S-C-D 的 XML 标记（<DECOMPOSE>/<CLASSIFY>/<SELECT>/<COMBINE>）。"
                        "四阶推理在内部完成，以动作计划体现。格式："
                        '{"actions":[{"action":"<允许动作之一>","path/query/command":...}]}\n'
                        if action_mode else
                        # 协议模式：四阶 XML 是唯一交付物。此前只说「严格按 PERSONA 输出」，
                        # 面对下方大量检查点/认知控制指令，模型会把权衡过程写进正文
                        # （实测泄漏为英文元推理）。故显式禁止过程外泄并要求中文作答。
                        "[输出格式·本轮最高优先级] 你的唯一交付物是 C-S-C-D 四阶 XML："
                        "<DECOMPOSE>…</DECOMPOSE>、<CLASSIFY>…</CLASSIFY>、"
                        "<SELECT>…</SELECT>、<COMBINE>…</COMBINE>，四段齐全且按此顺序。\n"
                        "禁止输出：思考过程、自我权衡、格式讨论、英文分析、任何四阶标记之外的解释性文字。\n"
                        "所有内容使用中文。\n"
                    )
                    + ("若已完成当前阶段，追加对应完成动作（如 exploration_completed）。"
                       if action_mode else "")
                )
                # 注入认知控制指令到 system（编排层 base_system + 当前状态 + 认知层）
                system = f"{base_system}\n\n{runtime_state_prompt}"
                if cognition_system:
                    system = f"{system}\n\n{cognition_system}"
                reason_text = self.carrier.reason(prompt, system, budget)
                last_reason = reason_text
                parsed_actions = Harness.parse_plan(reason_text)
                runtime_state.round_index = r
                if parsed_actions:
                    action_results = harness.run_action_plan(runtime_state, reason_text)
                    vr = SimpleNamespace(ok=True, missing=[])
                    last_attempt_ok = True
                    last_vr_ok = True
                    last_missing = []
                    # 动作计划轮同样可能携带四阶轨迹：真实模型常在同一响应里既给 JSON 动作
                    # 又按协议输出 <DECOMPOSE>。原子是单原子缓存探针的唯一来源，此处必须同样
                    # 提取——否则一旦走动作模式，缓存就永远查不到也写不进（真实验证已复现）。
                    last_decompose = parse_marks(reason_text).get("DECOMPOSE") or ""
                    if last_decompose:
                        cache_applicable = True
                    runtime_state.next_action = "基于执行结果继续下一步动作"
                    if workspace_enabled:
                        runtime_workspace.record(runtime_state, "action_plan_executed", {
                            "kind": "action_plan_executed",
                            "round": r,
                            "plan": reason_text[:4000],
                            "results": action_results,
                        })
                else:
                    # 缓存探针数据源：无论是否启用 legacy 校验，都从四阶轨迹提取 DECOMPOSE。
                    # legacy_marks_fallback 只决定「是否兼容旧输出」，与缓存取样无关；
                    # 若把取样也关掉，P1 单原子缓存将永远查不到、也永远写不进，cache_hits 恒为 0。
                    last_decompose = parse_marks(reason_text).get("DECOMPOSE") or ""
                    if last_decompose:
                        cache_applicable = True
                    # 四阶标记「审计」与「阻断」解耦：
                    # - 审计必须始终执行：marks_valid/missing_marks 是对外承诺的可追溯性字段，
                    #   此前仅在 legacy_marks_fallback 开启时才真校验，默认配置下恒为 True——
                    #   等于用伪造值冒充审计结果。
                    # - 阻断路径已移除（marks_blocking 默认 false 且不再触发 abort），
                    #   故始终校验不改变任何执行/交付行为，只让审计值恢复真实。
                    vr = validate_marks(reason_text)
                    last_attempt_ok = vr.ok
                    last_vr_ok = vr.ok
                    last_missing = vr.missing.copy()

                    # 非动作文本只作为观察，不能改变执行阶段或伪造执行证据。
                    cognition = _extract_cognition(reason_text, cognition)
                    # 机制3 桥接推理：验证 UNDERSTAND 步骤是否完成
                    if cognition.require_understand:
                        if not re.search(r"<UNDERSTAND>", reason_text):
                            runtime_state.next_action = "未完成 UNDERSTAND 步骤。请先输出 <UNDERSTAND> 理解代码逻辑，再进入 SELECT 和 COMBINE。"
                        else:
                            runtime_state.next_action = "UNDERSTAND 已完成，可以进入 SELECT 和 COMBINE。"
                    runtime_state.update_from_text(reason_text)
                    artifact = _extract_delivery_artifact(reason_text)
                    if artifact:
                        runtime_state.delivery_artifact = artifact
                        runtime_state.changed_files.extend(
                            f for f in artifact.get("changed_files", [])
                            if f not in runtime_state.changed_files
                        )
                        runtime_state.test_commands.extend(
                            f for f in artifact.get("test_plan", [])
                            if f not in runtime_state.test_commands
                        )
                    runtime_state.next_action = "模型未返回可执行动作，等待下一轮动作计划"
                    if workspace_enabled:
                        runtime_workspace.record(runtime_state, "model_observation", {
                            "marks_valid": vr.ok,
                            "missing_marks": list(vr.missing),
                            "legacy_fallback": bool(self.config.get("legacy_marks_fallback", False)),
                            "summary": reason_text[:4000],
                        })

                # Token 计量（Carrier 暴露 last_usage 时累加）
                try:
                    total_tokens += int(getattr(self.carrier, "last_usage", {}).get("completion_tokens", 0))
                except Exception:
                    pass

            # 程序级压缩：对全轮轨迹（优先 COMBINE）做确定性压缩
            cr = compress_summary(reason_text, ratio)
            # 写缓存：H1 硬短路轮的结论本就全部取自缓存，回写无意义；
            # 其余轮（含首轮——此时 miss_atoms 为空但模型已产出新结论）必须写入。
            # 原条件 `if miss_atoms` 会让首轮永不写缓存，下一轮探针无缓存可查，P1 复用彻底失效。
            if not is_cache_hit_round:
                cache.put(reason_text, need_review=tuple(cr.need_review))
            summaries.append(cr.next_round_context)
            compress_methods.append(cr.method)

            # ---- 运行时状态外化（P4）：每轮认知状态 + 轨迹摘要写入账本 ----
            if ledger is not None:
                dump_round(ledger, r, cognition.to_audit() if cognition else {},
                           last_vr_ok, cr.next_round_context)
                ledger.seam(round_idx=r)

            # 关键：仅 H2/模型轮更新 prev_summary（下一轮上下文 + 最终回传来源）。
            # H1 硬短路轮的 reason_text 是「缓存拼接」的构造轨迹（含 [缓存·] 调试前缀），
            # 若用作 prev_summary 会污染上一轮的精炼摘要，进而成为终端 final_context，
            # 违背"最终回传精炼结论"的设计意图。故硬短路轮保留上一轮精炼摘要。
            if not is_cache_hit_round:
                prev_summary = cr.next_round_context

            # 早停：连续两轮摘要一致
            if early_stop and r >= 2 and len(summaries) >= 2 and summaries[-1] == summaries[-2]:
                break

        # XML 标记失败只记录观察，不阻断交付；真实调用异常仍由 Carrier 抛出。
        # SHIP 只认通过测试证据；失败测试和模型文本不能触发交付。
        def is_passing_test(result) -> bool:
            if isinstance(result, dict):
                return result.get("ok") is True or result.get("returncode") == 0
            try:
                parsed = json.loads(str(result))
            except (TypeError, json.JSONDecodeError):
                return False
            return isinstance(parsed, dict) and (
                parsed.get("ok") is True or parsed.get("returncode") == 0
            )

        ship_evidence = any(is_passing_test(result) for result in runtime_state.test_results)
        if ship_evidence:
            runtime_state.set_phase("ship")
            runtime_state.next_action = "整理交付物并核对执行证据"
            runtime_state.execution_evidence.append({
                "kind": "rounds_completed",
                "rounds": rounds,
                "marks_valid": last_vr_ok,
                "missing_marks": list(last_missing),
                "ship_evidence": True,
            })
        else:
            runtime_state.next_action = "缺少验证证据（test_results/verified 为空），不得进入 SHIP"
            runtime_state.execution_evidence.append({
                "kind": "ship_blocked",
                "rounds": rounds,
                "reason": "缺少测试结果或已验证结论",
            })
        if workspace_enabled:
            runtime_workspace.record(runtime_state, "ship" if ship_evidence else "ship_blocked",
                                     {"round": rounds})
            runtime_workspace.record(runtime_state, "ship_prepared")

        # 阶段B 摘要仅作为 reasoning_state；交付物优先保留最后一轮完整输出。
        # 四阶合规时回传最后一轮轨迹（保留可追溯的完整结构）；
        # 四阶不合规时 last_reason 是模型的自由发挥/元推理独白，直接回传等于
        # 把污染文本当作结论交付——此时只回传压缩摘要，并让 marks_valid 如实反映失败。
        final_context = last_reason if last_vr_ok else (prev_summary or last_reason)
        runtime_state.delivery_artifact.setdefault("reasoning_summary", prev_summary)
        if workspace_enabled:
            runtime_workspace.record(runtime_state, "artifact")

        # 只有通过测试证据充分时才写入最终 ship 账本。
        if ledger is not None and ship_evidence:
            ledger.ship(artifact=final_context,
                        summary=f"{strategy}/{complexity} · {rounds}轮 · {total_tokens}tok")
        return CscdResult(
            task_type=task_type,
            complexity=complexity,
            strategy=strategy,
            route=route,
            route_score=route_score,
            budget=budget,
            anchor=anchor,
            reason=final_context,          # 替代式：回传压缩摘要，非全量
            raw_reason=last_reason,        # 审计：最后一轮全量轨迹
            marks_valid=last_vr_ok,
            missing_marks=last_missing,
            recursed=rounds > 1,
            pass_level=pass_level,
            loaded_modules=loaded,
            missing_modules=missing_modules,
            untrusted_input=has_untrusted_input,
            rounds=rounds,
            summaries=summaries,
            compress_methods=compress_methods,
            total_completion_tokens=total_tokens,
            final_context=final_context,
            planned_rounds=planned_rounds,
            complexity_driven=complexity_driven,
            cache_hits=cache_hits,
            cache_saved_tokens=cache_saved,
            cache_applicable=cache_applicable,
            # 推理时认知控制审计：同步 dsh 锚定状态 + 各轮认知信号
            cognition=_finalize_cognition(cognition, anchoring),
            delivery_artifact=runtime_state.delivery_artifact,
            execution_evidence=runtime_state.execution_evidence,
            # 运行时状态外化账本审计（task_id/条目数/最后交付物）
            ledger=({
                "task_id": ledger.task_id,
                "count": len(ledger.entries),
                "last_ship": ledger.last_ship(),
            } if ledger else {}),
        )
