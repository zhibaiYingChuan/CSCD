"""
CSCD 推理时运行状态与工作空间外化。

该模块保存真正驱动下一步动作的状态，而不是依赖模型输出的 XML 标记。
推理摘要可以压缩，交付物和执行证据必须单独保留。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Optional


_PHASES = ("anchor", "explore", "implement", "verify", "ship")
_PHASE_INDEX = {name: index for index, name in enumerate(_PHASES)}
_PHASE_EVENTS = {
    "anchor_started": "anchor",
    "anchor_completed": "explore",
    "first_read": "explore",       # 同时触发 promoted（见 apply_event）
    "first_edit": "implement",
    "first_test": "verify",
    "promoted": "explore",
    "exploration_completed": "implement",
    "implementation_completed": "verify",
    "verification_completed": "ship",
    "checkpoint": None,
    "rollback": None,
    "ship": "ship",
}


def _safe_task_id(task_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]", "_", str(task_id or "untitled"))
    return value.strip("._")[:128] or "untitled"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


@dataclass
class RuntimeState:
    """跨轮次、可恢复的 CSCD 运行状态。"""

    task_id: str
    phase: str = "anchor"
    goal: str = ""
    done_when: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    verified: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    next_action: str = ""
    changed_files: list[str] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)
    test_results: list[str] = field(default_factory=list)
    rollback_points: list[str] = field(default_factory=list)
    delivery_artifact: dict[str, Any] = field(default_factory=dict)
    execution_evidence: list[dict[str, Any]] = field(default_factory=list)
    round_index: int = 0
    promotion_state: str = "pending"
    promoted: bool = False

    def set_phase(self, phase: str) -> None:
        if phase not in _PHASES:
            raise ValueError(f"未知运行阶段: {phase}")
        self.phase = phase

    def apply_event(self, event: str, payload: Optional[dict[str, Any]] = None) -> None:
        """根据持久事件更新状态；阶段不再由调用方直接赋值。"""
        payload = payload or {}
        phase = _PHASE_EVENTS.get(event)
        if phase is not None and _PHASE_INDEX[phase] >= _PHASE_INDEX[self.phase]:
            self.phase = phase
        if event == "promoted":
            self.promoted = True
            self.promotion_state = "promoted"
        elif event == "first_read":
            # 机制1 动态锚定：模型实际执行 read/search 后立即晋升，不再依赖 anchor_completed
            if not self.promoted:
                self.promoted = True
                self.promotion_state = "promoted"
        elif event == "anchor_completed":
            self.promotion_state = "eligible"
        elif event == "rollback":
            self.promotion_state = "rolled_back"
        elif event == "checkpoint":
            point = str(payload.get("point", ""))
            if point and point not in self.rollback_points:
                self.rollback_points.append(point)
        if "round" in payload:
            self.round_index = int(payload["round"])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimeState":
        fields = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        return cls(**fields)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def allowed_tools(self) -> list[str]:
        """按持久运行阶段和锚定状态返回模型可规划的动作集合。

        机制1 动态锚定：晋升前只暴露 read/search，晋升后解锁完整工具集。
        """
        if not self.promoted and self.phase in ("anchor", "explore"):
            return ["read", "search"]
        return {
            "anchor": ["read", "search"],
            "explore": ["read", "search", "anchor_completed", "exploration_completed"],
            "implement": ["read", "search", "edit", "write", "checkpoint", "rollback", "implementation_completed"],
            "verify": ["read", "search", "run_test", "inspect_failure", "checkpoint", "rollback", "verification_completed"],
            "ship": ["read", "search", "checkpoint", "rollback", "ship"],
        }[self.phase]

    def update_from_text(self, text: str) -> None:
        """从模型文本提取轻量状态；失败不影响已有状态。"""
        if not text:
            return
        for line in text.splitlines():
            value = line.strip().lstrip("-* ")
            if not value:
                continue
            if re.match(r"(?:目标|goal)\s*[:：]", value, re.I):
                self.goal = re.split(r"[:：]", value, maxsplit=1)[1].strip()
            elif re.match(r"(?:下一步|next action)\s*[:：]", value, re.I):
                self.next_action = re.split(r"[:：]", value, maxsplit=1)[1].strip()
            elif re.match(r"(?:已验证|verified)\s*[:：]", value, re.I):
                item = re.split(r"[:：]", value, maxsplit=1)[1].strip()
                if item and item not in self.verified:
                    self.verified.append(item)
            elif re.match(r"(?:待确认|开放问题|open)\s*[:：]", value, re.I):
                item = re.split(r"[:：]", value, maxsplit=1)[1].strip()
                if item and item not in self.open_questions:
                    self.open_questions.append(item)
            elif re.match(r"(?:修改文件|changed files?)\s*[:：]", value, re.I):
                files = re.split(r"[:：]", value, maxsplit=1)[1]
                for item in re.split(r"[,，、\s]+", files):
                    if item and item not in self.changed_files:
                        self.changed_files.append(item)


class RuntimeWorkspace:
    """把 RuntimeState 投影到 .cscd 工作空间、轨迹和交付物文件。"""

    def __init__(self, task_id: str, root: Optional[Path] = None):
        base = Path(root or os.getenv("CSCD_RUNTIME_DIR", ".cscd"))
        self.root = base
        self.task_id = _safe_task_id(task_id)
        self.workspace_dir = base / "workspace"
        self.traces_dir = base / "traces"
        self.artifacts_dir = base / "artifacts"
        self.trace_file = self.traces_dir / "task.jsonl"
        self.artifact_file = self.artifacts_dir / "tests.json"
        self.patch_dir = self.artifacts_dir / "patches"
        self.checkpoint_dir = self.artifacts_dir / "checkpoints"

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".cscd-", dir=str(path.parent), text=True)
        renamed = False
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
            renamed = True
        finally:
            # 只在替换未发生时清理临时文件。原实现无条件 unlink，
            # 而 os.replace 之后 temp_name 已被移除，Windows 上会抛 FileNotFoundError
            # 并把一次成功写入误报为失败。
            if not renamed and os.path.exists(temp_name):
                os.unlink(temp_name)

    def save_state(self, state: RuntimeState) -> None:
        projections = {
            "goal.md": self._section("目标", [state.goal] + [f"完成条件：{x}" for x in state.done_when]),
            "verified.md": self._section("已验证", state.verified or ["暂无"]),
            "open.md": self._section("开放问题", state.open_questions or ["暂无"]),
            "next.md": self._section("下一步", [state.next_action or "暂无"]),
        }
        for name, content in projections.items():
            self._atomic_write(self.workspace_dir / name, content)

    def append_trace(self, state: RuntimeState, event: str, payload: Optional[dict[str, Any]] = None) -> None:
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": _now(),
            "event": event,
            "state": state.to_dict(),
            "payload": payload or {},
        }
        with self.trace_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def replay(self) -> Optional[RuntimeState]:
        """从事件日志重放并恢复状态，而不是信任最后一次内存快照。"""
        if not self.trace_file.exists():
            return None
        state = None
        checkpoint_states: dict[str, RuntimeState] = {}
        with self.trace_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                event = record["event"]
                payload = record.get("payload") or {}
                if state is None:
                    state = RuntimeState.from_dict(record["state"])
                if event == "checkpoint":
                    point = str(payload.get("point", ""))
                    if point:
                        checkpoint_states[point] = RuntimeState.from_dict(record["state"])
                if event == "rollback":
                    point = str(payload.get("point", ""))
                    restored = checkpoint_states.get(point)
                    if restored is not None:
                        current_evidence = list(state.execution_evidence)
                        state = RuntimeState.from_dict(restored.to_dict())
                        state.execution_evidence = current_evidence
                        state.apply_event(event, payload)
                        continue
                state.apply_event(event, payload)
                snapshot = record.get("state", {})
                for key, value in snapshot.items():
                    if key != "task_id" and hasattr(state, key):
                        setattr(state, key, value)
        return state

    def save_checkpoint(self, point: str, state: RuntimeState, files: Optional[dict[str, Optional[bytes]]] = None) -> None:
        """持久化 checkpoint 状态和文件快照，支持进程重启后的 rollback。"""
        encoded_files = {
            name: content.decode("latin1") if content is not None else None
            for name, content in (files or {}).items()
        }
        self._atomic_write(
            self.checkpoint_dir / f"{_safe_task_id(point)}.json",
            json.dumps({"state": state.to_dict(), "files": encoded_files}, ensure_ascii=False, indent=2),
        )

    def load_checkpoint(self, point: str) -> Optional[dict[str, Any]]:
        path = self.checkpoint_dir / f"{_safe_task_id(point)}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if "state" not in data:
            data = {"state": data, "files": {}}
        data["state"] = RuntimeState.from_dict(data["state"])
        data["files"] = {
            name: content.encode("latin1") if content is not None else None
            for name, content in data.get("files", {}).items()
        }
        return data

    def save_artifact(self, state: RuntimeState) -> None:
        self.patch_dir.mkdir(parents=True, exist_ok=True)
        self._atomic_write(
            self.artifact_file,
            json.dumps(
                {
                    "task_id": state.task_id,
                    "delivery_artifact": state.delivery_artifact,
                    "execution_evidence": state.execution_evidence,
                    "changed_files": state.changed_files,
                    "test_commands": state.test_commands,
                    "test_results": state.test_results,
                    "updated_at": _now(),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    def record(self, state: RuntimeState, event: str, payload: Optional[dict[str, Any]] = None) -> None:
        payload = payload or {}
        state.apply_event(event, payload)
        self.save_state(state)
        self.append_trace(state, event, payload)
        if event in {"artifact", "test", "ship", "checkpoint", "rollback"}:
            self.save_artifact(state)

    @staticmethod
    def _section(title: str, lines: list[str]) -> str:
        return f"# {title}\n\n" + "\n".join(f"- {line}" for line in lines) + "\n"

    def resume(self) -> Optional[RuntimeState]:
        """恢复接口统一返回事件重放后的运行状态。"""
        return self.replay()
