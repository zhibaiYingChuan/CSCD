import json

from core.runtime_state import RuntimeState, RuntimeWorkspace


def _read_trace(root):
    return [json.loads(line) for line in (root / "traces" / "task.jsonl").read_text(encoding="utf-8").splitlines()]


def test_replay_restores_rollback_phase(tmp_path):
    workspace = RuntimeWorkspace("demo", root=tmp_path / ".cscd")
    state = RuntimeState(task_id="demo", phase="implement", next_action="继续实现")
    workspace.record(state, "checkpoint", {"point": "p1"})
    state.phase = "verify"
    state.next_action = "修复失败"
    workspace.record(state, "rollback", {"point": "p1"})

    restored = workspace.resume()
    assert restored.phase == "implement"
    assert restored.next_action == "继续实现"


def test_workspace_persists_state_trace_and_artifact(tmp_path):
    state = RuntimeState(
        task_id="demo/task",
        goal="完成一个功能",
        done_when=["测试通过"],
        verified=["入口文件已确认"],
        open_questions=["是否需要兼容旧 API"],
        next_action="读取实现文件",
        delivery_artifact={"code_blocks": ["print('ok')"]},
        execution_evidence=[{"kind": "test", "status": "passed"}],
    )
    workspace = RuntimeWorkspace(state.task_id, root=tmp_path / ".cscd")

    workspace.record(state, "artifact")

    assert (tmp_path / ".cscd" / "workspace" / "goal.md").read_text(encoding="utf-8").startswith("# 目标")
    assert "入口文件已确认" in (tmp_path / ".cscd" / "workspace" / "verified.md").read_text(encoding="utf-8")
    assert workspace.trace_file.exists()
    artifact = json.loads(workspace.artifact_file.read_text(encoding="utf-8"))
    assert artifact["delivery_artifact"]["code_blocks"] == ["print('ok')"]
    assert artifact["execution_evidence"][0]["status"] == "passed"


def test_workspace_replays_persistent_events_and_phase(tmp_path):
    state = RuntimeState(task_id="demo")
    workspace = RuntimeWorkspace(state.task_id, root=tmp_path / ".cscd")

    workspace.record(state, "anchor_started")
    workspace.record(state, "anchor_completed")
    workspace.record(state, "first_read")
    workspace.record(state, "promoted")
    workspace.record(state, "first_edit", {"changed_files": ["src/main.py"]})
    workspace.record(state, "first_test", {"test_commands": ["pytest"]})
    workspace.record(state, "checkpoint", {"point": "before-ship"})

    restored = workspace.replay()
    assert restored is not None
    assert restored.phase == "verify"
    assert restored.promoted is True
    assert restored.promotion_state == "promoted"
    assert restored.rollback_points == ["before-ship"]
    assert workspace.trace_file.name == "task.jsonl"
    assert workspace.artifact_file.name == "tests.json"
    assert workspace.patch_dir.is_dir()


def test_phase_controls_allowed_tools():
    """各阶段正确控制可用工具集。

    机制1 动态锚定：需要 first_read 事件触发 promoted 后，才能使用阶段完成动作。
    """
    state = RuntimeState(task_id="demo")
    # 初始状态：未晋升，只暴露 read/search
    assert state.allowed_tools() == ["read", "search"]
    # anchor_completed 设置 promotion_state = "eligible" 但不触发 promoted
    state.apply_event("anchor_completed")
    assert state.allowed_tools() == ["read", "search"], "anchor_completed 后仍只有 read/search"
    # first_read 触发 promoted（动态锚定）
    state.apply_event("first_read")
    assert "exploration_completed" in state.allowed_tools(), "promoted 后应包含 exploration_completed"
    state.apply_event("exploration_completed")
    assert "edit" in state.allowed_tools()
    state.apply_event("first_edit")
    state.apply_event("implementation_completed")
    assert "run_test" in state.allowed_tools()
    state.apply_event("first_test")
    state.apply_event("verification_completed")
    assert "ship" in state.allowed_tools()


def test_anchor_promotion_requires_real_read(tmp_path):
    from core.harness import Harness

    workspace = RuntimeWorkspace("demo", root=tmp_path / ".cscd")
    harness = Harness(root=tmp_path, workspace=workspace)
    state = RuntimeState(task_id="demo")

    denied = harness.run_action_plan(state, '{"action":"anchor_completed"}')
    assert denied[0]["ok"] is False
    assert state.promoted is False

    (tmp_path / "input.txt").write_text("事实", encoding="utf-8")
    result = harness.run_action_plan(state, '{"actions":[{"action":"read","path":"input.txt"},{"action":"anchor_completed"}]}')
    assert all(item["ok"] for item in result)
    assert state.promoted is True
    assert state.phase == "explore"


