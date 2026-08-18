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


@dataclass
class CognitionState:
    """一轮推理的认知控制状态（可审计）。"""
    workspace: List[str] = field(default_factory=list)      # 当前激活项目（≤ WORKSPACE_LIMIT）
    dense_track: str = ""                                   # 稠密轨符号串（✓/?/✗/≈）
    bridged_concepts: List[str] = field(default_factory=list)  # 桥接推理：COMBINE 前已激活概念
    metacognition: str = ""                                 # 元认知动作选择（信任/重试/独立路径/经验验证）
    anchored: bool = False                                  # dsh：首轮锚定是否完成（晋升）
    anchor_round: int = 0                                   # 锚定完成的轮次
    tool_whitelist: List[str] = field(default_factory=list) # dsh：当前暴露的工具白名单

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
            "dense_track": self.dense_track,
            "bridged_concepts": self.bridged_concepts,
            "metacognition": self.metacognition,
            "anchored": self.anchored,
            "anchor_round": self.anchor_round,
            "tool_whitelist": self.tool_whitelist,
        }


# ---------- dsh 首轮轨迹锚定（P0） ----------
# 首轮只暴露极简工具（白名单），晋升后再解锁完整工具集。
INITIAL_TOOL_WHITELIST = ["read", "search"]
FULL_TOOLSET = ["read", "search", "bash", "edit", "write", "run", "review", "test", "deploy"]


class TrajectoryAnchoring:
    """dsh-anchored-standard 首轮轨迹锚定状态机。

    通过控制首轮的工具暴露，锚定模型推理轨迹方向；检测到首次持久输出后晋升解锁完整工具集。
    """

    def __init__(self, enabled: bool = True, first_round_whitelist: List[str] = None):
        self.enabled = enabled
        self.first_round_whitelist = list(first_round_whitelist or INITIAL_TOOL_WHITELIST)
        self.anchored = False
        self.anchor_round = 0

    def tools_for_round(self, round_idx: int, has_persistent_output: bool = False) -> List[str]:
        """返回本轮应暴露的工具集。

        dsh 规则：首轮（未锚定）只暴露白名单；一旦检测到首次持久输出（晋升条件）即锚定，
        解锁完整工具集。
        """
        if not self.enabled:
            return FULL_TOOLSET
        if not self.anchored:
            if has_persistent_output:
                self.anchored = True
                self.anchor_round = round_idx
                return FULL_TOOLSET
            return list(self.first_round_whitelist)
        return FULL_TOOLSET

    def to_prompt_fragment(self, tools: List[str], anchored: bool) -> str:
        """生成注入本轮的工具可用性指令。"""
        if not self.enabled:
            return ""
        if anchored:
            return "[工具状态] 已晋升：完整工具集可用（read/search/bash/edit/write/run/review/test/deploy）。"
        return f"[工具状态] 首轮锚定阶段：仅暴露 {', '.join(tools)}。先用它们建立推理方向，首次持久输出后解锁全部工具。"


# ---------- 认知控制指令组装 ----------
def build_cognition_system(
    state: CognitionState,
    anchoring: TrajectoryAnchoring,
    round_idx: int,
    anchored: bool,
    tools: List[str],
) -> str:
    """组装认知控制层 System Prompt 片段（注入到 base_system）。"""
    parts = [
        state.to_prompt_fragment(round_idx),
        anchoring.to_prompt_fragment(tools, anchored),
    ]
    return "\n".join(parts)
