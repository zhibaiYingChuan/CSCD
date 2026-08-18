# -*- coding: utf-8 -*-
"""
历史记录存储（JSON 文件后端）
============================
轻量持久化：以追加式 JSON 行文件存储调用记录，支持搜索/筛选/删除/导出。
数据量增大后可平滑替换为 SQLite/IndexedDB（前端可另存本地副本）。
"""

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_HISTORY_FILE = _DATA_DIR / "history.jsonl"

logger = logging.getLogger(__name__)
_LOCK = threading.Lock()


def _ensure_dir():
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def add(record: dict) -> dict:
    """追加一条记录，自动补 id / created_at。"""
    item = dict(record)
    item.setdefault("id", uuid.uuid4().hex[:12])
    item.setdefault("created_at", _now_iso())
    with _LOCK:
        _ensure_dir()
        with _HISTORY_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            f.flush()
    return item


def list_all(query: str = "", limit: int = 100, offset: int = 0) -> dict:
    """列出记录；query 按 question/reason 模糊匹配；支持分页。"""
    if not _HISTORY_FILE.exists():
        return {"items": [], "total": 0}
    items = []
    with _HISTORY_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning("历史记录文件存在坏行，已跳过（%s）: %s", e, line)
                continue
    # 过滤
    if query:
        q = query.lower()
        items = [it for it in items
                 if q in (it.get("question", "") or "").lower()
                 or q in (it.get("reason", "") or "").lower()]
    # 时间倒序
    items.sort(key=lambda it: it.get("created_at", ""), reverse=True)
    total = len(items)
    page = items[offset: offset + limit]
    return {"items": page, "total": total}


def get(record_id: str) -> dict:
    """按 id 取一条记录。"""
    if not _HISTORY_FILE.exists():
        return None
    with _HISTORY_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                it = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning("历史记录文件存在坏行，已跳过（%s）: %s", e, line)
                continue
            if it.get("id") == record_id:
                return it
    return None


def delete(record_id: str) -> bool:
    """按 id 删除一条记录（重建文件）。"""
    if not _HISTORY_FILE.exists():
        return False
    with _LOCK:
        lines = []
        found = False
        with _HISTORY_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    it = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning("历史记录文件存在坏行，已跳过（%s）: %s", e, line)
                    continue
                if it.get("id") == record_id:
                    found = True
                    continue
                lines.append(line)
        if found:
            _ensure_dir()
            with _HISTORY_FILE.open("w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
                f.flush()
    return found
