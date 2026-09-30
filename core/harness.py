"""CSCD 运行时动作执行器与模型动作计划解析。"""

from __future__ import annotations

from dataclasses import dataclass
import copy
import json
import re
import shutil
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

from core.runtime_state import RuntimeState, RuntimeWorkspace


def build_context(state: RuntimeState) -> dict[str, Any]:
    """按当前运行阶段构造最小可见上下文，避免一次性暴露全部状态。"""
    tools = state.allowed_tools()
    if state.phase == "anchor":
        context = "最小化上下文：先读取或搜索，确认任务入口。"
    elif state.phase == "explore":
        context = "工作区事实：\n" + "\n".join(state.verified or ["暂无已验证事实"])
    elif state.phase == "implement":
        context = "已验证事实：\n" + "\n".join(state.verified or ["暂无"]) + "\n当前焦点：" + (state.next_action or "暂无")
    elif state.phase == "verify":
        context = "测试证据：\n" + "\n".join(state.test_results or ["暂无测试结果"])
    else:
        context = "交付状态：\n" + "\n".join(state.test_results or ["暂无测试结果"])
    return {"phase": state.phase, "tools": tools, "context": context}


_ACTIONS = {
    "read", "search", "edit", "write", "run_test", "inspect_failure",
    "anchor_completed", "exploration_completed", "implementation_completed", "verification_completed",
    "checkpoint", "rollback", "ship",
}

# run_test 允许的执行器白名单：仅测试框架入口。
# cmd / powershell / wscript / rundll32 等可直接执行任意代码，必须拒绝，
# 否则 run_test 就退化成任意命令执行通道，绕过阶段与路径限制。
_BLOCKED_PROGRAMS = {
    "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
    "wscript", "wscript.exe", "cscript", "cscript.exe",
    "rundll32", "rundll32.exe", "regsvr32", "mshta", "mshta.exe",
    "bash", "bash.exe", "sh", "zsh", "wsl", "wsl.exe",
    "curl", "curl.exe", "wget", "wget.exe", "certutil", "bitsadmin",
}


@dataclass
class ActionResult:
    """单个动作的结构化执行结果。"""

    action: str
    ok: bool
    result: Any = None
    error: str = ""
    side_effect: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "ok": self.ok,
            "result": self.result,
            "error": self.error,
            "side_effect": self.side_effect,
        }


