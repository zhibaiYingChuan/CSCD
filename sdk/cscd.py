# -*- coding: utf-8 -*-
"""
C-S-C-D · Python SDK（Phase 4）
================================
面向 Python 应用的轻量客户端，封装 C-S-C-D REST API。

用法：
    from sdk import CSCDClient

    client = CSCDClient(base_url="http://127.0.0.1:8001", api_key="your-key")

    # 执行一次 CSCD 推理
    result = client.reason("设计带权限的 TODO 后端 API")
    print(result["reason"])            # 精炼结论
    print(result["cognition"])         # 认知控制审计
    print(result["ledger"])            # 账本审计

    # 查看用量
    print(client.usage())

依赖：仅标准库 urllib（无第三方依赖）。
"""

import json
import urllib.error
import urllib.request
import warnings
from typing import Any, Dict, Optional


class CSCDError(Exception):
    """C-S-C-D API 调用错误。"""


class CSCDClient:
    """C-S-C-D REST API 客户端。"""

    def __init__(self, base_url: str = "http://127.0.0.1:8001",
                 api_key: Optional[str] = None, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        if self.api_key and self.base_url.startswith("http://"):
            warnings.warn(
                "检测到 API Key 将通过 HTTP 明文传输，建议使用 HTTPS 端点。",
                stacklevel=2,
            )
        self.timeout = timeout

    # ---------- 底层请求 ----------
    def _request(self, method: str, path: str,
                 body: Optional[dict] = None) -> Dict[str, Any]:
        url = self.base_url + path
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as e:
                    raise CSCDError(f"响应解析失败（非法 JSON）: {raw[:200]}") from e
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read().decode("utf-8")).get("detail", "")
            except Exception:
                pass
            raise CSCDError(f"HTTP {e.code}: {detail or e.reason}") from e
        except urllib.error.URLError as e:
            raise CSCDError(f"无法连接服务: {e.reason}") from e

    # ---------- 公开方法 ----------
    def health(self) -> Dict[str, Any]:
        """服务健康检查。"""
        return self._request("GET", "/health")

    def reason(self, question: str, has_untrusted_input: bool = False,
               named_modules: Optional[list] = None,
               task_id: Optional[str] = None) -> Dict[str, Any]:
        """执行一次 CSCD 推理。

        Args:
            question: 用户问题。
            has_untrusted_input: 是否含不可信输入。
            named_modules: 显式指定 J-Space 模块。
            task_id: 账本 ID（续跑同一账本）。

        Returns:
            结构化推理结果（含 reason/cognition/ledger 等）。
        """
        body = {
            "question": question,
            "has_untrusted_input": has_untrusted_input,
            "named_modules": named_modules,
        }
        if task_id is not None:
            body["task_id"] = task_id
        return self._request("POST", "/v1/reason", body)

    def usage(self, limit: int = 100) -> Dict[str, Any]:
        """当前 key 的用量统计。"""
        return self._request("GET", f"/v1/usage?limit={limit}")

    def usage_all(self, limit: int = 100) -> Dict[str, Any]:
        """全部 key 用量（管理员）。"""
        return self._request("GET", f"/v1/usage/all?limit={limit}")
