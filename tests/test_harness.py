import json

from core.harness import Harness
from core.runtime_state import RuntimeState, RuntimeWorkspace


def make_harness(tmp_path, task_id="demo"):
    workspace = RuntimeWorkspace(task_id, root=tmp_path / ".cscd")
    return Harness(root=tmp_path, workspace=workspace), workspace


def test_harness_revision_loop_records_feedback_trace(tmp_path):
    from core.revision import RevisionController

    harness, workspace = make_harness(tmp_path)
    state = RuntimeState(task_id="revision", phase="implement", promoted=True)
    calls = []

    def generate(prompt):
        calls.append(prompt)
        return "bad" if len(calls) == 1 else "fixed"

    controller = RevisionController(
        generate=generate,
        verify=lambda artifact: {"available": True, "passed": artifact == "fixed", "error": "断言失败"},
    )
    result = harness.run_revision(state, controller, "实现任务", max_revisions=1)

    assert result.status == "passed"
    assert result.revision_count == 1
    assert state.delivery_artifact["status"] == "passed"
    records = [json.loads(line) for line in workspace.trace_file.read_text(encoding="utf-8").splitlines()]
    assert any(record["event"] == "revision_feedback" for record in records)
    assert any(record["event"] == "revision_completed" for record in records)


def test_stage_allowlist_denies_without_side_effect(tmp_path):
    harness, workspace = make_harness(tmp_path)
    state = RuntimeState(task_id="demo")
    result = harness.run_action_plan(state, '{"action":"write","path":"x.txt","content":"bad"}')
    assert result[0]["ok"] is False
    assert not (tmp_path / "x.txt").exists()
    assert state.execution_evidence[-1]["kind"] == "action_denied"
    assert workspace.trace_file.exists()


def test_read_and_search(tmp_path):
    (tmp_path / "a.txt").write_text("needle here", encoding="utf-8")
    harness, _ = make_harness(tmp_path)
    state = RuntimeState(task_id="demo")
    result = harness.run_action_plan(state, json.dumps({"actions": [
        {"action": "read", "path": "a.txt"},
        {"action": "search", "query": "needle"},
    ]}))
    assert result[0]["ok"] and result[0]["result"]["content"] == "needle here"
    assert result[1]["result"]["matches"] == ["a.txt"]


def test_write_edit_and_changed_files(tmp_path):
    harness, _ = make_harness(tmp_path)
    state = RuntimeState(task_id="demo", phase="implement")
    result = harness.run_action_plan(state, json.dumps({"actions": [
        {"action": "write", "path": "a.txt", "content": "old"},
        {"action": "edit", "path": "a.txt", "old": "old", "new": "new"},
    ]}))
    assert all(item["ok"] for item in result)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "new"
    assert state.changed_files == ["a.txt"]


def test_run_test_checkpoint_and_rollback(tmp_path):
    harness, workspace = make_harness(tmp_path)
    state = RuntimeState(task_id="demo", phase="implement")
    harness.run_action_plan(state, '{"action":"write","path":"a.txt","content":"before"}')
    state.apply_event("first_test")
    result = harness.run_action_plan(state, json.dumps({"actions": [
        {"action": "run_test", "command": "python -c \"print(1)\""},
    ]}))
    assert result[0]["result"]["returncode"] == 0
    assert state.test_commands
    state.set_phase("ship")
    harness.run_action_plan(state, json.dumps({"action": "checkpoint", "point": "p1"}))
    (tmp_path / "a.txt").write_text("after", encoding="utf-8")
    result = harness.run_action_plan(state, json.dumps({"action": "rollback", "point": "p1"}))
    assert result[0]["ok"]
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "before"
    assert "p1" in state.rollback_points
    assert "checkpoint" in workspace.trace_file.read_text(encoding="utf-8")


def test_rollback_restores_runtime_state_and_keeps_audit(tmp_path):
    harness, workspace = make_harness(tmp_path)
    state = RuntimeState(task_id="demo", phase="implement", next_action="继续实现")
    harness.run_action_plan(state, '{"action":"write","path":"a.txt","content":"before"}')
    state.set_phase("ship")
    state.next_action = "核对交付"
    result = harness.run_action_plan(state, '{"action":"checkpoint","point":"state-point"}')
    assert result[0]["ok"]

    (tmp_path / "a.txt").write_text("after", encoding="utf-8")
    state.set_phase("verify")
    state.next_action = "修复失败"
    result = harness.run_action_plan(state, '{"action":"rollback","point":"state-point"}')

    assert result[0]["ok"]
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "before"
    assert state.phase == "ship"
    assert state.next_action == "核对交付"
    records = [json.loads(line) for line in workspace.trace_file.read_text(encoding="utf-8").splitlines()]
    assert records[-1]["event"] == "rollback"
    assert records[-1]["payload"]["kind"] == "rollback"


