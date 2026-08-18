"""
C-S-C-D MCP Server
==================
将 C-S-C-D 推理协议封装为 MCP Server，使任何支持 MCP 的 AI 工具
（Continue / Cline / Cursor / Claude Desktop 等）以标准化方式：

  1. 读取协议 System Prompt（resource: cscd://system-prompt）
  2. 在模型调用前将其注入 System Prompt（客户端职责）
  3. 把模型产出的推理轨迹回传校验/抽取（tools）

运行：
  python cscd_mcp_server.py        # 默认 stdio 传输（MCP 客户端直接拉起）
  # 或在支持 sse 的网关里以 server 模式挂载

依赖：pip install mcp
"""

import os
import re
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP

# 复用既有协议层：校验/抽取直接用 core.marks，协议文本从模板抽取
from carriers.openai_carrier import load_cscd_system, OpenAICarrier

mcp = FastMCP("cscd-protocol")

# ---------- 调用网关状态（方案B：强制 Agent 先调用 cscd_reason 再使用其他工具） ----------
# 解决"工具存在但 Agent 不主动、不正确使用"的核心矛盾：
# 未先推理时，其他"消费推理产物"的工具被拒绝，强制 Agent 把 cscd_reason 当作必经入口。
#
# 注意：_call_state 是模块级可变全局，语义为「进程级一次推理解锁」（闩锁），而非「每请求独立」。
# 这意味着同进程内任意请求推理成功后，后续 validate/extract/compress 均能通过网关——
# 包括 B 请求在 A 请求推理成功后的调用。这是设计意图（简化 MCP 会话内工作流约束，
# 避免逐请求追踪归属），但务必知晓它并非请求级鉴权（issue 17 确认设计，补充注释说明）。
_call_state = {"reasoned": False}

# 豁免工具：这些是"前置/辅助"能力，不消费推理产物，无需先推理。
_GATE_EXEMPT_TOOLS = {
    "cscd_reason",        # 必经入口本身
    "get_cscd_system_prompt",  # 协议注入前置
    "cscd_ledger",        # 账本查看/记录（辅助，不消费推理结论）
}


def _require_reasoned(tool_name: str):
    """调用网关：除豁免工具外，其余工具须先完成 cscd_reason 推理。"""
    if tool_name in _GATE_EXEMPT_TOOLS:
        return None
    if not _call_state["reasoned"]:
        return (
            "⚠️ 工作流约束：必须先调用 `cscd_reason` 完成推理，才能使用 "
            f"`{tool_name}`。\n"
            "流程：1) cscd_reason(你的问题) 获得 final_context → "
            "2) 基于 final_context 开展工作 → 3) 需要校验/抽取/压缩时再调用本工具。"
        )
    return None

# 推理引擎所需模型配置（默认读取环境变量，便于服务化部署）。
# 支持两套变量：LLM_* 与 OPENAI_*（LLM_* 优先）。模型名不预设默认值，
# 由用户显式配置（可复现性，避免锁死某一家模型）。
_ENGINE_BASE_URL = os.getenv("LLM_API_URL") or os.getenv("OPENAI_BASE_URL", "")
_ENGINE_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
_ENGINE_MODEL = (os.getenv("LLM_MODEL") or os.getenv("CSCD_MODEL")
                 or os.getenv("OPENAI_MODEL") or "")

# 模块级引擎缓存（issue 17：避免每次 cscd_reason 重建 CscdEngine/重载配置）
# 多线程安全：双检锁（double-checked locking），cscd_reason 可被并发调用。
_ENGINE_CACHE = None
_ENGINE_LOCK = threading.Lock()


def _make_engine():
    """按环境变量实例化 CscdEngine（OpenAI 兼容 Carrier）。

    未配置 base_url/api_key/model 时抛出清晰错误，引导调用方设置环境变量。
    模型名由用户显式配置（LLM_MODEL/CSCD_MODEL/OPENAI_MODEL），不预设默认。
    引擎为进程级单例缓存（首次构建后复用），减少重复加载；配置变更需重启进程生效。
    """
    if not _ENGINE_BASE_URL or not _ENGINE_API_KEY or not _ENGINE_MODEL:
        raise RuntimeError(
            "cscd_reason 需要配置模型端点与模型名：请设置环境变量 "
            "LLM_API_URL / OPENAI_BASE_URL、LLM_API_KEY / OPENAI_API_KEY、"
            "LLM_MODEL / OPENAI_MODEL（如 deepseek-chat / gpt-4o / claude-... / 你的模型）。"
        )
    global _ENGINE_CACHE
    if _ENGINE_CACHE is None:
        with _ENGINE_LOCK:
            if _ENGINE_CACHE is None:
                from core.cscd import CscdEngine, load_config
                carrier = OpenAICarrier(_ENGINE_MODEL, _ENGINE_BASE_URL, _ENGINE_API_KEY)
                _ENGINE_CACHE = CscdEngine(carrier, load_config())
    return _ENGINE_CACHE


