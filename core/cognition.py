"""
推理时认知控制层（J-Space / dsh 机制补全）
=========================================
这是 C-S-C-D「编排层」（四阶任务拆解）之外的**推理时认知控制层**：
在模型生成推理轨迹的过程中，动态约束其「能激活什么信息」、「如何记录推理状态」、
「如何响应置信度信号」、「首轮看到什么」。

与 core/jspace_modules.py 的区别：
- jspace_modules.py 只负责「何时加载哪个模块」（注册表 + 通行级闸门）。
- 本模块把这些机制的**可执行指令**落地为 System Prompt 注入片段 + 结构化审计字段，
  让 CscdEngine 在每轮推理中真正施加认知控制，而非仅作模块清单。

对照来源：
- J-Space Cognition Suite V3.6：工作空间/稠密轨/桥接推理/元认知/经验逃逸。
- dsh-anchored-standard：首轮轨迹锚定（工具白名单 + 晋升机制）。
"""

from dataclasses import dataclass, field
import re
from typing import Optional, List

# ---------- 常量：认知控制参数 ----------
# 工作空间容量：限制同时激活的项目数（J-Space capacity 模块）
WORKSPACE_LIMIT = 5

# 稠密轨符号（J-Space shorthand 模块：golden rule）
DENSE_SYMBOLS = {
    "ok": "✓",      # 已确认/已廉价验证
    "check": "?",   # 待验证/存疑
    "fail": "✗",    # 已排除/失败
    "assume": "≈",  # 假设/未廉验
}

# 元认知动作选项（J-Space self-monitoring 模块：must act）
METACOGNITION_ACTIONS = ["信任", "重试", "独立路径", "经验验证"]


@dataclass(frozen=True)
class UnderstandContract:
    """ICoT 理解阶段契约；字段完整后才允许进入代码生成。"""

    fields: tuple[str, ...] = (
        "algorithm_intent", "input_output", "state_change", "problem", "plan", "complexity",
    )

    labels: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("algorithm_intent", ("算法意图", "algorithm intent")),
        ("input_output", ("输入输出", "input", "output")),
        ("state_change", ("状态变化", "state change")),
        ("problem", ("问题定位", "问题", "problem")),
        ("plan", ("修复方案", "方案", "plan")),
        ("complexity", ("复杂度", "时间复杂度", "空间复杂度", "complexity")),
    )

    def validate(self, text: str) -> dict:
        content = str(text or "")
        present = {
            field: any(label.lower() in content.lower() for label in labels)
            for field, labels in self.labels
        }
        missing = [field for field in self.fields if not present[field]]
        return {"valid": not missing, "fields": present, "missing": missing}


def build_understand_prompt() -> str:
    """生成 ICoT UNDERSTAND 阶段的统一要求。"""
    return (
        "[ICoT UNDERSTAND] 生成代码前必须完成以下六项，不得跳过：\n"
        "1. 算法意图：核心算法/数据结构是什么，为什么这样设计？\n"
        "2. 输入输出：输入是什么？输出契约是什么，边界如何界定？\n"
        "3. 状态变化：哪些状态会被读取、修改或持久化？\n"
        "4. 问题定位：具体缺陷位于哪个函数或条件分支？\n"
        "5. 修复方案：准备如何修改，并如何覆盖边界条件？\n"
        "6. 复杂度：时间复杂度和空间复杂度是多少？\n"
        "请使用 <UNDERSTAND>...</UNDERSTAND> 包裹完整内容；六项缺失任意一项都不能进入代码生成，完成后才能进入 SELECT 和 COMBINE。"
    )