def test_rollback_loads_persisted_checkpoint_across_harness_instances(tmp_path):
    harness, workspace = make_harness(tmp_path)
    state = RuntimeState(task_id="demo", phase="implement", next_action="继续实现")
    harness.run_action_plan(state, '{"action":"write","path":"a.txt","content":"before"}')
    state.set_phase("ship")
    state.next_action = "核对交付"
    result = harness.run_action_plan(state, '{"action":"checkpoint","point":"disk-point"}')
    assert result[0]["ok"]

    (tmp_path / "a.txt").write_text("after", encoding="utf-8")
    restarted_harness = Harness(root=tmp_path, workspace=workspace)
    state.phase = "verify"
    result = restarted_harness.run_action_plan(state, '{"action":"rollback","point":"disk-point"}')

    assert result[0]["ok"]
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "before"
    assert state.phase == "ship"
    assert state.next_action == "核对交付"
    assert (workspace.checkpoint_dir / "disk-point.json").exists()


def test_run_test_rejects_shell_chaining(tmp_path):
    harness, _ = make_harness(tmp_path)
    state = RuntimeState(task_id="demo", phase="verify")
    result = harness.run_action_plan(state, '{"action":"run_test","command":"python -c \\\"print(1)\\\" && echo unsafe"}')
    assert result[0]["ok"] is False
    assert "shell" in result[0]["error"].lower() or "命令" in result[0]["error"]


def test_natural_language_plan_and_invalid_action(tmp_path):
    harness, _ = make_harness(tmp_path)
    state = RuntimeState(task_id="demo")
    (tmp_path / "a.py").write_text("ok", encoding="utf-8")
    result = harness.run_action_plan(state, "读取文件 a.py")
    assert result[0]["ok"]
    result = harness.run_action_plan(state, '{"action":"delete","path":"a.py"}')
    assert result[0]["ok"] is False
    assert (tmp_path / "a.py").exists()


def test_workspace_events_are_persisted(tmp_path):
    harness, workspace = make_harness(tmp_path)
    state = RuntimeState(task_id="demo", phase="implement")
    harness.run_action_plan(state, '{"action":"write","path":"x.txt","content":"x"}')
    records = [json.loads(line) for line in workspace.trace_file.read_text(encoding="utf-8").splitlines()]
    assert records[-1]["event"] == "first_edit"
    assert records[-1]["payload"]["kind"] == "write"


def test_cross_process_ship_block_then_resume_after_passing_test(tmp_path):
    harness, workspace = make_harness(tmp_path)
    state = RuntimeState(task_id="demo", phase="verify", next_action="运行验证")
    result = harness.run_action_plan(state, '{"action":"ship"}')
    assert result[0]["ok"] is False

    harness.run_action_plan(state, '{"action":"checkpoint","point":"before-ship"}')
    state.phase = "ship"
    restarted = Harness(root=tmp_path, workspace=workspace)
    blocked = restarted.run_action_plan(state, '{"action":"ship"}')
    assert blocked[0]["ok"] is False

    state = RuntimeState.from_dict(workspace.load_checkpoint("before-ship")["state"].to_dict())
    state.phase = "verify"
    state.test_results.append('{"command":"pytest","returncode":0,"ok":true}')
    verified = restarted.run_action_plan(state, '{"action":"verification_completed"}')
    assert verified[0]["ok"] is True
    state.phase = "ship"
    shipped = restarted.run_action_plan(state, '{"action":"ship"}')
    assert shipped[0]["ok"] is True


def test_run_loop_replans_after_empty_plan(tmp_path):
    harness, workspace = make_harness(tmp_path)
    state = RuntimeState(task_id="demo")
    plans = ["", '{"action":"search","query":"needle"}']
    calls = []

    def planner(current_state, history):
        calls.append(len(history))
        return plans[len(history)]

    history = harness.run_loop(state, planner, max_steps=2)
    assert len(history) == 2
    assert history[0]["failure"]["kind"] == "action_planning_failed"
    assert history[1]["results"][0]["ok"] is True
    events = [json.loads(line)["event"] for line in workspace.trace_file.read_text(encoding="utf-8").splitlines()]
    assert "action_planning_failed" in events