# ---------- Resource：协议 System Prompt ----------
@mcp.resource("cscd://system-prompt")
def cscd_system_prompt() -> str:
    """返回完整的 C-S-C-D 协议 System Prompt，供客户端注入模型调用。"""
    return load_cscd_system()


@mcp.resource("cscd://readme")
def cscd_readme() -> str:
    """返回协议使用说明（已知边界 / 调用示意）。"""
    p = ROOT / "cscd-system-prompt.md"
    return p.read_text(encoding="utf-8") if p.exists() else "协议模板文件缺失。"


@mcp.resource("cscd://agent-guide")
def cscd_agent_guide() -> str:
    """返回宿主 Agent 的调用引导规则：何时调用 CSCD 工具、按什么顺序调用。

    这是让「模型能够主动调用」的关键：告诉宿主模型在什么条件下该触发 CSCD，
    以及协议路径 vs 短路路径的选择。客户端应在注入协议 system 的同时读取本 guide。
    """
    p = ROOT / "cscd-agent-guide.md"
    return p.read_text(encoding="utf-8") if p.exists() else "Agent 调用引导文件缺失。"


# ---------- Tool：取协议 ----------
@mcp.tool()
def get_cscd_system_prompt() -> str:
    """获取 C-S-C-D 协议 System Prompt 文本。客户端应在每次推理调用前将其作为 system 消息注入。"""
    return load_cscd_system()


# ---------- Tool：校验轨迹 ----------
@mcp.tool()
def validate_cscd_trace(trace: str) -> dict:
    """校验一段模型输出是否满足四阶标记结构（DECOMPOSE/CLASSIFY/SELECT/COMBINE 成对、顺序、非空）。

    Args:
        trace: 模型产出的推理文本（应含四阶标记）。
    Returns:
        {ok, missing, ordered, empty_segments}
    """
    gate = _require_reasoned("validate_cscd_trace")
    if gate:
        return {"gate_required": True, "message": gate, "ok": False, "missing": [], "ordered": False, "empty_segments": []}
    from core.marks import validate_marks
    vr = validate_marks(trace)
    # 顺序校验：用正则 re.search 确认四阶标记的首次出现位置递增，大小写不敏感（issue 17）
    order = ["DECOMPOSE", "CLASSIFY", "SELECT", "COMBINE"]
    positions = []
    for m in order:
        mt = re.search(rf"<{m}>", trace, re.IGNORECASE)
        positions.append(mt.start() if mt else -1)
    ordered = (all(p != -1 for p in positions)
               and all(positions[i] < positions[i + 1] for i in range(len(order) - 1)))
    empty = [k for k, v in vr.sections.items() if not (v or "").strip()]
    return {
        "ok": vr.ok,
        "missing": vr.missing,
        "ordered": ordered,
        "empty_segments": empty,
    }


# ---------- Tool：抽取各阶内容 ----------
@mcp.tool()
def extract_cscd_marks(trace: str) -> dict:
    """从模型输出中抽取四阶标记内容，便于做结构比对或审计。

    Args:
        trace: 模型产出的推理文本。
    Returns:
        {DECOMPOSE, CLASSIFY, SELECT, COMBINE} 各段文本（缺失则为空串）
    """
    gate = _require_reasoned("extract_cscd_marks")
    if gate:
        return {"gate_required": True, "message": gate,
                "DECOMPOSE": None, "CLASSIFY": None, "SELECT": None, "COMBINE": None}
    from core.marks import parse_marks
    return parse_marks(trace)


# ---------- Tool：程序侧递归压缩（阶段B 预埋·混合方案运行时部分） ----------
@mcp.tool()
def compress_cscd_round(trace: str, ratio: float = 0.5) -> dict:
    """对一轮 C-S-C-D 轨迹做程序级压缩，提取摘要作为**替代原始全量**的最终上下文。

    这是「混合方案」中**运行时才能兑现**的部分：协议层只约束模型输出 <<<summary>>> 结构，
    本工具在程序侧对四阶做确定性抽取（非模型自律），返回的 `next_round_context` **替代**
    原始全量轨迹回传给调用方，从而真实削减终端 Token（替代式压缩，而非追加）。

    Args:
        trace: 模型产出的四阶轨迹（可含 <<<summary>>> 缩略图）。
        ratio: 目标压缩比（仅作标注，实际压缩以抽取 summary/key_points 为准）。
    Returns:
        {summary_text, key_points, need_review, next_round_context}
    """
    gate = _require_reasoned("compress_cscd_round")
    if gate:
        return {"gate_required": True, "message": gate,
                "summary_text": "", "key_points": [], "need_review": [],
                "next_round_context": "", "target_ratio": ratio}
    from core.marks import parse_marks
    sections = parse_marks(trace)
    summary_parts = []
    key_points = []
    need_review = []
    for stage, body in sections.items():
        if not (body or "").strip():
            continue
        # 优先取模型已生成的 <<<summary>>>；缺失则从正文首句近似
        if "<<<summary>>>" in body:
            seg = body.split("<<<summary>>>", 1)[1]
            seg = seg.split("<<</summary>>>", 1)[0].strip()
        else:
            seg = (body.strip().splitlines() or [""])[0][:120]
        summary_parts.append(f"[{stage}] {seg}")
        # 在 summary 段内按行提取 key_points / need_review（避免误抓正文）
        kp_val = nr_val = None
        for ln in seg.splitlines():
            s = ln.strip()
            if s.startswith("key_points"):
                kp_val = s.split(":", 1)[1].strip() if ":" in s else s
            elif s.startswith("need_review"):
                nr_val = s.split(":", 1)[1].strip() if ":" in s else s
        if kp_val:
            key_points.append(f"{stage}: {kp_val}")
        if nr_val and nr_val != "无":
            need_review.append(f"{stage}: {nr_val}")
    summary_text = "\n".join(summary_parts)
    next_round_context = summary_text + ("\n[待回溯] " + "; ".join(need_review) if need_review else "")
    return {
        "summary_text": summary_text,
        "key_points": key_points,
        "need_review": need_review,
        "next_round_context": next_round_context,
        "target_ratio": ratio,
    }


