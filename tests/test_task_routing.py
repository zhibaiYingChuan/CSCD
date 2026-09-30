"""阶段 1.2 动态路由的本地契约测试。"""

from core.assess import score_task_complexity, select_route


def test_simple_task_uses_fast_route():
    task = {
        "title": "实现 add 函数",
        "description": "实现一个函数，返回两个数的和。",
        "test_cases": [{"input": "1, 2", "output": "3"}],
    }
    assert score_task_complexity(task) <= 3
    assert select_route(task) == "fast"


def test_ambiguous_multi_function_task_uses_deep_route():
    task = {
        "title": "实现异步并发数据处理系统",
        "description": """
        实现多个类和函数，包含异步、并发、线程安全、缓存、文件 IO、错误恢复和状态管理。
        需要设计数据结构，处理超时、取消、重试和多个订阅者，并保持接口兼容。
        """ + " def " * 80,
        "test_cases": [{"input": str(i), "output": str(i)} for i in range(8)],
    }
    assert score_task_complexity(task) >= 7
    assert select_route(task) == "deep"


def test_route_thresholds_are_configurable():
    task = {"description": "实现一个函数并处理输入校验和边界条件，返回稳定结果。", "language": "python", "test_cases": [{"input": "1", "output": "1"}, {"input": "2", "output": "2"}, {"input": "3", "output": "3"}]}
    assert select_route(task, {"routing": {"thresholds": {"fast": 0, "deep": 2}}}) == "standard"


def test_hierarchical_merge_task_is_not_routed_to_fast():
    task = {
        "title": "实现层次化数据作用域合并",
        "description": "实现层次化数据作用域，支持递归合并、作用域覆盖和冲突处理。",
        "test_cases": [{"input": str(i), "output": str(i)} for i in range(5)],
    }
    assert score_task_complexity(task) > 3
    assert select_route(task) == "standard"


def test_route_is_total_and_bounded():
    assert 0 <= score_task_complexity({}) <= 10
    assert select_route({}) in {"fast", "standard", "deep"}
