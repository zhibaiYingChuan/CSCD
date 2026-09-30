"""运行时层垂直切片契约测试。"""

from core.harness import Harness
from core.runtime_state import RuntimeState, RuntimeWorkspace


def test_run_test_requires_modified_files(tmp_path):
    workspace = RuntimeWorkspace("gate", root=tmp_path / ".cscd")
    harness = Harness(root=tmp_path, workspace=workspace)
    state = RuntimeState(task_id="gate", phase="verify")

    result = harness.run_action_plan(state, '{"action":"run_test","command":"python -c \\"print(1)\\""}')

    assert result[0]["ok"] is False
    assert "修改" in result[0]["error"]
    assert result[0]["side_effect"] is False


def test_build_context_exposes_only_phase_tools(tmp_path):
    from core.harness import build_context

    state = RuntimeState(task_id="context", phase="anchor")
    context = build_context(state)
    assert context["tools"] == ["read", "search"]

    state.phase = "verify"
    state.test_results.append('{"ok":false,"stderr":"失败"}')
    context = build_context(state)
    assert "run_test" in context["tools"]
    assert "失败" in context["context"]


def test_build_context_uses_verified_and_focus_for_implementation(tmp_path):
    from core.harness import build_context

    state = RuntimeState(task_id="context", phase="implement", promoted=True)
    state.verified.append("入口已确认")
    state.next_action = "修改实现"
    context = build_context(state)
    assert "write" in context["tools"]
    assert "入口已确认" in context["context"]
    assert "修改实现" in context["context"]
