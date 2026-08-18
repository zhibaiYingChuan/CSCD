# -*- coding: utf-8 -*-
"""
C-S-C-D · 独立 REST API 服务（Phase 4 规模化）
================================================
把 CscdEngine 暴露为面向第三方/Agent 的 REST API，供 SDK 或任意 HTTP 客户端调用。
相对 WebUI 后端，本服务面向「规模化」：
  - API Key 鉴权（支持独立凭证 CSCD_API_KEY，回退模型 Key）
  - 用量统计 / 计费审计（每次调用落账，含 token 计量，api_key 哈希存储）
  - 独立端口，可服务化部署（systemd / Docker / 反向代理）

端点：
  GET  /health                   健康检查
  POST /v1/reason                执行 CSCD 推理（鉴权）
  GET  /v1/usage                 用量统计（鉴权，可选 query: limit）
  GET  /v1/usage/all             全部用量（需 CSCD_ADMIN_KEY 管理员凭证）

鉴权模式：
  1. 推荐：设置 CSCD_API_KEY 作为独立 API 鉴权凭证
  2. 回退：自动扫描模型 Key（CSCD_API_KEYS / LLM_API_KEY / ...）
  3. 管理员：/v1/usage/all 需 CSCD_ADMIN_KEY 环境变量

运行：
  export CSCD_API_KEY="sk-your-api-key"          # 推荐：独立鉴权凭证
  export CSCD_ADMIN_KEY="sk-admin-key"           # 可选：管理员凭证
  export CSCD_ALLOW_ORIGINS="http://127.0.0.1:8000,http://localhost:8000"  # 可选：CORS 白名单（逗号分隔）
  export LLM_API_URL="https://api.deepseek.com"
  export LLM_API_KEY="sk-..."
  export LLM_MODEL="deepseek-chat"
  python api_server.py                           # 默认 127.0.0.1:8001
"""

import hashlib
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

# 复用 WebUI 的推理门面（同一引擎）
sys.path.insert(0, str(ROOT / "webui" / "backend"))
from services.cscd_service import CscdService, get_service

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("api_server")

app = FastAPI(
    title="C-S-C-D REST API",
    description="结构化推理编排协议的可规模化 REST 接口（鉴权 + 用量统计）",
    version="1.0.0",
)

# ---------- CORS 配置 ----------
_origins_str = os.getenv("CSCD_ALLOW_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000")
_ALLOW_ORIGINS = [o.strip() for o in _origins_str.split(",") if o.strip()]
_IS_WILDCARD_ORIGIN = "*" in _ALLOW_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOW_ORIGINS,
    allow_credentials=not _IS_WILDCARD_ORIGIN,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 鉴权配置 ----------
# 优先使用独立凭证 CSCD_API_KEY，未配置时回退扫描模型 Key
_CSCD_API_KEY = (os.getenv("CSCD_API_KEY") or "").strip()
_CSCD_ADMIN_KEY = (os.getenv("CSCD_ADMIN_KEY") or "").strip()

# 收集模型 Key 作为回退白名单
_API_KEY_VARS = (
    "CSCD_API_KEYS",       # 显式配置（逗号分隔）
    "LLM_API_KEY",         # 本机实测端点
    "OPENAI_API_KEY",      # OpenAI 兼容
    "DEEPSEEK_API_KEY",    # DeepSeek
    "ANTHROPIC_API_KEY",   # Anthropic
    "OPENROUTER_API_KEY",  # OpenRouter
)


def _discover_api_keys() -> list:
    """自动扫描环境变量中的已有模型 Key，去重后作为鉴权白名单。"""
    keys = []
    for var in _API_KEY_VARS:
        val = (os.getenv(var) or "").strip()
        if not val:
            continue
        if var == "CSCD_API_KEYS":
            keys.extend(k.strip() for k in val.split(",") if k.strip())
        elif val:
            keys.append(val)
    seen = set()
    return [k for k in keys if k and not (k in seen or seen.add(k))]


if _CSCD_API_KEY:
    # 独立凭证模式：仅接受 CSCD_API_KEY
    _ALLOWED_KEYS = [_CSCD_API_KEY]
    _AUTH_REQUIRED = True
    logger.info("已启用独立鉴权凭证（CSCD_API_KEY）")
else:
    # 回退模式：自动扫描已配置的模型 Key
    _ALLOWED_KEYS = _discover_api_keys()
    _AUTH_REQUIRED = bool(_ALLOWED_KEYS)
    if _AUTH_REQUIRED:
        logger.warning("正在使用模型 key 作为 API 鉴权，建议设置 CSCD_API_KEY 独立凭证")


