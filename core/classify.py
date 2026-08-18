"""
L1 任务分类路由（模型无关）
=========================
识别任务类型: spec / react / weak
规则优先，可扩展为模型自分类（weak 时交由 Carrier 在首轮自路由）。

为避免源码中文字面量编码污染导致的匹配失效，中文 spec 信号通过
Unicode 码点（chr）安全构造，英文信号用纯 ASCII 列表匹配。
"""

from typing import Literal

TaskType = Literal["spec", "react", "weak"]

# 英文关键词（spec 触发，统一小写比对，纯 ASCII 无编码风险）
_SPEC_EN = ["design", "implement", "architecture", "system", "compare", "analyze",
            "module", "interface", "contract", "plan", "refactor", "optimize"]

# 中文关键词（spec 触发）：以十六进制码点元组构造，避免字面量编码问题
# 设计 架构 实现 对比 分析 方案 系统 模块 接口 契约 划分
_SPEC_CN_CODEPTS = [
    (0x8BBE, 0x8BA1), (0x67B6, 0x6784), (0x5B9E, 0x73B0), (0x5BF9, 0x6BD4),
    (0x5206, 0x6790), (0x65B9, 0x6848), (0x7CFB, 0x7EDF), (0x6A21, 0x5757),
    (0x63A5, 0x53E3), (0x5951, 0x7EA6), (0x5212, 0x5206),
]

# 计划性意图关键词（强制走 spec 的工程加固，见 README 工程调优记录）
# 设计 计划 架构 实现 规划 spec 设计文档 模块 流程 方案
_SPEC_INTENT_CN_CODEPTS = [
    (0x8BBE, 0x8BA1),               # 设计
    (0x8BA1, 0x5212),               # 计划
    (0x67B6, 0x6784),               # 架构
    (0x5B9E, 0x73B0),               # 实现
    (0x89C4, 0x5212),               # 规划
    (0x8BBE, 0x8BA1, 0x6587, 0x6863),  # 设计文档
    (0x6A21, 0x5757),               # 模块
    (0x6D41, 0x7A0B),               # 流程
    (0x65B9, 0x6848),               # 方案
]
_SPEC_INTENT_EN = ["spec", "design", "plan", "architecture", "implement"]


def _spec_cn() -> list:
    return ["".join(chr(cp) for cp in pair) for pair in _SPEC_CN_CODEPTS]


def _spec_intent_cn() -> list:
    return ["".join(chr(cp) for cp in pair) for pair in _SPEC_INTENT_CN_CODEPTS]


def classify_task(question: str) -> TaskType:
    """
    L1 任务分类（修正版，见 README 工程调优记录）。

    修正动机：原规则 `len(q) < 15 -> react` 基于英文/Token 启发式，对中文极不友好——
    如「实现模块设计」(6字) 这类计划性任务会被错误踢进 react 快通道，导致不加载任何模块，
    违背 spec 应走 full/loop 的设计初衷。

    修正逻辑（意图命中 + 长度兜底）：
      1. 计划性意图关键词命中（设计/计划/架构/实现/规划/spec/模块/流程/方案…）
         -> 强制 spec，无论多短。
      2. 中文长任务（>20字）不直接下结论，交 weak 由模型二次评估，
         至少不会误判 react。
      3. 极简短指令（编译/重启等）才走 react。
    """
    q = question.strip()
    ql = q.lower()

    # 1. 计划性意图关键词命中 -> 强制 spec
    intent_cn = _spec_intent_cn()
    intent_en = _SPEC_INTENT_EN
    if any(k in q for k in intent_cn) or any(k in ql for k in intent_en):
        return "spec"

    # 2. 长度兜底：中文 >20 字交给 weak 二次评估（不直接 react）
    if len(q) > 20:
        return "weak"

    # 3. 极简短指令走 react
    return "react"
