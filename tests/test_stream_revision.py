from core.revision import RevisionController


def test_stream_revision_checks_each_generated_artifact():
    calls = []

    def generate(prompt):
        calls.append(prompt)
        return f"artifact-{len(calls)}"

    checks = []
    controller = RevisionController(
        generate=generate,
        verify=lambda artifact: {"available": True, "passed": artifact == "artifact-2", "error": "未通过"},
    )
    result = controller.run_stream("task", inspect=lambda artifact: checks.append(artifact) or {"ok": True}, max_iterations=2)

    assert result.status == "passed"
    assert checks == ["artifact-1", "artifact-2"]
    assert any(stage["stage"] == "stream_inspection" for stage in result.stages)


def test_stream_revision_stops_when_intermediate_inspection_rejects():
    controller = RevisionController(generate=lambda prompt: "artifact", verify=lambda artifact: {"passed": True})
    result = controller.run_stream("task", inspect=lambda artifact: {"ok": False, "error": "格式不完整"}, max_iterations=2)
    assert result.status == "inspection_failed"
    assert result.revision_count == 0