class DefaultActionExecutor:
    """默认文件与测试执行器；所有路径都限制在根目录内。"""

    def __init__(self, root: Path, workspace: RuntimeWorkspace):
        self.root = Path(root).resolve()
        self.workspace = workspace
        self.snapshots: dict[str, dict[str, Optional[bytes]]] = {}

    def _path(self, value: str) -> Path:
        candidate = (self.root / str(value)).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("路径必须位于执行根目录内")
        return candidate

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def read(self, spec: dict[str, Any]) -> dict[str, Any]:
        path = self._path(spec.get("path", ""))
        return {"path": self._relative(path), "content": path.read_text(encoding="utf-8")}

    def search(self, spec: dict[str, Any]) -> dict[str, Any]:
        query = str(spec.get("query", spec.get("pattern", "")))
        if not query:
            raise ValueError("search 需要 query 或 pattern")
        base = self._path(spec.get("path", "."))
        candidates = [base] if base.is_file() else base.rglob("*")
        matches = []
        for path in candidates:
            if not path.is_file() or ".cscd" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if query.lower() in text.lower():
                matches.append(self._relative(path))
        return {"query": query, "matches": matches}

    def write(self, spec: dict[str, Any]) -> dict[str, Any]:
        path = self._path(spec.get("path", ""))
        content = spec.get("content", "")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")
        return {"path": self._relative(path), "bytes": len(str(content).encode("utf-8"))}

    def edit(self, spec: dict[str, Any]) -> dict[str, Any]:
        path = self._path(spec.get("path", ""))
        text = path.read_text(encoding="utf-8")
        old = spec.get("old", spec.get("find"))
        new = spec.get("new", spec.get("replace", ""))
        if old is None or str(old) not in text:
            raise ValueError("edit 未找到 old/find 文本")
        updated = text.replace(str(old), str(new), 1)
        path.write_text(updated, encoding="utf-8")
        return {"path": self._relative(path), "replacements": 1}

    def validate_test_command(self, command: str) -> list[str]:
        """校验测试命令并返回解析后的 argv。

        逐字符扫描原始命令串，而不是靠子串黑名单。子串黑名单可被未覆盖的元字符绕过
        （实测 '>'、'&'、换行均曾漏网），而这些字符足以在 Windows 上实现
        重定向、串接和命令调用。同时拒绝可执行任意代码的解释器。
        """
        command = str(command or "")
        if not command:
            raise ValueError("run_test 需要 command")
        forbidden = ";&|<>`\n\r$"
        bad = sorted({ch for ch in command if ch in forbidden})
        if bad:
            raise ValueError(f"run_test 命令包含危险字符: {' '.join(bad)}")
        # 命令替换的判据是「$( 或 ` 前置的括号」，不是任意括号——
        # 合法测试命令本就大量含括号（python -c "print(1)"、pytest -k "test_foo(bar)"）。
        # $ 与反引号已在上面的危险字符里拦掉，这里只做一次显式提示。
        if "$((" in command:
            raise ValueError("run_test 命令包含嵌套命令替换")
        try:
            argv = shlex.split(command, posix=False)
        except ValueError as exc:
            raise ValueError("run_test 命令解析失败") from exc
        if not argv:
            raise ValueError("run_test 命令为空")
        program = Path(str(argv[0])).name.lower()
        if program in _BLOCKED_PROGRAMS:
            raise ValueError(f"run_test 禁止调用解释器/命令执行器: {program}")
        return argv

    def run_test(self, spec: dict[str, Any]) -> dict[str, Any]:
        command = str(spec.get("command", spec.get("cmd", "")))
        argv = self.validate_test_command(command)
        completed = subprocess.run(
            argv, cwd=self.root, shell=False, capture_output=True, text=True,
            timeout=float(spec.get("timeout", 120)), check=False,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-10000:],
            "stderr": completed.stderr[-10000:],
            "ok": completed.returncode == 0,
        }

    def inspect_failure(self, spec: dict[str, Any]) -> dict[str, Any]:
        return {
            "test_results": spec.get("test_results", []),
            "message": spec.get("message", "检查最近一次测试失败结果"),
        }

    def checkpoint(self, spec: dict[str, Any], changed_files: list[str]) -> dict[str, Any]:
        point = str(spec.get("point", spec.get("name", "checkpoint")))
        snapshot: dict[str, Optional[bytes]] = {}
        for name in changed_files:
            path = self._path(name)
            snapshot[name] = path.read_bytes() if path.exists() else None
        self.snapshots[point] = snapshot
        return {"point": point, "files": list(snapshot)}

    def rollback(self, spec: dict[str, Any]) -> dict[str, Any]:
        point = str(spec.get("point", spec.get("name", "")))
        if point not in self.snapshots:
            raise ValueError(f"不存在回滚点: {point}")
        restored = []
        for name, content in self.snapshots[point].items():
            path = self._path(name)
            if content is None:
                if path.exists():
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            restored.append(name)
        return {"point": point, "restored": restored}


