# -*- coding: utf-8 -*-
"""FastAPI 请求/响应 Pydantic 模型。"""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class ReasonRequest(BaseModel):
    """POST /api/reason 请求体。"""
    question: str = Field(..., min_length=1, max_length=20000, description="用户问题")
    has_untrusted_input: bool = Field(
        False, description="是否含不可信输入（强制 introspection，禁用方向Y 短路）"
    )
    named_modules: Optional[List[str]] = Field(
        None, description="显式指定要加载的 J-Space 模块名"
    )
    task_id: Optional[str] = Field(None, description="账本 ID（同一 ID 多次调用续跑同一账本，支持 resume）")

    @field_validator("question")
    @classmethod
    def _strip_question(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question 不能为空或全为空白字符")
        return v


class ReasonResponse(BaseModel):
    """POST /api/reason 响应体（结构化推理结果）。"""
    question: str
    reason: str
    final_context: str
    raw_reason: str = ""
    summaries: List[str] = Field(default_factory=list)
    compress_methods: List[str] = Field(default_factory=list)
    task_type: str = ""
    complexity: str = ""
    strategy: str = ""
    rounds: int = 1
    planned_rounds: int = 1
    marks_valid: bool = True
    missing_marks: List[str] = Field(default_factory=list)
    cache_hits: int = 0
    cache_saved_tokens: int = 0
    total_completion_tokens: int = 0
    pass_level: str = "fast"
    loaded_modules: List[str] = Field(default_factory=list)
    cognition: dict = Field(default_factory=dict, description="推理时认知控制审计（工作空间/稠密轨/桥接/元认知/锚定）")
    ledger: dict = Field(default_factory=dict, description="运行时状态外化账本审计（task_id/条目数/最后交付物）")


class StatusResponse(BaseModel):
    """GET /api/status 响应体。"""
    status: str
    ready: bool
    model: str
    base_url: str = ""  # 已配置的端点（部署向导自动填充用）
    message: str = ""


class HistoryItem(BaseModel):
    """一条历史调用记录。"""
    id: str
    question: str
    reason: str
    complexity: str
    strategy: str
    rounds: int
    marks_valid: bool
    cache_hits: int
    total_completion_tokens: int
    created_at: str


class HistoryListResponse(BaseModel):
    """GET /api/history 响应体。"""
    items: List[HistoryItem]
    total: int
