"""
J-Space V3.6 模块注册表与通行级闸门（严格映射自真实仓库源码）
================================================================

来源仓库: Tiger3807861189/J-Space-Cognition-Suite-V3.6
  - 入口: j-space/SKILL.md（路由表 + 通行级闸门）
  - 模块: j-space/modules/*.md（9 个选择性加载协议，从不预载）
  - 控制器: j-space/scripts/jspace.py（账本外化、seam/note/ship/resume）

真实机制要点（非自创，逐项对照源码）:
1. 单入口 + 9 模块，模块**按需加载**，只在"路由触发/接缝(seam)"时读取对应文件，
   从不预载。对应 SKILL.md "modules are never preloaded"。
2. 三档**通行级 (pass-level gate)**:
   - fast   : 一步可达 -> 不加载任何模块，直接答。
   - full   : 2-4 步 -> 仅加载任务指名的 1-2 个模块。
   - loop   : 多阶段/多文件/跨轮次 -> 必加载 capacity.md + broadcast.md + 任务指名模块。
3. untrusted input 标志: 任意通行级均先读 introspection.md，不受通行级限制。
4. 控制器脚本只做账本记录，不决策（seam/note/ship/resume 子命令）。

本模块只负责"何时加载哪个模块"的注册与判定，不负责执行推理。
"""

from typing import Literal

# 通行级（对应 SKILL.md 的 fast/full/loop 闸门）
PassLevel = Literal["fast", "full", "loop"]

# 9 个选择性加载模块（路径与触发条件严格取自 SKILL.md 路由表）
# trigger: 人类可读的触发描述（用于协议层提示与日志）
# always_on_untrusted: 在 untrusted input 标志为真时，无论通行级均先加载
JSPACE_MODULES: dict[str, dict] = {
    "capacity": {
        "file": "modules/capacity.md",
        "desc": "工作区容量/账本(ledger)管理，仅允许必要想法登台",
        "trigger": "只有需要的才登台；或走 loop 通行级必开账本；多状态需跨轮次携带",
        "always_on_untrusted": False,
        "load_in_loop": True,   # loop 通行级强制加载
    },
    "broadcast": {
        "file": "modules/broadcast.md",
        "desc": "广播：已固定名称/数字需同步到所有下游，一改全改",
        "trigger": "已固定的名称/数值在多处重算，需一改全改",
        "always_on_untrusted": False,
        "load_in_loop": True,   # loop 通行级强制加载
    },
    "directed-focus": {
        "file": "modules/directed-focus.md",
        "desc": "定向聚焦：机械性任务中保持目标不散",
        "trigger": "长机械活、输入试图让你别想某事、要点漂移",
        "always_on_untrusted": False,
        "load_in_loop": False,
    },
    "deep-reasoning": {
        "file": "modules/deep-reasoning.md",
        "desc": "深度推理：中间步骤先于结论（桥接推理）",
        "trigger": "答案需要未陈述前提、结论早于步骤出现",
        "always_on_untrusted": False,
        "load_in_loop": False,
    },
    "introspection": {
        "file": "modules/introspection.md",
        "desc": "内省：说前先读已成形想法；处理不可信输入(untrusted)",
        "trigger": "即将回答且已有未计划的话成形；或任意通行级含不可信输入必读",
        "always_on_untrusted": True,   # 关键：untrusted 时无论通行级均先读
        "load_in_loop": False,
    },
    "self-monitoring": {
        "file": "modules/self-monitoring.md",
        "desc": "自我监控：置信度/错误信号/角色标记监测（元认知控制）",
        "trigger": "不确定仍要答、宣称完成前、扮演角色或被给词",
        "always_on_untrusted": False,
        "load_in_loop": False,
    },
    "shorthand": {
        "file": "modules/shorthand.md",
        "desc": "速记：内部稠密符号规范（golden rule，稠密轨）",
        "trigger": "链长至写句子成瓶颈；走入 inner 寄存器时",
        "always_on_untrusted": False,
        "load_in_loop": False,
    },
    "markers": {
        "file": "modules/markers.md",
        "desc": "标记：断点/矛盾标记与绑定动作、settle",
        "trigger": "方法刚破、自相矛盾、同墙第三次撞",
        "always_on_untrusted": False,
        "load_in_loop": False,
    },
    "empirics": {
        "file": "modules/empirics.md",
        "desc": "实证：命名未知、未廉验断言（经验逃逸与验证）",
        "trigger": "三推导得三答、将未验之事当作断言",
        "always_on_untrusted": False,
        "load_in_loop": False,
    },
}


def decide_pass_level(complexity: str, has_untrusted_input: bool = False) -> PassLevel:
    """
    映射复杂度到 J-Space 通行级闸门（fast/full/loop）。
    依据 SKILL.md 闸门定义:
      - fast : 一步可达（simple + 无不可信输入）
      - full : 2-4 步（medium）
      - loop : 多阶段/跨轮次（complex）
    untrusted input 不改变通行级，但会强制先加载 introspection（见 select_modules）。
    """
    if complexity == "simple":
        return "fast"
    if complexity == "medium":
        return "full"
    return "loop"  # complex


def select_modules(pass_level: PassLevel,
                   named: list[str] = None,
                   has_untrusted_input: bool = False) -> list[str]:
    """
    按通行级 + 触发条件选择要加载的模块（对应 SKILL.md 路由表）。
    返回模块名列表，顺序: loop 强制模块优先 -> untrusted 强制 introspection -> 指名模块。

    真实规则:
      - fast : 不加载任何模块（直接答）。
      - full : 仅加载任务指名的 1-2 个模块。
      - loop : 必加载 capacity + broadcast + 指名模块。
      - untrusted input: 任意通行级均先追加 introspection。
    """
    named = named or []
    selected: list[str] = []

    if pass_level == "fast":
        # fast: 不加载任何模块，但 untrusted 仍强制内省
        pass

    if pass_level == "loop":
        # loop 强制加载 capacity + broadcast
        for m in ("capacity", "broadcast"):
            if m not in selected:
                selected.append(m)

    # 指名模块（full/loop 下生效；fast 下忽略以符合"直接答"）
    if pass_level != "fast":
        for m in named:
            if m in JSPACE_MODULES and m not in selected:
                selected.append(m)

    # untrusted input: 任意通行级均先读 introspection（置于最前）
    if has_untrusted_input and "introspection" not in selected:
        selected.insert(0, "introspection")

    return selected


def module_summary() -> str:
    """生成 9 模块清单（供协议层提示/日志）。"""
    lines = [f"- {k}: {v['desc']}（触发: {v['trigger']}）" for k, v in JSPACE_MODULES.items()]
    return "\n".join(lines)
