"""ReVeal 风格反馈修订控制器契约测试。"""

from core.revision import RevisionController


def test_stops_after_verified_artifact():
    calls = []

    def generate(prompt):
        calls.append(prompt)
        return "good"

    controller = RevisionController(generate=generate, verify=lambda artifact: {"passed": True})
    result = controller.run("task", max_revisions=2)

    assert result.status == "passed"
    assert result.revision_count == 0
    assert len(calls) == 1
    assert result.stages[0]["stage"] == "initial"


def test_injects_real_failure_evidence_before_revision():
    prompts = []

    def generate(prompt):
        prompts.append(prompt)
        return "bad" if len(prompts) == 1 else "fixed"

    def verify(artifact):
        return {"passed": artifact == "fixed", "error": "assert expected 2 got 1"}

    controller = RevisionController(generate=generate, verify=verify)
    result = controller.run("task", max_revisions=1)

    assert result.status == "passed"
    assert result.revision_count == 1
    assert "assert expected 2 got 1" in prompts[1]
    assert result.stages[1]["stage"] == "feedback"
    assert result.stages[2]["stage"] == "revision"


def test_does_not_retry_when_verifier_unavailable():
    calls = []
    controller = RevisionController(
        generate=lambda prompt: calls.append(prompt) or "candidate",
        verify=lambda artifact: {"available": False, "passed": None, "error": "no verifier"},
    )

    result = controller.run("task", max_revisions=2)

    assert result.status == "not_verifiable"
    assert result.revision_count == 0
    assert len(calls) == 1


def test_failed_revision_returns_auditable_result():
    controller = RevisionController(
        generate=lambda prompt: "bad",
        verify=lambda artifact: {"available": True, "passed": False, "error": "NameError: missing"},
    )

    result = controller.run("task", max_revisions=1)

    assert result.status == "revision_failed"
    assert result.revision_count == 1
    assert result.feedback["error"] == "NameError: missing"
