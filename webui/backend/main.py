# -*- coding: utf-8 -*-
"""
C-S-C-D 可视化调用界面 · FastAPI 后端
====================================
对接 core.cscd 的 CscdEngine（与 MCP cscd_reason 同一引擎），提供：

  GET  /api/status        服务状态
  POST /api/reason        执行一次 CSCD 推理
  GET  /api/history       历史记录（搜索/分页）
  DELETE /api/history/{id} 删除一条记录
  GET  /api/export/{id}   导出某次记录（JSON）
  GET  /                  返回前端页面（静态托管）

运行：
  export OPENAI_BASE_URL="https://api.deepseek.com"
  export OPENAI_API_KEY="sk-..."
  cd cscd/webui/backend
  uvicorn main:app --host 0.0.0.0 --port 8000
"""

import logging
import os
import sys
from pathlib import Path

# 允许从 cscd 根目录导入 core / carriers
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from models.schemas import (
    ReasonRequest, ReasonResponse, StatusResponse,
    HistoryItem, HistoryListResponse,
)
from services.cscd_service import get_service
from storage import history as history_store

logger = logging.getLogger(__name__)

app = FastAPI(
    title="C-S-C-D 推理可视化界面",
    description="结构化推理编排协议的正式产品入口：输入任务，获得可追溯的四阶推理结果。",
    version="1.0.0",
)

# CORS：默认仅允许本机前端源 http://127.0.0.1:8000
# 可通过环境变量 CSCD_WEB_ALLOW_ORIGINS 逗号分隔覆盖（如 http://localhost:5173,http://192.168.1.2:8000）
# 注意：allow_origins 含 "*" 时不能与 allow_credentials=True 同时使用
_allow_origins = [
    o.strip()
    for o in os.getenv("CSCD_WEB_ALLOW_ORIGINS", "http://127.0.0.1:8000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/status", response_model=StatusResponse)
def status():
    svc = get_service()
    ready = svc.ready()
    return StatusResponse(
        status="ok" if ready else "not_ready",
        ready=ready,
        model=svc.model,
        base_url=svc.base_url,
        message="" if ready else svc.missing_env(),
    )


@app.get("/health")
def health():
    """统一健康检查（与 REST API api_server 一致），供一键启动脚本 / 用户快速验证。"""
    svc = get_service()
    return {"status": "ok", "ready": svc.ready(), "model": svc.model}


@app.post("/api/reason", response_model=ReasonResponse)
def reason(req: ReasonRequest):
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

    # 落库（失败不阻断推理结果返回；仅记录核心审计字段）
    try:
        history_store.add({
            "question": req.question,
            "reason": result["reason"],
            "complexity": result["complexity"],
            "strategy": result["strategy"],
            "rounds": result["rounds"],
            "marks_valid": result["marks_valid"],
            "cache_hits": result["cache_hits"],
            "total_completion_tokens": result["total_completion_tokens"],
            "full": result,  # 完整轨迹用于导出
        })
    except Exception as e:
        logger.warning("历史记录落库失败（不影响推理结果）: %s", e)
    return ReasonResponse(**result)


@app.get("/api/history", response_model=HistoryListResponse)
def list_history(
    q: str = Query("", description="按问题/结论模糊搜索"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    data = history_store.list_all(query=q, limit=limit, offset=offset)
    items = [
        HistoryItem(
            id=it.get("id", ""),
            question=it.get("question", ""),
            reason=it.get("reason", ""),
            complexity=it.get("complexity", ""),
            strategy=it.get("strategy", ""),
            rounds=it.get("rounds", 1),
            marks_valid=it.get("marks_valid", True),
            cache_hits=it.get("cache_hits", 0),
            total_completion_tokens=it.get("total_completion_tokens", 0),
            created_at=it.get("created_at", ""),
        )
        for it in data["items"]
    ]
    return HistoryListResponse(items=items, total=data["total"])


@app.delete("/api/history/{record_id}")
def delete_history(record_id: str):
    if not history_store.delete(record_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"deleted": True}


@app.get("/api/export/{record_id}")
def export_history(record_id: str):
    it = history_store.get(record_id)
    if not it:
        raise HTTPException(status_code=404, detail="记录不存在")
    return it.get("full", it)


# 前端静态目录（纯 HTML/CSS/JS）——必须在 mount 前定义
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/deploy")
def deploy():
    """可视化部署向导页（用户下载仓库后的第一入口）。"""
    from fastapi.responses import HTMLResponse
    deploy_file = _FRONTEND_DIR / "deploy.html"
    if deploy_file.exists():
        return HTMLResponse(deploy_file.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail="部署向导页面缺失")


# 前端静态目录 mount 必须放在所有 API 路由之后，
# 否则 mount("/") 会先于 /api/* 匹配，遮蔽 API 路由。
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
else:
    logger.warning("前端静态目录不存在，跳过挂载: %s", _FRONTEND_DIR)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
