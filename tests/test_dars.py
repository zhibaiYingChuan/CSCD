import copy

from core.harness import Harness
from core.runtime_state import RuntimeState, RuntimeWorkspace


def test_dars_runs_branches_from_same_checkpoint(tmp_path):
    workspace = RuntimeWorkspace("dars", root=tmp_path / ".cscd")
    harness = Harness(root=tmp_path, workspace=workspace)
    state = RuntimeState(task_id="dars", phase="implement", promoted=True)
    state.changed_files = ["candidate.txt"]
    (tmp_path / "candidate.txt").write_text("base", encoding="utf-8")

    def branch_a(current):
        current.next_action = "A"
        return {"score": 1, "label": "A"}

    def branch_b(current):
        current.next_action = "B"
        return {"score": 3, "label": "B"}

    result = harness.run_branches(state, {"a": branch_a, "b": branch_b}, score=lambda value: value["score"])
    assert result["selected"] == "b"
    assert result["branches"]["a"]["result"]["label"] == "A"
    assert result["branches"]["b"]["result"]["label"] == "B"
    assert state.next_action == "B"


def test_dars_rejects_empty_branches(tmp_path):
    harness = Harness(root=tmp_path, workspace=RuntimeWorkspace("dars", root=tmp_path / ".cscd"))
    state = RuntimeState(task_id="dars", phase="implement", promoted=True)
    try:
        harness.run_branches(state, {}, score=lambda value: 0)
    except ValueError as exc:
        assert "分支" in str(exc)
    else:
        raise AssertionError("空分支必须被拒绝")
