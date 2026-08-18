"""
C-S-C-D 四阶递归主循环（协议层核心，载体无关）
=============================================
本模块不调用任何模型，只负责：装配 Prompt、驱动 Carrier 执行、
校验四阶标记、并按协议决定是否递归（产生新子目标时回到 DECOMPOSE）。
"""

from dataclasses import dataclass, field
from typing import Optional
import re
import sys
import yaml
from pathlib import Path

from core.classify import classify_task, TaskType
from core.assess import (assess_complexity, select_strategy, budget_for,
                         pass_level_for, Complexity)
from core.marks import validate_marks, parse_marks
from core.jspace_modules import select_modules
from core.compressor import compress_summary
from core.cognition import (
    CognitionState, TrajectoryAnchoring, build_cognition_system,
    WORKSPACE_LIMIT,
)

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
_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
_DEFAULT_CONFIG = {
    "compress_ratios": {"round_1": 0.6, "round_2": 0.5, "round_3": 0.4, "round_default": 0.4},
    "max_rounds": 3,
    "budget_per_round": 2048,
    "temperature": 0.3,
    "early_stop_on_stable": True,
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
    # ---- J-Space 通行级校准字段 ----
    pass_level: str = "fast"        # J-Space 闸门: fast/full/loop
    loaded_modules: list = field(default_factory=list)  # 实际按需加载的模块
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
    # ---- 推理时认知控制层（J-Space/dsh 补全，2026-08-18）----
    cognition: dict = field(default_factory=dict)  # 认知控制审计（workspace/稠密轨/桥接/元认知/锚定）
    # ---- 运行时状态外化账本（P4，2026-08-18）----
    ledger: dict = field(default_factory=dict)  # 账本审计（task_id/count/最后交付物）
    # ---- 硬性失败信息（issue 8：校验失败 abort）----
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


def _marks_abort_result(
    task_type, complexity, strategy, budget, anchor,
    pass_level, loaded, untrusted,
    missing, total_tokens, rounds,
) -> CscdResult:
    """构造四阶标记校验失败后的 abort 结果（保持返回类型兼容，issue 8）。"""
    msg = "marks validation failed after retry"
    return CscdResult(
        task_type=task_type,
        complexity=complexity,
        strategy=strategy,
        budget=budget,
        anchor=anchor,
        reason=msg,
        final_context=msg,
        marks_valid=False,
        missing_marks=list(missing),
        recursed=False,
        pass_level=pass_level,
        loaded_modules=loaded,
        untrusted_input=untrusted,
        rounds=rounds,
        summaries=[],
        compress_methods=[],
        total_completion_tokens=total_tokens,
        raw_reason="",
        planned_rounds=0,
        complexity_driven=False,
        cache_hits=0,
        cache_saved_tokens=0,
        cognition={"anchored": False},
        ledger={},
        error=msg,
    )


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

    return new


def _finalize_cognition(cognition: "CognitionState",
                        anchoring: "TrajectoryAnchoring") -> dict:
    """收尾：把 dsh 锚定状态合并进认知审计字典。"""
    if cognition is None:
        return {"anchored": False}
    audit = cognition.to_audit()
    audit["anchored"] = anchoring.anchored
    audit["anchor_round"] = anchoring.anchor_round
    audit["tool_whitelist"] = anchoring.first_round_whitelist
    return audit


class CscdEngine:
    """协议层编排器：依赖 Carrier 抽象，不依赖具体模型/运行时。

    阶段B：run() 在程序侧驱动多轮四阶推理，每轮 COMBINE 后调用 compressor
    做确定性压缩，将摘要拼入下一轮输入前缀，实现「混合方案」的级联压缩递归。
    """

    def __init__(self, carrier, config: dict = None):
        self.carrier = carrier
        self.config = config or load_config()

    def run(self, question: str,
            has_untrusted_input: bool = False,
            named_modules: list = None,
            task_id: str = None,
            persist_ledger: bool = True) -> CscdResult:
        task_type = classify_task(question)
        complexity = assess_complexity(question, task_type)
        strategy = select_strategy(complexity)

        # ---- 运行时状态外化账本（P4）：记录认知状态/轨迹/交付物，支持 resume ----
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
        loaded = select_modules(pass_level, named_modules or [], has_untrusted_input)

        base_system = (
            f"{PERSONA}\n\n{TASK_RULES}\n\n"
            f"本轮任务类型: {task_type}；推理策略: {strategy}（据此调整四阶深度）\n"
            f"J-Space 通行级: {pass_level}；已加载模块: {', '.join(loaded) or '无(fast 直接答)'}"
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
            # 短路走基线直答：不发起 anchor 调用（锚定仅协议路径需要），省一次模型调用
            base_text = self.carrier.reason_baseline(question)
            usage = getattr(self.carrier, "last_usage", None) or {}
            comp = int(usage.get("completion_tokens", 0))
            return CscdResult(
                reason=base_text,            # 终端回传即基线文本（替代式：不附加协议骨架）
                raw_reason=base_text,
                final_context=base_text,
                complexity=complexity,
                task_type=task_type,
                strategy=strategy,
                budget=budget,
                anchor="",                   # 短路路径无锚定
                pass_level=pass_level,
                loaded_modules=loaded,
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
                marks_valid=True,
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
        last_decompose = ""   # 上一轮完整轨迹的 DECOMPOSE 段（缓存探针来源）

        # 编排级输出缓存（P1 任务内复用）：跨轮次复用已生成的四阶结论
        cache = RoundCache()

        # 四阶标记校验失败重试计数（issue 8：无效不交付）
        retry_marks = 0
        last_attempt_ok = True  # 跟踪最后一次模型调用的四阶校验结果

        for r in range(1, max_rounds + 1):
            rounds = r
            ratio = _ratio_for_round(self.config, r)

            # ---- 推理时认知控制（每轮动态）----
            # dsh 首轮锚定：本轮工具集 + 晋升判定（首轮有持久输出即晋升解锁完整工具）
            tools = anchoring.tools_for_round(r, has_persistent_output=bool(last_decompose))
            # 组装认知控制 System 注入（注入到 reason 调用的 system）
            cognition_system = ""
            if cognitive_enabled:
                cognition_system = build_cognition_system(
                    cognition, anchoring, r,
                    anchored=anchoring.anchored,
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

            if hit_atoms and not miss_atoms:
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
                vr = validate_marks(reason_text)
                last_vr_ok = vr.ok
                last_missing = vr.missing.copy()
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
                # 注入认知控制指令到 system（编排层 base_system + 推理时认知层指令）
                system = base_system
                if cognition_system:
                    system = f"{base_system}\n\n{cognition_system}"
                reason_text = self.carrier.reason(prompt, system, budget)
                last_reason = reason_text
                vr = validate_marks(reason_text)
                last_attempt_ok = vr.ok
                last_missing = vr.missing.copy()  # 同时记录失败详情（供 post-loop abort 使用）
                if not vr.ok:
                    # 四阶标记校验失败：不压缩/不缓存/不记账，重试或 abort（issue 8）
                    retry_marks += 1
                    if retry_marks >= 2:
                        print(f"⚠️ [CSCD] 四阶标记校验失败（missing={vr.missing}），已重试 {retry_marks} 次，终止。", file=sys.stderr)
                        return _marks_abort_result(
                            task_type, complexity, strategy, budget, anchor,
                            pass_level, loaded, has_untrusted_input,
                            vr.missing, total_tokens, rounds,
                        )
                    print(f"⚠️ [CSCD] 第 {r} 轮四阶标记校验失败（missing={vr.missing}），重试…", file=sys.stderr)
                    continue  # 跳过本轮压缩/缓存/账本，下一轮重试
                last_vr_ok = True
                last_decompose = parse_marks(reason_text).get("DECOMPOSE") or ""

                # 提取本轮认知信号（稠密轨 / 工作空间 / 桥接概念 / 元认知动作）
                cognition = _extract_cognition(reason_text, cognition)

                # Token 计量（Carrier 暴露 last_usage 时累加）
                try:
                    total_tokens += int(getattr(self.carrier, "last_usage", {}).get("completion_tokens", 0))
                except Exception:
                    pass

            # 程序级压缩：对全轮轨迹（优先 COMBINE）做确定性压缩
            cr = compress_summary(reason_text, ratio)
            # 写缓存：仅未命中原子需补全的 H2 轮写入新结论（命中轮结论已在缓存）
            if miss_atoms:
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
            if not (hit_atoms and not miss_atoms):
                prev_summary = cr.next_round_context

            # 早停：连续两轮摘要一致
            if early_stop and r >= 2 and summaries[-1] == summaries[-2]:
                break

        # 四阶标记校验失败：最后一次模型调用无效且已重试过 → abort 不交付（issue 8）
        if not last_attempt_ok and retry_marks >= 1:
            return _marks_abort_result(
                task_type, complexity, strategy, budget, anchor,
                pass_level, loaded, has_untrusted_input,
                last_missing, total_tokens, rounds,
            )

        # 阶段B「替代式」核心：最终回传内容 = 程序级压缩后的最终摘要，
        # 而非最后一轮的全量轨迹。全量轨迹仅留存 raw_reason 供审计，
        # 从而让压缩真实削减终端输出（而非追加）。
        final_context = prev_summary or last_reason

        # 运行时状态外化（P4）：定稿交付物到账本
        if ledger is not None:
            ledger.ship(artifact=final_context,
                        summary=f"{strategy}/{complexity} · {rounds}轮 · {total_tokens}tok")

        return CscdResult(
            task_type=task_type,
            complexity=complexity,
            strategy=strategy,
            budget=budget,
            anchor=anchor,
            reason=final_context,          # 替代式：回传压缩摘要，非全量
            raw_reason=last_reason,        # 审计：最后一轮全量轨迹
            marks_valid=last_vr_ok,
            missing_marks=last_missing,
            recursed=rounds > 1,
            pass_level=pass_level,
            loaded_modules=loaded,
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
            # 推理时认知控制审计：同步 dsh 锚定状态 + 各轮认知信号
            cognition=_finalize_cognition(cognition, anchoring),
            # 运行时状态外化账本审计（task_id/条目数/最后交付物）
            ledger=({
                "task_id": ledger.task_id,
                "count": len(ledger.entries),
                "last_ship": ledger.last_ship(),
            } if ledger else {}),
        )
