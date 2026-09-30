"""RoutingGen 风格的任务路径调度模块。"""

from __future__ import annotations

from dataclasses import dataclass
from core.assess import score_task_complexity


@dataclass(frozen=True)
class RouteConfig:
    fast_max: int = 3
    deep_min: int = 7


@dataclass(frozen=True)
class RouteDecision:
    name: str
    score: int
    signals: tuple[str, ...] = ()


class Router:
    """根据现有复杂度评分选择 Fast/Standard/Deep。"""

    def __init__(self, config: RouteConfig | None = None):
        self.config = config or RouteConfig()

    def route_for_score(self, score: int, signals: tuple[str, ...] = ()) -> RouteDecision:
        if score <= self.config.fast_max:
            name = "fast"
        elif score >= self.config.deep_min:
            name = "deep"
        else:
            name = "standard"
        return RouteDecision(name=name, score=score, signals=signals)

    def select(self, task: dict) -> RouteDecision:
        score = score_task_complexity(task)
        text = " ".join(str(task.get(key, "")) for key in ("title", "description"))
        signals = tuple(signal for signal in ("层次", "递归", "作用域", "合并", "hierarchical", "recursive", "scope", "merge") if signal.lower() in text.lower())
        return self.route_for_score(score, signals)
