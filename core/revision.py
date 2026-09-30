"""基于真实验证反馈的可插拔代码修订控制器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class RevisionResult:
    """一次反馈修订闭环的完整审计结果。"""

    status: str
    initial_artifact: Any = None
    revised_artifact: Any = None
    feedback: dict[str, Any] | None = None
    revision_count: int = 0
    stages: list[dict[str, Any]] = field(default_factory=list)


class RevisionController:
    """执行生成→真实验证→失败反馈→修订，直到通过或达到上限。"""

    def __init__(
        self,
        generate: Callable[[str], Any],
        verify: Callable[[Any], dict[str, Any]],
        build_feedback: Callable[[Any, dict[str, Any]], str] | None = None,
    ) -> None:
        self.generate = generate
        self.verify = verify
        self.build_feedback = build_feedback or self._default_feedback

    @staticmethod
    def _default_feedback(artifact: Any, evidence: dict[str, Any]) -> str:
        error = evidence.get("error") or "验证失败，但没有返回错误详情"
        return f"上一版交付物验证失败。真实失败证据：\n{error}\n请只输出修订后的完整交付物。"

    @staticmethod
    def _is_passed(evidence: dict[str, Any]) -> bool:
        return evidence.get("available", True) is not False and evidence.get("passed") is True

    def run_stream(self, prompt: str, inspect: Callable[[Any], dict[str, Any]], max_iterations: int = 3) -> RevisionResult:
        """按生成片段逐轮检查；检查失败立即停止，不伪造完整交付。"""
        if max_iterations < 1:
            raise ValueError("max_iterations 必须至少为1")
        stages: list[dict[str, Any]] = []
        artifact = self.generate(prompt)
        for index in range(max_iterations):
            inspection = inspect(artifact)
            stages.append({"stage": "stream_inspection", "iteration": index, "artifact": artifact, "inspection": inspection})
            if inspection.get("ok") is not True:
                return RevisionResult("inspection_failed", initial_artifact=artifact, revised_artifact=artifact, stages=stages)
            evidence = self.verify(artifact)
            stages.append({"stage": "stream_verify", "iteration": index, "artifact": artifact, "evidence": evidence})
            if evidence.get("available", True) is False:
                return RevisionResult("not_verifiable", initial_artifact=artifact, revised_artifact=artifact, stages=stages)
            if self._is_passed(evidence):
                return RevisionResult("passed", initial_artifact=artifact, revised_artifact=artifact, revision_count=index, stages=stages)
            if index + 1 < max_iterations:
                artifact = self.generate(self.build_feedback(artifact, evidence))
        return RevisionResult("revision_failed", initial_artifact=stages[0]["artifact"], revised_artifact=artifact, revision_count=max_iterations - 1, stages=stages)

    def run(self, prompt: str, max_revisions: int = 1) -> RevisionResult:
        if max_revisions < 0:
            raise ValueError("max_revisions 不能为负数")

        stages: list[dict[str, Any]] = []
        artifact = self.generate(prompt)
        initial = artifact
        evidence = self.verify(artifact)
        stages.append({"stage": "initial", "artifact": artifact, "evidence": evidence})

        if evidence.get("available", True) is False:
            return RevisionResult("not_verifiable", initial_artifact=initial, feedback=evidence, stages=stages)
        if self._is_passed(evidence):
            return RevisionResult("passed", initial_artifact=initial, revised_artifact=artifact, stages=stages)

        for revision_index in range(1, max_revisions + 1):
            feedback = {"passed": False, "error": evidence.get("error", "验证失败")}
            stages.append({"stage": "feedback", "feedback": feedback, "revision": revision_index})
            revision_prompt = self.build_feedback(artifact, feedback)
            artifact = self.generate(revision_prompt)
            evidence = self.verify(artifact)
            stages.append({"stage": "revision", "artifact": artifact, "evidence": evidence, "revision": revision_index})
            if evidence.get("available", True) is False:
                return RevisionResult(
                    "not_verifiable",
                    initial_artifact=initial,
                    revised_artifact=artifact,
                    feedback=feedback,
                    revision_count=revision_index,
                    stages=stages,
                )
            if self._is_passed(evidence):
                return RevisionResult(
                    "passed",
                    initial_artifact=initial,
                    revised_artifact=artifact,
                    feedback=feedback,
                    revision_count=revision_index,
                    stages=stages,
                )

        return RevisionResult(
            "revision_failed",
            initial_artifact=initial,
            revised_artifact=artifact,
            feedback={"passed": False, "error": evidence.get("error", "验证失败")},
            revision_count=max_revisions,
            stages=stages,
        )
