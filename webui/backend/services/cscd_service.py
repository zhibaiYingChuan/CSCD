# -*- coding: utf-8 -*-
"""
C-S-C-D 推理服务层
==================
封装 core.cscd 的 CscdEngine 为 WebUI 可调用的推理服务。
与 cscd_mcp_server 的 cscd_reason 使用**同一个引擎**（OpenAICarrier + CscdEngine），
区别仅在入口：本服务由 FastAPI 直接调用，不经过 MCP 客户端进程。

环境变量：
  OPENAI_BASE_URL  模型端点（必填，如 https://api.deepseek.com）
  OPENAI_API_KEY   API Key（必填）
  OPENAI_MODEL     模型名（可选，默认 deepseek-chat）
"""

import os
import sys
from pathlib import Path

# 允许从 cscd 根目录导入 core 与 carriers
ROOT = Path(__file__).resolve().parent.parent.parent.parent  # webui/backend/services -> cscd/
sys.path.insert(0, str(ROOT))

from core.cscd import CscdEngine, load_config
from carriers.openai_carrier import OpenAICarrier


class CscdService:
    """WebUI 的推理服务门面：一个 reason() 方法，隐藏引擎装配细节。"""

    def __init__(self):
        self._engine = None
        # 支持两套变量：LLM_* 与 OPENAI_*（LLM_* 优先）。模型名不预设默认值，
        # 由用户显式配置，避免锁死某一家模型（可复现性）。
        self.base_url = os.getenv("LLM_API_URL") or os.getenv("OPENAI_BASE_URL", "")
        self.api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        self.model = os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or ""

    def ready(self) -> bool:
        """服务是否可推理（模型端点 + 模型名均已配置）。"""
        return bool(self.base_url and self.api_key and self.model)

    def missing_env(self) -> str:
        """返回缺失的环境变量引导信息；已配置则返回空串。

        模型名由用户显式配置（LLM_MODEL 或 OPENAI_MODEL，如 deepseek-chat / gpt-4o /
        claude-... / 你的本地模型），不预设默认值。
        """
        missing = []
        if not self.base_url:
            missing.append("LLM_API_URL / OPENAI_BASE_URL")
        if not self.api_key:
            missing.append("LLM_API_KEY / OPENAI_API_KEY")
        if not self.model:
            missing.append("LLM_MODEL / OPENAI_MODEL")
        if missing:
            return "缺少环境变量: " + ", ".join(missing) + \
                   "（例：LLM_API_URL=https://api.deepseek.com、LLM_API_KEY=sk-...、" \
                   "LLM_MODEL=deepseek-chat；或 OPENAI_BASE_URL/OPENAI_API_KEY/OPENAI_MODEL）"
        return ""

    def _ensure_engine(self) -> CscdEngine:
        if not self.ready():
            raise RuntimeError(self.missing_env())
        if self._engine is None:
            carrier = OpenAICarrier(self.model, self.base_url, self.api_key)
            self._engine = CscdEngine(carrier, load_config())
        return self._engine

    def reason(self, question: str,
               has_untrusted_input: bool = False,
               named_modules: list = None,
               task_id: str = None) -> dict:
        """执行一次完整 CSCD 推理，返回结构化结果（含轨迹/缓存/Token 统计）。

        Args:
            task_id: 可选，账本 ID（同一 ID 多次调用续跑同一账本，支持 resume）。
        """
        engine = self._ensure_engine()
        try:
            r = engine.run(
                question,
                has_untrusted_input=has_untrusted_input,
                named_modules=named_modules or [],
                task_id=task_id,
            )
        except Exception as e:
            # 包装底层模型/网络异常为可读信息，避免 FastAPI 返回裸 500
            raise RuntimeError(
                f"推理调用失败（{type(e).__name__}）：{e}"
            ) from e
        # 回传结构化结果：终端结论 + 审计轨迹 + 元数据
        return {
            "question": question,
            "reason": r.reason,                # 终端回传（基线或精炼结论）
            "final_context": r.final_context,  # 程序级压缩后的最终输出
            "raw_reason": r.raw_reason,        # 最后一轮完整四阶轨迹（审计）
            "summaries": r.summaries,          # 每轮压缩摘要
            "compress_methods": r.compress_methods,
            "task_type": str(getattr(r, "task_type", "")),
            "complexity": str(getattr(r, "complexity", "")),
            "strategy": r.strategy,
            "rounds": r.rounds,                # 实际轮次
            "planned_rounds": r.planned_rounds,
            "marks_valid": r.marks_valid,
            "missing_marks": r.missing_marks,
            "cache_hits": r.cache_hits,
            "cache_saved_tokens": r.cache_saved_tokens,
            "total_completion_tokens": r.total_completion_tokens,
            "pass_level": getattr(r, "pass_level", "fast"),
            "loaded_modules": getattr(r, "loaded_modules", []),
            # 推理时认知控制审计（J-Space/dsh 补全）
            "cognition": getattr(r, "cognition", {}),
            # 运行时状态外化账本审计（P4）
            "ledger": getattr(r, "ledger", {}),
        }


_service = None


def get_service() -> CscdService:
    """单例获取服务实例。"""
    global _service
    if _service is None:
        _service = CscdService()
    return _service