@dataclass
class CognitionState:
    """一轮推理的认知控制状态（可审计）。

    机制2 工作空间限制：focus 限制模型当前可处理的信息范围。
    机制3 桥接推理：require_understand 强制模型在 SELECT 前完成理解步骤。
    """
    workspace: List[str] = field(default_factory=list)      # 当前激活项目（≤ WORKSPACE_LIMIT）
    focus: List[str] = field(default_factory=list)           # 机制2：当前 focus 范围
    dense_track: str = ""                                   # 稠密轨符号串（✓/?/✗/≈）
    bridged_concepts: List[str] = field(default_factory=list)  # 桥接推理：COMBINE 前已激活概念
    metacognition: str = ""                                 # 元认知动作选择（信任/重试/独立路径/经验验证）
    anchored: bool = False                                  # dsh：首轮锚定是否完成（晋升）
    anchor_round: int = 0                                   # 锚定完成的轮次
    tool_whitelist: List[str] = field(default_factory=list) # dsh：当前暴露的工具白名单
    require_understand: bool = False                         # 机制3：是否需要 UNDERSTAND 步骤

    def to_prompt_fragment(self, round_idx: int) -> str:
        """生成注入本轮 System Prompt 的认知控制指令片段。"""
        parts = [
            "[推理时认知控制]",
            f"当前工作空间（仅可激活，其余暂不处理）: {', '.join(self.workspace) or '(空，从本轮 DECOMPOSE 中选择≤%d项)' % WORKSPACE_LIMIT}",
            f"稠密轨（用符号记录每个原子的推理状态）: {', '.join(DENSE_SYMBOLS.values())} 分别表示 确认/待验/失败/假设",
            "COMBINE 前必须输出「已激活中间概念」列表（桥接推理检查点），确保结论建立在这些概念之上。",
            "每轮结束必须对当前置信度选择一个元认知动作: " + "/".join(METACOGNITION_ACTIONS),
            f"推理轮次: {round_idx}。",
        ]
        return "\n".join(parts)

    def to_audit(self) -> dict:
        """输出审计字段。"""
        return {
            "workspace": self.workspace,
            "workspace_limit": WORKSPACE_LIMIT,
            "focus": self.focus,
            "dense_track": self.dense_track,
            "bridged_concepts": self.bridged_concepts,
            "metacognition": self.metacognition,
            "anchored": self.anchored,
            "anchor_round": self.anchor_round,
            "tool_whitelist": self.tool_whitelist,
            "require_understand": self.require_understand,
        }


# ---------- dsh 首轮轨迹锚定（P0） ----------
# 首轮只暴露极简工具（白名单），晋升后再解锁完整工具集。
# 机制1 动态锚定：晋升由 RuntimeState 的 first_read 事件实际触发，不再依赖合成标志。
INITIAL_TOOL_WHITELIST = ["read", "search"]
FULL_TOOLSET = ["read", "search", "bash", "edit", "write", "run", "review", "test", "deploy"]


class TrajectoryAnchoring:
    """dsh-anchored-standard 首轮轨迹锚定状态机。

    机制1 动态锚定：首轮只暴露 read/search，模型实际执行 read 或 search 后，
    RuntimeState.apply_event("first_read") 触发 promoted，解锁完整工具集。
    锚定状态完全由 RuntimeState.promoted 驱动，本类仅生成提示片段。
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def to_prompt_fragment(self, tools: list[str], anchored: bool) -> str:
        """生成注入本轮的工具可用性指令。

        anchored 直接取自 RuntimeState.promoted，确保首轮提示词与真实状态一致。
        """
        if not self.enabled:
            return ""
        if anchored:
            return "[工具状态] 已晋升：完整工具集可用（read/search/edit/write/run_test/inspect_failure/checkpoint/rollback/ship）。"
        return f"[工具状态] 首轮锚定阶段：仅暴露 {', '.join(tools)}。先执行 read 或 search 理解代码，之后解锁全部工具。"


# ---------- 认知控制指令组装 ----------
def build_cognition_system(
    state: CognitionState,
    anchoring: TrajectoryAnchoring,
    round_idx: int,
    anchored: bool,
    tools: list[str],
) -> str:
    """组装认知控制层 System Prompt 片段（注入到 base_system）。

    机制1 动态锚定：anchored 取自 RuntimeState.promoted，由 first_read 事件触发。
    机制2 工作空间限制：focus 信息注入到提示词中。
    机制3 桥接推理：UNDERSTAND 步骤约束注入到提示词中。
    """
    parts = [
        state.to_prompt_fragment(round_idx),
        anchoring.to_prompt_fragment(tools, anchored),
    ]
    # 机制2 工作空间限制：注入 focus 约束
    if state.focus:
        parts.append(f"[工作空间限制] 当前 focus: {', '.join(state.focus)}。仅处理 focus 内的信息，其他信息暂不处理。")
    # 机制3 桥接推理：注入 UNDERSTAND 步骤约束
    if state.require_understand:
        parts.append("[桥接推理] " + build_understand_prompt())
    return "\n".join(parts)