def test_state_extracts_minimal_runtime_fields():
    state = RuntimeState(task_id="demo")
    state.update_from_text(
        "目标：修复路由\n已验证：现有测试可运行\n开放问题：是否保留旧参数\n下一步：运行测试\n修改文件：src/routing.py"
    )

    assert state.goal == "修复路由"
    assert state.verified == ["现有测试可运行"]
    assert state.open_questions == ["是否保留旧参数"]
    assert state.next_action == "运行测试"
    assert state.changed_files == ["src/routing.py"]


class _MinimalCarrier:
    def __init__(self, output: str):
        self.output = output
        self.last_usage = {"completion_tokens": 0}

    def anchor(self, question: str) -> str:
        return "anchor"

    def reason(self, prompt: str, system: str = None, budget: int = 2048) -> str:
        return self.output


def test_default_run_does_not_use_legacy_marks_fallback(tmp_path):
    from core.cscd import CscdEngine

    engine = CscdEngine(_MinimalCarrier("<DECOMPOSE>旧文本</DECOMPOSE>"), config={
        "simple_shortcut_to_baseline": False,
        "runtime_root": str(tmp_path),
        "runtime_dir": str(tmp_path / ".cscd"),
        "legacy_marks_fallback": False,
    })
    result = engine.run("执行任务", task_id="legacy-off", persist_ledger=False)
    observations = [item for item in result.execution_evidence if item.get("kind") == "model_observation"]
    assert observations == []
    # 四阶标记的「审计」与「阻断」自 2026-09-02 起解耦：
    # 审计始终执行（marks_valid/missing_marks 是对外承诺的可追溯性字段，不得伪造），
    # legacy_marks_fallback 只决定是否兼容旧输出，不再决定"要不要校验"。
    # 故此处 missing_marks 必须如实报告缺失的三段，而不是像解耦前那样恒为空。
    assert set(result.missing_marks) == {"CLASSIFY", "SELECT", "COMBINE"}


def test_baseline_shortcut_does_not_fake_promotion(tmp_path):
    from core.cscd import CscdEngine

    class BaselineCarrier(_MinimalCarrier):
        def reason_baseline(self, question: str) -> str:
            return "基线回答"

    engine = CscdEngine(BaselineCarrier("基线回答"), config={
        "simple_shortcut_to_baseline": True,
        "runtime_root": str(tmp_path),
        "runtime_dir": str(tmp_path / ".cscd"),
    })
    result = engine.run("简单问题", task_id="baseline", persist_ledger=False)
    events = [item.get("event") for item in _read_trace(tmp_path / ".cscd")]
    assert "anchor_completed" not in events
    assert "ship" not in events
    assert "baseline_shortcut" in events


def test_run_failure_evidence_blocks_ship_and_ledger(tmp_path):
    from core.cscd import CscdEngine

    class FailingCarrier(_MinimalCarrier):
        def __init__(self):
            super().__init__('{"actions":[{"action":"run_test","command":"python -c \\\"raise SystemExit(1)\\\""}]}')

    engine = CscdEngine(FailingCarrier(), config={
        "simple_shortcut_to_baseline": False,
        "runtime_root": str(tmp_path),
        "runtime_dir": str(tmp_path / ".cscd"),
        "runtime_ledger": True,
    })
    result = engine.run("执行失败测试", task_id="failed", persist_ledger=True)

    assert any(item.get("kind") == "ship_blocked" for item in result.execution_evidence)
    ledger_file = tmp_path / ".cscd" / "ledger" / "failed.jsonl"
    if ledger_file.exists():
        assert '"kind": "ship"' not in ledger_file.read_text(encoding="utf-8")


def test_run_requires_evidence_before_ship(tmp_path):
    from core.cscd import CscdEngine

    engine = CscdEngine(_MinimalCarrier('{"actions":[{"action":"read","path":"input.txt"}]}'), config={
        "simple_shortcut_to_baseline": False,
        "runtime_root": str(tmp_path),
        "runtime_dir": str(tmp_path / ".cscd"),
    })
    (tmp_path / "input.txt").write_text("内容", encoding="utf-8")

    result = engine.run("读取文件", task_id="demo", persist_ledger=False)

    assert result.reason
    assert result.final_context
    assert any(item.get("kind") == "read" for item in result.execution_evidence)
    assert any(item.get("event") == "first_read" for item in _read_trace(tmp_path / ".cscd"))