class Harness:
    """解析并执行受阶段白名单保护的动作计划。"""

    def __init__(self, root: Optional[Path] = None, workspace: Optional[RuntimeWorkspace] = None,
                 executor: Any = None):
        self.root = Path(root or ".").resolve()
        self.workspace = workspace
        self.executor = executor or DefaultActionExecutor(self.root, workspace or RuntimeWorkspace("untitled", self.root / ".cscd"))
        self.state_snapshots: dict[str, dict[str, Any]] = {}

    @staticmethod
    def parse_plan(plan_text: str) -> list[dict[str, Any]]:
        text = str(plan_text or "").strip()
        if not text:
            return []
        # 优先级 1：JSON 块（含 ```json ... ``` 包裹），用 raw_decode 容忍尾部文本
        decoder = json.JSONDecoder()
        candidates = [text]
        candidates.extend(re.findall(r"```(?:json)?\s*(.*?)```", text, re.I | re.S))
        for candidate in candidates:
            candidate = candidate.strip()
            try:
                value, _ = decoder.raw_decode(candidate)
                actions = value.get("actions", [value]) if isinstance(value, dict) else value
                if isinstance(actions, dict):
                    actions = [actions]
                if isinstance(actions, list):
                    return [item for item in actions if isinstance(item, dict)]
            except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
                continue
        # 优先级 1.5：四阶协议输出优先识别（真实端点验证发现，2026-09-02）。
        # 模型按 C-S-C-D 输出 <DECOMPOSE>/<CLASSIFY>/<SELECT>/<COMBINE> 时，正文里
        # 常出现「读取」「搜索」等普通词语，若继续往下走优先级 2/3，会被误判成
        # read/search 动作计划：四阶推理被当成工具调用去执行文件读取，
        # 同时主循环走动作分支会跳过 marks 审计（vr 恒 True），可追溯性失效。
        # 放在优先级 1 之后：模型若确实给出了合法 JSON actions，动作意图更明确，仍按动作处理。
        if re.search(r"<(DECOMPOSE|CLASSIFY|SELECT|COMBINE)\b", text, re.I):
            return []
        # 优先级 2：检测 XML 标签（在自然语言之前尝试，避免 run_test 等误匹配标签内容）
        xml_tag_pattern = r"<(read|search|edit|write|run_test|checkpoint|rollback|anchor_completed|exploration_completed|implementation_completed|verification_completed|ship)\b"
        has_xml = re.search(xml_tag_pattern, text, re.I)
        if has_xml:
            xml_actions = {
                "read": ("path", r"<read>(.*?)</read>"),
                "search": ("query", r"<search>(.*?)</search>"),
                "edit": ("old", r"<edit>.*?<old>(.*?)</old>.*?</edit>"),
                "write": ("path", r"<write>(.*?)</write>"),
                "run_test": ("command", r"<run_test>(.*?)</run_test>"),
                "checkpoint": ("point", r"<checkpoint>(.*?)</checkpoint>"),
                "rollback": ("point", r"<rollback>(.*?)</rollback>"),
            }
            for action, (key, pattern) in xml_actions.items():
                match = re.search(pattern, text, re.I | re.S)
                if match:
                    return [{"action": action, key: match.group(1).strip()}]
            for action in {"anchor_completed", "exploration_completed", "implementation_completed", "verification_completed", "ship"}:
                if re.search(rf"<{action}\s*/?>", text, re.I):
                    return [{"action": action}]
        # 优先级 3：自然语言匹配
        matchers = [
            ("read", r"(?:read|读取|读取文件)\s+(?:file|文件)?\s*[`\"']?([^`\"'\s,。]+)"),
            ("search", r"(?:search|搜索|查找)\s+(?:for)?\s*[`\"']?([^`\"'\s,。]+)"),
            ("run_test", r"(?:run_test|运行测试|执行测试)\s*[:：]?\s*[`\"']?(.+?)[`\"']?$"),
            ("checkpoint", r"(?:checkpoint|检查点)\s*[:：]?\s*([\w.-]+)"),
            ("rollback", r"(?:rollback|回滚)\s*[:：]?\s*([\w.-]+)"),
            ("anchor_completed", r"(?:anchor_completed|完成锚定|锚定完成)\b"),
            ("exploration_completed", r"(?:exploration_completed|完成探索|探索完成)\b"),
            ("implementation_completed", r"(?:implementation_completed|完成实现|实现完成)\b"),
            ("verification_completed", r"(?:verification_completed|完成验证|验证完成)\b"),
            ("ship", r"(?:ship|交付|发布)\b"),
        ]
        for action, pattern in matchers:
            match = re.search(pattern, text, re.I | re.M)
            if match:
                if action in {"ship", "anchor_completed", "exploration_completed", "implementation_completed", "verification_completed"}:
                    return [{"action": action}]
                key = "command" if action == "run_test" else ("query" if action == "search" else ("point" if action in {"checkpoint", "rollback"} else "path"))
                return [{"action": action, key: match.group(1).strip()}]
        return []

    def _record(self, state: RuntimeState, event: str, evidence: dict[str, Any]) -> None:
        state.execution_evidence.append(evidence)
        if self.workspace:
            payload = dict(evidence)
            result = evidence.get("result")
            if event == "checkpoint" and isinstance(result, dict):
                payload["point"] = result.get("point", "")
            self.workspace.record(state, event, payload)

    def run_action_plan(self, state: RuntimeState, plan_text: str) -> list[dict[str, Any]]:
        results = []
        for spec in self.parse_plan(plan_text):
            action = str(spec.get("action", "")).strip().lower()
            if action not in _ACTIONS:
                result = ActionResult(action, False, error="非法动作", side_effect=False)
                denied = {"kind": "action_denied", **result.to_dict()}
                self._record(state, "action_denied", denied)
                results.append(result.to_dict())
                continue
            if action not in state.allowed_tools():
                result = ActionResult(action, False, error=f"阶段 {state.phase} 不允许该动作", side_effect=False)
                denied = {"kind": "action_denied", **result.to_dict()}
                self._record(state, "action_denied", denied)
                results.append(result.to_dict())
                continue
            try:
                if action == "run_test":
                    command = str(spec.get("command", spec.get("cmd", "")))
                    # 复用执行器的同一套校验，避免门禁与执行两处规则漂移。
                    self.executor.validate_test_command(command)
                    if not state.changed_files:
                        raise ValueError("运行测试前必须存在已修改文件")
                if action in {"read", "search", "edit", "write", "run_test", "inspect_failure"}:
                    value = getattr(self.executor, action)(spec)
                elif action == "checkpoint":
                    value = self.executor.checkpoint(spec, state.changed_files)
                    self.state_snapshots[str(value["point"])] = state.to_dict()
                    if self.workspace:
                        files = getattr(self.executor, "snapshots", {}).get(str(value["point"]), {})
                        self.workspace.save_checkpoint(str(value["point"]), state, files)
                elif action == "rollback":
                    point = str(spec.get("point", spec.get("name", "")))
                    snapshot = self.state_snapshots.get(point)
                    persisted = self.workspace.load_checkpoint(point) if self.workspace else None
                    restored = RuntimeState.from_dict(snapshot) if snapshot else (persisted["state"] if persisted else None)
                    if persisted and not snapshot:
                        files = persisted.get("files", {})
                        for name, content in files.items():
                            path = self.executor._path(name)
                            if content is None:
                                if path.exists():
                                    path.unlink()
                            else:
                                path.parent.mkdir(parents=True, exist_ok=True)
                                path.write_bytes(content)
                    value = self.executor.rollback(spec) if snapshot else {"point": point, "restored": list((persisted or {}).get("files", {}))}
                    if restored:
                        current_evidence = list(state.execution_evidence)
                        state.__dict__.update(restored.__dict__)
                        state.execution_evidence = current_evidence
                elif action in {"anchor_completed", "exploration_completed", "implementation_completed", "verification_completed"}:
                    if action == "verification_completed":
                        def is_passing_test(result: Any) -> bool:
                            if isinstance(result, dict):
                                return result.get("ok") is True or result.get("returncode") == 0
                            try:
                                parsed = json.loads(str(result))
                            except (TypeError, json.JSONDecodeError):
                                return False
                            return isinstance(parsed, dict) and (
                                parsed.get("ok") is True or parsed.get("returncode") == 0
                            )

                        if not any(is_passing_test(result) for result in state.test_results):
                            raise ValueError("验证完成前必须存在通过的测试证据")
                    value = {"status": "completed", "phase_event": action}
                elif action == "ship":
                    if not state.test_results:
                        raise ValueError("交付前必须完成验证：测试结果为空")
                    # 只认真实测试证据，不再只看 verification_completed 声明。
                    def is_passing_test(result: Any) -> bool:
                        if isinstance(result, dict):
                            return result.get("ok") is True or result.get("returncode") == 0
                        try:
                            parsed = json.loads(str(result))
                        except (TypeError, json.JSONDecodeError):
                            return False
                        return isinstance(parsed, dict) and (
                            parsed.get("ok") is True or parsed.get("returncode") == 0
                        )

                    has_passing_test = any(is_passing_test(result) for result in state.test_results)
                    if not has_passing_test:
                        raise ValueError("交付前必须完成验证：缺少通过的测试证据")
                    value = {"task_id": state.task_id, "status": "shipped"}
                evidence = {"kind": action, "status": "completed", "result": value}
                if action == "run_test":
                    command = value["command"]
                    if command not in state.test_commands:
                        state.test_commands.append(command)
                    state.test_results.append(json.dumps(value, ensure_ascii=False))
                if action == "rollback":
                    point = value["point"]
                    if point not in state.rollback_points:
                        state.rollback_points.append(point)
                    evidence["state_snapshot"] = state.to_dict()
                if action in {"edit", "write"} and value["path"] not in state.changed_files:
                    state.changed_files.append(value["path"])
                if action == "anchor_completed":
                    has_first_read = any(
                        item.get("kind") in {"read", "search"} and item.get("status") == "completed"
                        for item in state.execution_evidence
                    )
                    if not has_first_read:
                        raise ValueError("锚定完成前必须成功执行 read 或 search")
                event = {"read": "first_read", "search": "first_read", "edit": "first_edit", "write": "first_edit", "run_test": "first_test", "checkpoint": "checkpoint", "rollback": "rollback", "ship": "ship"}.get(action, action)
                self._record(state, event, evidence)
                if action == "anchor_completed":
                    self._record(state, "promoted", {"kind": "promotion", "status": "completed", "reason": "anchor action completed after first read"})
                results.append(ActionResult(action, True, value, side_effect=action in {"edit", "write", "run_test", "checkpoint", "rollback", "ship"}).to_dict())
            except Exception as exc:
                result = ActionResult(action, False, error=f"{type(exc).__name__}: {exc}")
                self._record(state, "action_failed", result.to_dict())
                results.append(result.to_dict())
        return results

    def run_branches(self, state: RuntimeState, branches: dict[str, Callable[[RuntimeState], Any]], score: Callable[[Any], float]) -> dict[str, Any]:
        """从同一状态快照运行替代分支，并选择评分最高结果。"""
        if not branches:
            raise ValueError("分支集合不能为空")
        base_state = copy.deepcopy(state)
        results: dict[str, Any] = {}
        for name, branch in branches.items():
            branch_state = copy.deepcopy(base_state)
            try:
                value = branch(branch_state)
                results[name] = {"ok": True, "result": value, "score": score(value), "state": branch_state.to_dict()}
            except Exception as exc:
                results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "score": float("-inf"), "state": branch_state.to_dict()}
        selected = max(results, key=lambda name: results[name]["score"])
        state.__dict__.update(RuntimeState.from_dict(results[selected]["state"]).__dict__)
        audit_branches = {
            name: {key: value for key, value in branch_result.items() if key != "state"}
            for name, branch_result in results.items()
        }
        self._record(state, "branches_evaluated", {"kind": "branches_evaluated", "branches": audit_branches, "selected": selected})
        return {"selected": selected, "branches": results}

    def run_revision(self, state: RuntimeState, controller: Any, prompt: str, max_revisions: int = 1) -> Any:
        """执行反馈修订控制器，并把真实反馈写入运行轨迹。"""
        result = controller.run(prompt, max_revisions=max_revisions)
        for stage in result.stages:
            event = {
                "feedback": "revision_feedback",
                "revision": "revision_generated",
            }.get(stage.get("stage"))
            if event:
                self._record(state, event, {"kind": event, **stage})
        state.delivery_artifact = {
            "status": result.status,
            "revision_count": result.revision_count,
            "feedback": result.feedback,
        }
        self._record(state, "revision_completed", {
            "kind": "revision_completed",
            "status": result.status,
            "revision_count": result.revision_count,
        })
        return result

    def run_loop(self, state: RuntimeState, planner: Callable[[RuntimeState, list[dict[str, Any]]], str], max_steps: int = 20) -> list[dict[str, Any]]:
        """执行规划、动作、失败回传和重规划闭环，直到交付或达到步数上限。"""
        history: list[dict[str, Any]] = []
        for step in range(max_steps):
            plan_text = planner(state, history)
            if not plan_text:
                failure = {
                    "kind": "action_planning_failed",
                    "step": step + 1,
                    "error": "规划器未返回动作计划",
                }
                self._record(state, "action_planning_failed", failure)
                history.append({"step": step + 1, "plan": "", "results": [], "failure": failure})
                continue
            self._record(state, "action_planned", {
                "kind": "action_planned",
                "step": step + 1,
                "plan": str(plan_text)[:4000],
            })
            results = self.run_action_plan(state, plan_text)
            batch = {"step": step + 1, "plan": plan_text, "results": results}
            history.append(batch)
            if any(item.get("action") == "ship" and item.get("ok") for item in results):
                break
            if not any(item.get("ok") for item in results):
                recovery = {
                    "kind": "action_recovery_requested",
                    "step": step + 1,
                    "error": "本批次动作全部失败，下一轮必须基于失败结果重新规划",
                }
                self._record(state, "action_recovery_requested", recovery)
                batch["recovery"] = recovery
                continue
        else:
            self._record(state, "action_loop_exhausted", {
                "kind": "action_loop_exhausted",
                "steps": max_steps,
                "reason": "达到最大重规划步数，未完成 ship",
            })
        return history


ActionExecutor = DefaultActionExecutor
