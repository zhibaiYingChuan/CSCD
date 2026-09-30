"""
L3 复杂度评估与推理策略选择（模型无关）
======================================
根据任务类型与问题规模评估复杂度，映射到 Token 预算档位与推理策略。
对齐 protocol.md 中的 Token 预算表。
"""

import re
from typing import Literal
from core.classify import TaskType

Route = Literal["fast", "standard", "deep"]

DEFAULT_ROUTING_THRESHOLDS = {"fast": 3, "deep": 7}
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


def score_task_complexity(task: dict) -> int:
    """根据任务可观察特征返回 0-10 的复杂度评分。"""
    text = " ".join(
        str(task.get(key, ""))
        for key in ("title", "description", "language")
    )
    score = 0
    length = len(text)
    if length > 500:
        score += 3
    elif length > 200:
        score += 2
    elif length > 50:
        score += 1

    symbols = re.findall(r"\b(?:def|class|function|func|fn|struct|interface|type)\s+\w+", text, re.IGNORECASE)
    symbol_count = len(set(symbols))
    score += 3 if symbol_count > 5 else 2 if symbol_count >= 4 else 1 if symbol_count >= 2 else 0

    complexity_signals = (
        "async", "异步", "并发", "线程", "thread", "lock", "缓存", "cache",
        "超时", "timeout", "重试", "retry", "取消", "cancel", "文件", "file",
        "状态管理", "state management", "层次", "递归", "作用域", "合并",
        "hierarchical", "recursive", "scope", "merge",
    )
    score += min(3, sum(signal.lower() in text.lower() for signal in complexity_signals))

    test_count = len(task.get("test_cases") or [])
    score += 2 if test_count > 5 else 1 if test_count >= 3 else 0
    return min(score, 10)


def select_route(task: dict, config: dict | None = None) -> Route:
    """按复杂度阈值选择 Fast、Standard 或 Deep 路径。

    实际决策统一由 core.routing.Router 承担——阈值边界只应存在一处定义，
    否则两份实现迟早漂移。此处仅保留薄封装以兼容既有调用方。
    """
    from core.routing import RouteConfig, Router

    thresholds = dict(DEFAULT_ROUTING_THRESHOLDS)
    if config:
        thresholds.update(config.get("routing", {}).get("thresholds", {}))
    router = Router(RouteConfig(
        fast_max=int(thresholds["fast"]),
        deep_min=int(thresholds["deep"]),
    ))
    return router.select(task).name


def budget_for(complexity: Complexity) -> int:
    return TOKEN_BUDGET[complexity]


def pass_level_for(complexity: Complexity, has_untrusted_input: bool = False) -> PassLevel:
    """
    复杂度 -> J-Space 通行级闸门（fast/full/loop）。
    见 core/jspace_modules.decide_pass_level 的真实闸门定义。
    """
    return decide_pass_level(complexity, has_untrusted_input)
