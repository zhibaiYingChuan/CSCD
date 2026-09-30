from core.routing import RouteConfig, Router


def test_router_selects_three_routes_from_score():
    router = Router(RouteConfig(fast_max=3, deep_min=7))
    assert router.route_for_score(2).name == "fast"
    assert router.route_for_score(5).name == "standard"
    assert router.route_for_score(8).name == "deep"


def test_router_uses_existing_task_complexity_scorer():
    router = Router()
    task = {"title": "层次化递归合并", "description": "scope merge recursive", "language": "python", "test_cases": ["a", "b", "c"]}
    decision = router.select(task)
    assert decision.score >= 0
    assert decision.name in {"fast", "standard", "deep"}
    assert decision.signals
