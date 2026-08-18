"""
运行时状态外化账本（J-Space controller 能力，P4）
================================================
把推理过程中的认知控制状态、四阶轨迹、审计字段**外化到磁盘账本**，
实现跨调用/跨会话的持久化与恢复（对应 J-Space `seam/note/ship/resume` 子命令）。

与 core/cognition.py 的关系：
- cognition.py 负责"推理时认知控制"的指令注入与信号解析（内存态）。
- 本模块把每轮的认知状态 + 推理轨迹**落盘**（外化态），支持 seam（接缝点）、
  note（状态备注）、ship（交付物定稿）、resume（恢复续跑）。

设计：
- 账本目录：`{ROOT}/.cscd/ledger/`，每个任务一个 JSONL 文件。
- 追加式写入，不重写历史；resume 时读取最新状态继续。
- 纯确定性、可审计、无模型依赖（与压缩铁律一致）。
"""

import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 账本根目录（可被环境变量覆盖，便于测试）
_LEDGER_ROOT = Path(os.getenv("CSCD_LEDGER_DIR", str(Path(__file__).resolve().parent.parent / ".cscd" / "ledger")))

# 内存条目上限（超过时裁剪，仅保留最新 N 条；文件本身保持追加式、不截断）
_MAX_ENTRIES = 10000

# ship 交付物字符串最大长度（超出截断并告警）
_MAX_ARTIFACT_LEN = 20000

# task_id 清洗后最大长度
_MAX_TASK_ID_LEN = 128


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _sanitize_task_id(task_id: str) -> str:
    """清洗 task_id，防止路径穿越（两个防护通道都会经过这里）。

    清洗规则：
    - 空串 / 全空白 / 含 `..` 等危险串清洗后为空的 → 默认值 "untitled"
    - 仅保留字母、数字、下划线、连字符，其余字符替换为 `_`
    - 超过 _MAX_TASK_ID_LEN 则截断
    """
    if not task_id:
        return "untitled"
    cleaned = re.sub(r"[^A-Za-z0-9_\-]", "_", str(task_id))
    cleaned = cleaned.strip("_")
    # 清洗后为空（如 "."、".."、纯符号）或全为分隔符 → 兜底默认值
    if not cleaned:
        return "untitled"
    return cleaned[:_MAX_TASK_ID_LEN]


def _try_lock_file(f) -> bool:
    """尝试对打开的文件对象加文件级排他锁（标准库，尽力而为）。

    平台策略：
    - Windows：msvcrt.locking（1 字节区域锁）
    - Linux/其他 Unix：fcntl.flock（LOCK_EX）
    - 平台不支持或加锁失败 → 返回 False，调用方跳过解锁（进程内已有 threading.Lock 兜底）

    Returns:
        是否成功加锁。
    """
    try:
        if sys.platform == "win32":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            return True
        try:
            import fcntl
        except ImportError:
            return False
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        return True
    except (ImportError, OSError, AttributeError):
        return False


def _try_unlock_file(f, locked: bool) -> None:
    """释放 _try_lock_file 获取的文件锁。"""
    if not locked:
        return
    try:
        if sys.platform == "win32":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            return
        try:
            import fcntl
        except ImportError:
            return
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except (ImportError, OSError, AttributeError):
        return