def test_run_loop_replans_after_action_failure(tmp_path):
    harness, workspace = make_harness(tmp_path)
    state = RuntimeState(task_id="demo")
    plans = [
        '{"action":"read","path":"missing.txt"}',
        '{"action":"search","query":"needle"}',
    ]

    def planner(current_state, history):
        return plans[len(history)]

    history = harness.run_loop(state, planner, max_steps=2)
    assert history[0]["results"][0]["ok"] is False
    assert history[0]["recovery"]["kind"] == "action_recovery_requested"
    assert history[1]["results"][0]["ok"] is True
    events = [json.loads(line)["event"] for line in workspace.trace_file.read_text(encoding="utf-8").splitlines()]
    assert "action_recovery_requested" in events


def test_run_loop_drives_planner_to_ship(tmp_path):
    harness, workspace = make_harness(tmp_path)
    state = RuntimeState(task_id="demo")
    plans = [
        '{"action":"search","query":"missing"}',
        '{"action":"exploration_completed"}',
        '{"action":"write","path":"x.txt","content":"ok"}',
        '{"action":"implementation_completed"}',
        '{"action":"run_test","command":"python -c \\\"print(1)\\\""}',
        '{"action":"verification_completed"}',
        '{"action":"ship"}',
    ]

    def planner(current_state, history):
        assert current_state is state
        return plans[len(history)]

    history = harness.run_loop(state, planner)
    assert len(history) == len(plans)
    assert state.phase == "ship"
    assert (tmp_path / "x.txt").read_text(encoding="utf-8") == "ok"
    events = [json.loads(line)["event"] for line in workspace.trace_file.read_text(encoding="utf-8").splitlines()]
    assert "action_planned" in events
    assert events[-1] == "ship"


def test_xml_legacy_parse_fallback():
    """XML 标签作为兼容回退，能解析为动作计划。"""
    actions = Harness.parse_plan("<read>src/app.py</read>")
    assert actions == [{"action": "read", "path": "src/app.py"}]

    actions = Harness.parse_plan("<run_test>pytest -q</run_test>")
    assert actions == [{"action": "run_test", "command": "pytest -q"}]

    actions = Harness.parse_plan("<anchor_completed/>")
    assert actions == [{"action": "anchor_completed"}]

    actions = Harness.parse_plan("<ship></ship>")
    assert actions == [{"action": "ship"}]


def test_ship_rejected_without_verification(tmp_path):
    """ship 在缺少测试结果或验证证据时被拒绝。"""
    harness, _ = make_harness(tmp_path)
    state = RuntimeState(task_id="demo")

    result = harness.run_action_plan(state, '{"action":"ship"}')
    assert result[0]["ok"] is False

    state.apply_event("anchor_completed", {})
    state.apply_event("exploration_completed", {})
    state.apply_event("implementation_completed", {})
    state.phase = "verify"
    result = harness.run_action_plan(state, '{"action":"verification_completed"}')
    assert result[0]["ok"] is False
    result = harness.run_action_plan(state, '{"action":"ship"}')
    assert result[0]["ok"] is False

    state.test_results.append('{"command":"python -m pytest","returncode":0,"ok":true}')
    result = harness.run_action_plan(state, '{"action":"verification_completed"}')
    assert result[0]["ok"] is True
    state.phase = "ship"
    result = harness.run_action_plan(state, '{"action":"ship"}')
    assert result[0]["ok"] is True


def test_json_priority_over_xml():
    """JSON 动作计划优先于 XML 兼容格式。"""
    text = '{"actions":[{"action":"read","path":"a.txt"}]}<read>b.txt</read>'
    actions = Harness.parse_plan(text)
    assert actions == [{"action": "read", "path": "a.txt"}]


def test_plan_and_xml_mix_still_prefers_actions(tmp_path):
    """动作计划与四阶标记混杂时，仍优先执行动作计划。"""
    harness, _ = make_harness(tmp_path)
    (tmp_path / "a.txt").write_text("content", encoding="utf-8")
    state = RuntimeState(task_id="demo")
    state.phase = "anchor"
    mixed = '{"actions":[{"action":"read","path":"a.txt"}]}<DECOMPOSE>1. x</DECOMPOSE>'
    results = harness.run_action_plan(state, mixed)
    assert results[0]["ok"] is True
    assert results[0]["result"]["content"] == "content"
