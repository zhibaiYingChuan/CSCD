from types import SimpleNamespace


def _fake_result():
    return SimpleNamespace(
        reason="结论",
        final_context="结论",
        raw_reason="动作计划",
        summaries=[],
        compress_methods=[],
        task_type="spec",
        complexity="medium",
        strategy="protocol",
        rounds=1,
        planned_rounds=1,
        marks_valid=True,
        missing_marks=[],
        cache_hits=0,
        cache_saved_tokens=0,
        total_completion_tokens=0,
        pass_level="full",
        loaded_modules=["capacity"],
        cognition={"anchored": True},
        ledger={},
        delivery_artifact={"changed_files": ["a.py"]},
        execution_evidence=[{"kind": "run_test", "status": "completed"}],
    )


def test_webui_service_exposes_runtime_evidence(monkeypatch):
    from webui.backend.services.cscd_service import CscdService

    service = CscdService()
    service._engine = SimpleNamespace(run=lambda *args, **kwargs: _fake_result())
    monkeypatch.setattr(service, "ready", lambda: True)
    result = service.reason("任务")

    assert result["delivery_artifact"] == {"changed_files": ["a.py"]}
    assert result["execution_evidence"][0]["kind"] == "run_test"


def test_mcp_result_contract_includes_runtime_evidence(monkeypatch):
    import cscd_mcp_server

    monkeypatch.setattr(cscd_mcp_server, "_make_engine", lambda: SimpleNamespace(
        run=lambda *args, **kwargs: _fake_result()
    ))
    result = cscd_mcp_server.cscd_reason("任务")

    assert result["delivery_artifact"] == {"changed_files": ["a.py"]}
    assert result["execution_evidence"][0]["kind"] == "run_test"
