# -*- coding: utf-8 -*-
"""
C-S-C-D 一键启动（易用性入口）
================================
用户配置好模型端点后，用一条命令拉起并检查所有服务：
  - 自动检测已配置的模型端点（LLM_*/OPENAI_*/DEEPSEEK_* 等，无需二次配置）
  - 检查关键依赖是否安装
  - 可选启动 WebUI（端口 8000）与 REST API（端口 8001）
  - 输出清晰的就绪状态与接入指引

用法:
    python start_services.py                # 仅检查环境与端点就绪（推荐先跑）
    python start_services.py --webui        # 启动 WebUI 看板 (8000)
    python start_services.py --api          # 启动 REST API (8001)
    python start_services.py --all          # 同时启动 WebUI + REST API

说明：MCP Server 由 MCP 客户端（Continue/Cline/Claude Desktop）拉起，配置见
      `.mcp.example.json`，本脚本不负责启动 MCP 服务进程。
"""

import argparse
import importlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "webui" / "backend"))

# 模型端点变量（与 api_server._discover 一致）
_MODEL_VARS = {
    "LLM_API_URL": "LLM_API_KEY",
    "OPENAI_BASE_URL": "OPENAI_API_KEY",
    "DEEPSEEK_API_URL": "DEEPSEEK_API_KEY",
}
_REQUIRED_PKGS = ["fastapi", "uvicorn", "openai", "pydantic"]


def _detect_endpoint() -> tuple:
    """检测已配置的模型端点。返回 (base_url, api_key, model, source)。

    模型名由用户显式配置（LLM_MODEL/OPENAI_MODEL），不预设默认值（可复现性）。
    """
    for url_var, key_var in _MODEL_VARS.items():
        url = os.getenv(url_var)
        key = os.getenv(key_var)
        if url and key:
            model = (os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL")
                     or os.getenv("DEEPSEEK_MODEL") or "")
            return url, key, model, f"{url_var}/{key_var}"
    # 单独有 key 但无 url（部分工具只配 key）
    for key_var in ("LLM_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        if os.getenv(key_var):
            return "", os.getenv(key_var), "", key_var
    return "", "", "", ""


def _check_deps() -> list:
    """检查关键依赖是否安装，返回缺失列表。"""
    missing = []
    for pkg in _REQUIRED_PKGS:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)
    return missing


def _start_background(cmd: list, cwd: Path):
    """后台启动一个进程，并将输出写入统一日志文件。"""
    log_dir = ROOT / ".cscd" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "start_services.log"
    log_handle = log_file.open("a", encoding="utf-8")
    return subprocess.Popen(
        cmd, cwd=str(cwd), stdout=log_handle, stderr=subprocess.STDOUT
    )


def _port_is_listening(port: int) -> bool:
    """检查本机端口是否已监听。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main():
    parser = argparse.ArgumentParser(description="C-S-C-D 一键启动")
    parser.add_argument("--webui", action="store_true", help="启动 WebUI 看板 (8000)")
    parser.add_argument("--api", action="store_true", help="启动 REST API (8001)")
    parser.add_argument("--all", action="store_true", help="同时启动 WebUI + REST API")
    args = parser.parse_args()

    print("=" * 60)
    print("C-S-C-D 服务启动检查")
    print("=" * 60)

    # 1. 依赖检查
    missing = _check_deps()
    if missing:
        print(f"\n[❌] 缺少依赖: {', '.join(missing)}")
        print(f"     安装: pip install {' '.join(missing)}")
        sys.exit(1)
    print("[✅] 关键依赖已就绪 (fastapi/uvicorn/openai/pydantic)")

    # 2. 端点检测
    url, key, model, source = _detect_endpoint()
    if url and key and model:
        print(f"[✅] 模型端点已就绪 (来自 {source})")
        print(f"     base_url: {url}")
        print(f"     model   : {model}")
    elif url and key:
        print(f"[⚠️] 已检测到端点 ({source})，但未配置模型名。")
        print("     请设置 LLM_MODEL 或 OPENAI_MODEL（如 deepseek-chat / gpt-4o / claude-... / 你的本地模型）。")
    elif key:
        print(f"[⚠️] 检测到 API Key ({source})，但未配置 base_url 与模型名。")
        print("     请设置 LLM_API_URL 或 OPENAI_BASE_URL 指向你的 OpenAI 兼容端点，并配置 LLM_MODEL/OPENAI_MODEL。")
    else:
        print("[⚠️] 未检测到模型端点。")
        print("     请设置以下任一组合（或已在 AI 工具中配置过）：")
        print("       LLM_API_URL + LLM_API_KEY + LLM_MODEL")
        print("       OPENAI_BASE_URL + OPENAI_API_KEY + OPENAI_MODEL")
        print("       DEEPSEEK_API_URL + DEEPSEEK_API_KEY + LLM_MODEL")
        print("     （模型名如 deepseek-chat / gpt-4o / claude-...，不预设默认）")

    # 3. 启动服务
    if args.all:
        args.webui = args.api = True

    if args.webui or args.api:
        if not (url and key):
            print("\n[⚠️] 端点未就绪，服务可启动但 /api/reason 会返回 503 引导。")
        if args.webui:
            _start_background([sys.executable, "-m", "uvicorn", "main:app",
                               "--host", "127.0.0.1", "--port", "8000"],
                              ROOT / "webui" / "backend")
            print("[✅] WebUI 看板已启动:  http://127.0.0.1:8000")
        if args.api:
            _start_background([sys.executable, "-m", "uvicorn", "api_server:app",
                               "--host", "127.0.0.1", "--port", "8001"], ROOT)
            print("[✅] REST API 已启动:   http://127.0.0.1:8001")

        print("\n等待服务启动并检查端口...")
        time.sleep(3)
        for port in (8000, 8001):
            if (port == 8000 and args.webui) or (port == 8001 and args.api):
                if not _port_is_listening(port):
                    print(f"[⚠️] 端口 {port} 未监听，请查看 .cscd/logs/start_services.log")

        print("\n验证服务已就绪（注意两个服务健康检查路径不同）:")
        if args.webui:
            print("  WebUI  : curl http://127.0.0.1:8000/api/status   (返回 {\"status\":\"ok\"} 即就绪)")
        if args.api:
            print("  REST API: curl http://127.0.0.1:8001/health        (返回 {\"status\":\"ok\"} 即就绪)")
    else:
        # 仅检查模式：给出启动指引
        print("\n" + "=" * 60)
        print("接入指引")
        print("=" * 60)
        print("  WebUI 看板 : python start_services.py --webui  → http://127.0.0.1:8000")
        print("  REST API   : python start_services.py --api    → http://127.0.0.1:8001")
        print("  MCP Server : 按 .mcp.example.json 配置到你的 MCP 客户端 (Continue/Cline/Claude)")
        print("  Python SDK : from sdk import CSCDClient; c = CSCDClient()")
        print("\n一键全启动 : python start_services.py --all")


if __name__ == "__main__":
    main()
