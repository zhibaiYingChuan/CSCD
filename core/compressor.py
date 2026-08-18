"""
C-S-C-D 程序级压缩器（混合方案·运行时部分）
============================================
本模块实现「混合方案」中协议层无法兑现、必须由程序强制的部分：
- 根据 ratio 对上一轮 COMBINE 输出做确定性压缩，生成下一轮递归的输入摘要；
- 不依赖模型自律，避免「标签漂移 / 压缩被忽略」问题。

压缩策略（确定性、可复现）：
1. 优先抽取模型已生成的 `<<<summary>>>` 块（若含 key_points 一并保留）；
2. 缺失 summary 时，按 ratio 截断正文（保留前 ratio 比例字符，并尽量在句边界截断）；
3. 始终附加 `key_points` / `need_review` 透传，供下一轮上下文使用。

注意：压缩比是"目标上限"，实际输出以抽取到的 summary 为准；本模块不做语义重写，
只做结构化抽取 + 受控截断，确保确定性（同一输入同 ratio 必得同输出）。
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CompressResult:
    summary: str                       # 压缩后的摘要文本
    key_points: list = field(default_factory=list)
    need_review: list = field(default_factory=list)
    next_round_context: str = ""       # 拼好的下一轮递归输入前缀
    method: str = "summary"            # summary=抽取模型摘要 / truncate=截断


def _extract_summary_block(body: str) -> Optional[str]:
    """从一段文本中抽取 <<<summary>>>...</<<<summary>>> 块内容。"""
    if "<<<summary>>>" not in body:
        return None
    seg = body.split("<<<summary>>>", 1)[1]
    if "<<</summary>>>" in seg:
        seg = seg.split("<<</summary>>>", 1)[0]
    return seg.strip() or None


def _extract_fields(seg: str):
    """从 summary 块内按行抽取 key_points / need_review。"""
    kps, nrs = [], []
    for ln in seg.splitlines():
        s = ln.strip()
        if s.startswith("key_points"):
            v = s.split(":", 1)[1].strip() if ":" in s else s
            if v:
                kps.append(v)
        elif s.startswith("need_review"):
            v = s.split(":", 1)[1].strip() if ":" in s else s
            if v and v != "无":
                nrs.append(v)
    return kps, nrs


def _truncate(text: str, ratio: float) -> str:
    """按 ratio 保留前 ratio 比例字符，并尽量在句边界（。！？\n）截断。"""
    if not text:
        return ""
    keep = max(1, int(len(text) * ratio))
    if keep >= len(text):
        return text
    cut = text[:keep]
    # 向后找到最近的句边界
    m = re.search(r"[。！？\n]", text[keep:])
    if m:
        cut = text[:keep + m.end()]
    return cut.strip()


def compress_summary(text: str, ratio: float = 0.5) -> CompressResult:
    """对一段 C-S-C-D 轨迹（通常是上一轮 COMBINE 或全轮）做程序级压缩。

    Args:
        text: 待压缩的文本（四阶轨迹或单阶内容）。
        ratio: 目标压缩比（summary 缺失时用于截断正文）。
    Returns:
        CompressResult：含 summary / key_points / need_review / next_round_context。
    """
    ratio = min(1.0, max(0.05, ratio))

    # 1) 尝试抽取模型已生成的 summary
    block = _extract_summary_block(text)
    if block:
        kps, nrs = _extract_fields(block)
        summary = block
        method = "summary"
    else:
        # 2) 退化为受控截断（尽量保留 COMBINE 段）
        from core.marks import parse_marks
        sections = parse_marks(text)
        src = (sections.get("COMBINE") or text)
        summary = _truncate(src, ratio)
        kps, nrs = [], []
        method = "truncate"

    next_ctx = summary
    if nrs:
        next_ctx += "\n[待回溯] " + "; ".join(nrs)

    return CompressResult(
        summary=summary,
        key_points=kps,
        need_review=nrs,
        next_round_context=next_ctx,
        method=method,
    )