# ---------- 用量统计（落盘，追加式） ----------
_USAGE_FILE = ROOT / ".cscd" / "usage.jsonl"


def _record_usage(api_key: str, payload: dict):
    """记录用量到文件；api_key 仅存 SHA-256 前 12 位哈希，不留明文。"""
    _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:12]
    entry = {
        "api_key": key_hash,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_completion_tokens": payload.get("total_completion_tokens", 0),
        "rounds": payload.get("rounds", 0),
        "cache_hits": payload.get("cache_hits", 0),
        "complexity": payload.get("complexity", ""),
        "marks_valid": payload.get("marks_valid", True),
    }
    import json as _json
    try:
        with _USAGE_FILE.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("用量记录写入失败: %s", exc)


# ---------- 鉴权依赖 ----------
def require_key(x_api_key: str = Header(None, alias="X-API-Key")) -> str:
    """API Key 鉴权：请求头 X-API-Key 须在白名单内。

    白名单优先使用 CSCD_API_KEY 独立凭证，未配置时自动扫描模型 Key
    （CSCD_API_KEYS / LLM_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY /
    ANTHROPIC_API_KEY / OPENROUTER_API_KEY）。未配置任何 Key 则不鉴权（内网模式）。
    """
    if not _AUTH_REQUIRED:
        return x_api_key or "anonymous"
    if not x_api_key or x_api_key not in _ALLOWED_KEYS:
        raise HTTPException(status_code=401, detail="无效或缺失的 API Key")
    return x_api_key


def require_admin_key(x_api_key: str = Header(None, alias="X-API-Key")) -> str:
    """管理员鉴权：仅接受 CSCD_ADMIN_KEY 环境变量配置的 Key。"""
    if not _CSCD_ADMIN_KEY:
        raise HTTPException(
            status_code=403,
            detail="管理员接口未启用（未配置 CSCD_ADMIN_KEY 环境变量）",
        )
    if not x_api_key or x_api_key != _CSCD_ADMIN_KEY:
        raise HTTPException(status_code=403, detail="无效的管理员 Key")
    return x_api_key


# ---------- 模型 ----------
class ReasonRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=20000, description="用户问题")
    has_untrusted_input: bool = Field(False)
    named_modules: Optional[list] = Field(None, description="显式指定的 J-Space 模块名")
    task_id: Optional[str] = Field(None, description="账本 ID（同一 ID 多次调用续跑同一账本，支持 resume）")

    @field_validator("question")
    def question_not_blank(cls, v):
        stripped = v.strip()
        if not stripped:
            raise ValueError("question 不能为空或纯空格")
        return stripped


# ---------- 端点 ----------
@app.get("/health")
def health():
    svc = get_service()
    return {"status": "ok", "ready": svc.ready(), "model": svc.model, "auth_required": _AUTH_REQUIRED}


@app.post("/v1/reason")
def reason(req: ReasonRequest, key: str = Depends(require_key)):
    svc = get_service()
    if not svc.ready():
        raise HTTPException(status_code=503, detail=svc.missing_env())
    try:
        result = svc.reason(
            req.question,
            has_untrusted_input=req.has_untrusted_input,
            named_modules=req.named_modules,
            task_id=req.task_id,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    # 用量记录：失败仅告警，不中断主流程
    try:
        _record_usage(key, result)
    except Exception as exc:
        logger.warning("用量记录失败（不影响主流程）: %s", exc)
    return result


@app.get("/v1/usage")
def usage(limit: int = Query(100, ge=1, le=500), key: str = Depends(require_key)):
    """查看当前 key 的用量统计。"""
    return _read_usage(key, limit)


@app.get("/v1/usage/all")
def usage_all(limit: int = Query(100, ge=1, le=500), key: str = Depends(require_admin_key)):
    """管理员：查看全部 key 的用量（需 CSCD_ADMIN_KEY 环境变量）。"""
    return _read_usage(None, limit)


def _read_usage(filter_key: Optional[str], limit: int):
    if not _USAGE_FILE.exists():
        return {"total_calls": 0, "total_completion_tokens": 0, "items": []}
    import json as _json
    filter_hash = hashlib.sha256(filter_key.encode()).hexdigest()[:12] if filter_key else None
    items = []
    with _USAGE_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                it = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            if filter_hash and it.get("api_key") != filter_hash:
                continue
            items.append(it)
    total_calls = len(items)
    total_tokens = sum(it.get("total_completion_tokens", 0) for it in items)
    return {
        "total_calls": total_calls,
        "total_completion_tokens": total_tokens,
        "items": items[-limit:],
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("CSCD_API_PORT", "8001"))
    uvicorn.run("api_server:app", host="0.0.0.0", port=port)