class Ledger:
    """任务级推理账本：外化认知状态 + 轨迹 + 审计，支持 resume。"""

    def __init__(self, task_id: str = None, root: Path = None):
        self.root = Path(root or _LEDGER_ROOT)
        # 两个通道（默认生成的随机 id / 调用方传入的 task_id）都经过清洗，防路径穿越
        self.task_id = _sanitize_task_id(task_id or uuid.uuid4().hex[:12])
        self.file = self.root / f"{self.task_id}.jsonl"
        self.entries: List[dict] = []
        # 进程内互斥锁：保护内存列表 + 文件追加的原子性
        self._lock = threading.Lock()
        self._load_existing()

    # ---------- 基础读写 ----------
    def _load_existing(self):
        if self.file.exists():
            with self.file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self.entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            logger.warning(
                                "账本 %s 存在损坏行，已跳过: %s", self.file, line[:80]
                            )
            if len(self.entries) > _MAX_ENTRIES:
                logger.warning(
                    "账本 %s 条目数 %d 超过上限 %d，内存仅保留最新 %d 条",
                    self.task_id, len(self.entries), _MAX_ENTRIES, _MAX_ENTRIES,
                )
                self.entries = self.entries[-_MAX_ENTRIES:]

    def _append(self, kind: str, payload: dict):
        entry = {
            "kind": kind,
            "task_id": self.task_id,
            "ts": _now_iso(),
            **payload,
        }
        self.file.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.file.open("a", encoding="utf-8") as f:
                # 文件级锁：Windows 上保证跨进程互斥；不支持的平台降级为进程内锁
                locked = _try_lock_file(f)
                try:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    _try_unlock_file(f, locked)
            self.entries.append(entry)
            if len(self.entries) > _MAX_ENTRIES:
                logger.warning(
                    "账本 %s 内存条目数超过上限 %d，裁剪为最新 %d 条",
                    self.task_id, _MAX_ENTRIES, _MAX_ENTRIES,
                )
                self.entries = self.entries[-_MAX_ENTRIES:]
        return entry

    # ---------- J-Space 四个子命令 ----------
    def note(self, **state: Any) -> dict:
        """note：记录当前推理/认知状态（工作空间、稠密轨、锚定等）。"""
        return self._append("note", {"state": state})

    def seam(self, seam_id: str = None, **ctx: Any) -> dict:
        """seam：记录接缝点——此处可中断，之后可从这里 resume。"""
        return self._append("seam", {"seam_id": seam_id or uuid.uuid4().hex[:8], **ctx})

    def ship(self, artifact: Any, summary: str = "") -> dict:
        """ship：定稿交付物（精炼结论/压缩摘要），标记任务完成。"""
        if isinstance(artifact, str) and len(artifact) > _MAX_ARTIFACT_LEN:
            logger.warning(
                "ship artifact 长度 %d 超过上限 %d，已截断",
                len(artifact), _MAX_ARTIFACT_LEN,
            )
            artifact = artifact[:_MAX_ARTIFACT_LEN]
        return self._append("ship", {"summary": summary, "artifact": artifact})

    def resume(self) -> Optional[dict]:
        """resume：从最后一个 seam/note 恢复上下文。

        Returns:
            最近一个非 ship 条目的 state 字典（含 seam_id/kind/ts），若无则 None。
        """
        for entry in reversed(self.entries):
            if entry.get("kind") in ("note", "seam"):
                return entry
        return None

    # ---------- 查询 ----------
    def history(self) -> List[dict]:
        """按时间顺序返回全部账本条目。"""
        return list(self.entries)

    def ships(self) -> List[dict]:
        """返回全部 ship 条目（交付物）。"""
        return [e for e in self.entries if e.get("kind") == "ship"]

    def last_ship(self) -> Optional[dict]:
        ships = self.ships()
        return ships[-1] if ships else None

    def to_dict(self) -> dict:
        """导出账本全文（供审计/导出）。"""
        return {
            "task_id": self.task_id,
            "file": str(self.file),
            "count": len(self.entries),
            "entries": self.entries,
        }


def ledger_for(task_id: str = None) -> Ledger:
    """获取（或创建）一个账本实例。"""
    return Ledger(task_id=task_id)


# ---------- CscdEngine 集成辅助 ----------
def dump_round(ledger: Ledger, round_idx: int, cognition: dict,
               marks_valid: bool, summary: str) -> dict:
    """把一轮的认知状态 + 推理轨迹摘要外化到账本（note）。"""
    return ledger.note(
        round_idx=round_idx,
        cognition=cognition,
        marks_valid=marks_valid,
        summary=summary,
    )