# ---------- Tool：完整推理（形态B 推理网关的高层入口） ----------
@mcp.tool()
def cscd_reason(
    question: str,
    has_untrusted_input: bool = False,
    named_modules: list = None,
    task_id: str = None,
) -> dict:
    """对一个问题执行一次完整的 C-S-C-D 四阶递归推理，返回精炼结论（替代式）。

    这是「推理网关」形态的高层工具：调用方无需自行拼四阶、校验、压缩，一个调用即可
    拿到最终结论。内部依次完成：复杂度评估 → 动态轮次 → 方向Y 短路 / 协议递归 →
    程序级压缩 → 单原子缓存 → 认知控制 → 运行时账本外化。simple 任务自动短路走基线直答；
    medium/complex 走协议+缓存。

    Args:
        question: 用户问题。
        has_untrusted_input: 是否含不可信输入（强制 introspection，禁用方向Y 短路）。
        named_modules: 显式指定要加载的 J-Space 模块名。
        task_id: 可选，指定账本 task_id（同一 task_id 多次调用会把状态追加到同一账本，支持 resume）。

    Returns:
        {reason, final_context, complexity, strategy, task_type, rounds,
         marks_valid, cache_hits, planned_rounds, total_completion_tokens,
         cognition, ledger}
    """
    engine = _make_engine()
    r = engine.run(question, has_untrusted_input=has_untrusted_input,
                   named_modules=named_modules or [], task_id=task_id)
    # 推理成功后标记进程级网关（闩锁语义：非每请求独立，见 _call_state 注释）
    _call_state["reasoned"] = True
    return {
        "reason": r.reason,
        "final_context": r.final_context,
        "complexity": str(getattr(r, "complexity", "")),
        "strategy": r.strategy,
        "task_type": str(getattr(r, "task_type", "")),
        "rounds": r.rounds,
        "planned_rounds": r.planned_rounds,
        "marks_valid": r.marks_valid,
        "cache_hits": r.cache_hits,
        "total_completion_tokens": r.total_completion_tokens,
        "cognition": getattr(r, "cognition", {}),
        "ledger": getattr(r, "ledger", {}),
        "error": getattr(r, "error", ""),
    }


# ---------- Tool：运行时状态外化账本（P4） ----------
@mcp.tool()
def cscd_ledger(task_id: str, action: str = "view", payload: dict = None) -> dict:
    """查看 / 恢复 / 记录 C-S-C-D 推理的运行时状态外化账本（J-Space seam/note/ship/resume）。

    每轮推理的认知状态、轨迹摘要、交付物会被外化到 `.cscd/ledger/{task_id}.jsonl`，
    支持跨调用/跨会话的持久化与恢复续跑。

    Args:
        task_id: 账本 ID（与 cscd_reason 的 task_id 对应）。
        action: view（查看全部条目）| resume（恢复最后 note/seam 上下文）| note（记录状态）| ship（定稿）。
        payload: 当 action 为 note/ship 时传入的附加状态。

    Returns:
        {task_id, count, entries | resume | status}
    """
    from core.ledger import Ledger
    led = Ledger(task_id=task_id)
    action = (action or "view").lower()

    if action == "view":
        return {
            "task_id": led.task_id,
            "count": len(led.entries),
            "entries": led.history(),
        }
    if action == "resume":
        r = led.resume()
        return {
            "task_id": led.task_id,
            "count": len(led.entries),
            "resumed": r,
        }
    if action == "note":
        entry = led.note(**((payload or {})))
        return {"status": "noted", "task_id": led.task_id, "entry": entry}
    if action == "ship":
        p = payload or {}
        entry = led.ship(artifact=p.get("artifact", ""), summary=p.get("summary", ""))
        return {"status": "shipped", "task_id": led.task_id, "entry": entry}
    return {"error": f"未知 action: {action}，支持 view/resume/note/ship"}


if __name__ == "__main__":
    # stdio 传输：MCP 客户端（Continue/Cline 等）配置 command 拉起本文件即可
    mcp.run()
