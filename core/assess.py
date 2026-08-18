"""
L3 复杂度评估与推理策略选择（模型无关）
======================================
根据任务类型与问题规模评估复杂度，映射到 Token 预算档位与推理策略。
对齐 protocol.md 中的 Token 预算表。
"""

from typing import Literal
from core.classify import TaskType
from core.jspace_modules import decide_pass_level, PassLevel

Complexity = Literal["simple", "medium", "complex"]
Strategy = Literal["react", "AoT", "GoT", "Hybrid"]

TOKEN_BUDGET: dict[Complexity, int] = {
    "simple": 512,
    "medium": 2048,
    "complex": 8192,
}

STRATEGY_BY_COMPLEXITY: dict[Complexity, Strategy] = {
    "simple": "react",
    "medium": "AoT",
    "complex": "GoT",
}


def assess_complexity(question: str, task_type: TaskType) -> Complexity:
    if task_type == "react":
        return "simple"
    if len(question) > 120 or task_type == "spec":
        return "complex"
    return "medium"


def select_strategy(complexity: Complexity) -> Strategy:
    return STRATEGY_BY_COMPLEXITY[complexity]


def budget_for(complexity: Complexity) -> int:
    return TOKEN_BUDGET[complexity]


def pass_level_for(complexity: Complexity, has_untrusted_input: bool = False) -> PassLevel:
    """
    复杂度 -> J-Space 通行级闸门（fast/full/loop）。
    见 core/jspace_modules.decide_pass_level 的真实闸门定义。
    """
    return decide_pass_level(complexity, has_untrusted_input)
