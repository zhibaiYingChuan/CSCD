"""
四阶标记解析与校验（L4 认知控制 · 标记一致性）
=============================================
保证跨载体（OpenAI / CodeBuddy / DSH）输出的四阶语义一致。
所有 Carrier 在 reason() 后必须调用 validate_marks() 校验结构完整性。
"""

import re
from dataclasses import dataclass
from typing import Optional


# 四阶标记（与 protocol.md 对齐）。
# 容错正则：优先匹配成对闭合标签；若模型只输出开标签（真实端点常见标签漂移，
# 缺 </DECOMPOSE> 闭合），回退匹配到「下一标签或文本结尾」，保证内容仍可提取、校验不误报。
MARKS = {
    "DECOMPOSE": r"<DECOMPOSE>(.*?)(?:</DECOMPOSE>|(?=<CLASSIFY>|$))",
    "CLASSIFY":  r"<CLASSIFY>(.*?)(?:</CLASSIFY>|(?=<SELECT>|$))",
    "SELECT":    r"<SELECT>(.*?)(?:</SELECT>|(?=<COMBINE>|$))",
    "COMBINE":   r"<COMBINE>(.*?)(?:</COMBINE>|$)",
}


def _extract_stage(name: str, text: str) -> str:
    """容错提取单个阶段内容：优先闭合对；否则取开标签到下一标签/结尾。

    同时兼容方括号变体（[原子列表] 等 J-Space/模型自由输出形式），
    以「开标签存在 + 内容非空」为提取底线。
    """
    pat = MARKS[name]
    m = re.search(pat, text, re.DOTALL)
    if m:
        return (m.group(1) or "").strip()
    # 方括号变体回退：如 [原子列表] / [可执行结论] / [分类]
    alias = {
        "DECOMPOSE": r"\[原子列表\]\s*(.*?)(?=\[|$)",
        "CLASSIFY":  r"\[分类\]\s*(.*?)(?=\[|$)",
        "SELECT":    r"\[选择\]\s*(.*?)(?=\[|$)",
        "COMBINE":   r"\[可执行结论\]\s*(.*?)(?=\[|$)",
    }.get(name)
    if alias:
        m2 = re.search(alias, text, re.DOTALL)
        if m2:
            return (m2.group(1) or "").strip()
    return ""


@dataclass
class MarkResult:
    ok: bool
    missing: list[str] = None
    sections: dict = None

    def __post_init__(self):
        if self.missing is None:
            self.missing = []
        if self.sections is None:
            self.sections = {}


def parse_marks(text: str) -> dict:
    """提取四阶各段内容（不带标签）。缺失返回 None（兼容历史调用方）。"""
    out = {}
    for name in MARKS:
        val = _extract_stage(name, text or "")
        out[name] = val or None
    return out


def validate_marks(text: str) -> MarkResult:
    """
    校验四阶标记齐全。返回 MarkResult。

    宽松校验（容忍真实模型标签漂移）：
    - 优先要求四段成对闭合、顺序固定、非空；
    - 若某段仅开标签（缺闭合）也能提取出非空内容，则该段视为「存在」而非缺失，
      避免真实端点输出因缺一个 </DECOMPOSE> 而被整体误判 marks_valid=False。
    """
    if not text:
        return MarkResult(ok=False, missing=["DECOMPOSE", "CLASSIFY", "SELECT", "COMBINE"])
    sections = parse_marks(text)
    missing = [k for k in MARKS if not sections.get(k)]
    return MarkResult(ok=len(missing) == 0, missing=missing, sections=sections)


def count_atoms(decompose_text: str) -> int:
    """统计 DECOMPOSE 段中的原子项数（按行首数字/'-' 计数）。"""
    if not decompose_text:
        return 0
    lines = [l for l in decompose_text.splitlines() if re.match(r"^\s*(\d+[.、]|\-|\*)", l)]
    return len(lines)
