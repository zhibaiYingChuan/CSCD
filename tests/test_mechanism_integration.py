"""集成机制实际调用证据测试。"""

import json

from core.harness import Harness
from core.revision import RevisionController
from core.runtime_state import RuntimeState, RuntimeWorkspace


def test_stream_revision_and_dars_write_trigger_evidence(tmp_path):
    workspace = RuntimeWorkspace("mechanisms", root=tmp_path / ".cscd")
    harness = Harness(root=tmp_path, workspace=workspace)
    state = RuntimeState(task_id="mechanisms", phase="implement", promoted=True)
    generated = iter(["bad", "good"])
    controller = RevisionController(
        generate=lambda prompt: next(generated),
        verify=lambda artifact: {"available": True, "passed": artifact == "good", "error": "行为失败"},
    )

    revision = controller.run_stream("task", inspect=lambda artifact: {"ok": True}, max_iterations=2)
    revision_attempts = iter(["bad", "good"])
    revision_controller = RevisionController(
        generate=lambda prompt: next(revision_attempts),
        verify=lambda artifact: {"available": True, "passed": artifact == "good", "error": "行为失败"},
    )
    harness.run_revision(state, revision_controller, "task", max_revisions=1)
    branch = harness.run_branches(
        state,
        {"a": lambda branch_state: {"score": 1}, "b": lambda branch_state: {"score": 2}},
        score=lambda result: result["score"],
    )

    assert any(stage["stage"] == "stream_inspection" for stage in revision.stages)
    assert branch["selected"] == "b"
    records = [json.loads(line) for line in workspace.trace_file.read_text(encoding="utf-8").splitlines()]
    assert any(record["event"] == "revision_feedback" for record in records)
    assert any(record["event"] == "branches_evaluated" for record in records)
