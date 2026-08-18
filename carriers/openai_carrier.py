"""
OpenAI 兼容 Carrier（选项A：任意模型可接）
=========================================
实现 Carrier 接口，对接任意 OpenAI Chat Completions 兼容端点。
这是本系统中**唯一能真正发起独立模型调用、从而注入/不注入协议到「直接模型调用思维链」**的载体。

提供两类入口：
- `reason()`：带协议 System Prompt 的四阶推理调用（影响思维链）。
- `reason_baseline()`：同任务、中性 System、独立调用（对照基线，不影响思维链）。
两者上下文完全隔离，可用于「协议是否改变思维链」的真实双调用对照。
"""

import logging
import time
from pathlib import Path
from carriers.base import Carrier

# 协议本体模板（cscd-system-prompt.md 中截取），默认自动加载；缺失时回退内置精简版。
_PROMPT_TEMPLATE = Path(__file__).parent.parent / "cscd-system-prompt.md"

logger = logging.getLogger(__name__)

_NEUTRAL_SYSTEM = "你是一个有用的助手，请直接完成任务。"

_BUILTIN_CSCD = (
    "你是一个遵循 C-S-C-D（分类-选择-组合-拆解）四阶递归的推理系统。"
    "必须按 DECOMPOSE→CLASSIFY→SELECT→COMBINE 顺序输出四阶标记，"
    "四段成对出现、顺序固定、非空；SELECT 仅从事实池取权重最高3个原子。"
)


def load_cscd_system() -> str:
    """从 cscd-system-prompt.md 抽取 SYSTEM PROMPT 段；缺失则回退内置。

    鲁棒做法：按行查找以 `=== SYSTEM PROMPT` 开头的边界行，避免脆弱的精确中文子串比较。
    """
    if _PROMPT_TEMPLATE.exists():
        lines = _PROMPT_TEMPLATE.read_text(encoding="utf-8").splitlines()
        start = end = None
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith("=== SYSTEM PROMPT") and "开始" in s:
                start = i
            elif s.startswith("=== SYSTEM PROMPT") and "结束" in s:
                end = i
        if start is not None and end is not None and end > start + 1:
            return "\n".join(lines[start + 1:end]).strip()
    return _BUILTIN_CSCD


class OpenAICarrier(Carrier):
    def __init__(self, model: str, base_url: str, api_key: str):
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0.0}

    def _call(self, messages: list, max_tokens: int) -> str:
        import os
        from openai import OpenAI
        import openai as _openai_mod

        # 防御性收集异常类（兼容不同 openai 库版本，不存在的类自动跳过）
        _exc_list = []
        for _name in ("RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError"):
            _cls = getattr(_openai_mod, _name, None)
            if _cls is not None:
                _exc_list.append(_cls)
        _retry_excs = tuple(_exc_list)

        # 超时：环境变量 CSCD_TIMEOUT 覆盖，默认 60 秒
        timeout = float(os.environ.get("CSCD_TIMEOUT", "60.0"))
        client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=timeout)

        # 指数退避重试：对 429（限流）/ 5xx/连接错误/超时/空响应 自动重试
        max_retries = 3
        attempt = 0
        resp = None
        t0 = time.time()  # 总耗时起点（含所有重试等待）
        while attempt < max_retries:
            attempt += 1
            try:
                resp = client.chat.completions.create(
                    model=self.model, messages=messages,
                    max_tokens=max_tokens, temperature=0.3,
                )
            except _retry_excs as e:
                if attempt >= max_retries:
                    raise
                wait = 2 ** (attempt - 1)  # 1s -> 2s -> 4s
                logger.warning("OpenAI 调用失败（第 %d/%d 次），%s 秒后重试：%s", attempt, max_retries, wait, e)
                time.sleep(wait)
                continue
            # 防御性检查响应结构
            assert resp and len(resp.choices) > 0, f"模型返回空 choices：{resp}"
            msg = resp.choices[0].message
            assert msg is not None, "模型返回的 message 为 None"
            content = (msg.content or "").strip()
            if content:
                break
            # content 为空：可能是推理模型只产出了 reasoning_content，或端点抖动。
            # 若 reasoning_content 含内容则直接采用（deepseek 标准字段）；否则重试。
            rc = (getattr(msg, "reasoning_content", None) or "").strip()
            if rc:
                break
            if attempt >= max_retries:
                raise RuntimeError(f"模型返回空响应（{attempt} 次尝试均无 content/reasoning_content）")
            time.sleep(2 ** (attempt - 1))
        dt = (time.time() - t0) * 1000.0  # 总耗时（含所有重试）
        u = resp.usage if resp else None
        self.last_usage = {
            "prompt_tokens": u.prompt_tokens if u else 0,
            "completion_tokens": u.completion_tokens if u else 0,
            "latency_ms": dt,
            "retries": attempt - 1,
        }
        msg = resp.choices[0].message
        content = (msg.content or "").strip()
        if content:
            return content
        return (getattr(msg, "reasoning_content", None) or "").strip()

    def anchor(self, question: str) -> str:
        return self._call(
            [
                {"role": "system", "content": "你是推理助手。请先理解问题并给出初步事实锚定，简明即可。"},
                {"role": "user", "content": question},
            ],
            max_tokens=256,
        )

    def reason(self, prompt: str, system: str = None, budget: int = 2048) -> str:
        """带协议的四阶推理调用（注入 C-S-C-D 到模型思维链）。"""
        system = system or load_cscd_system()
        return self._call(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=budget,
        )

    def reason_baseline(self, prompt: str, budget: int = 2048) -> str:
        """对照基线：同任务、中性 System、独立上下文（不注入协议）。"""
        return self._call(
            [
                {"role": "system", "content": _NEUTRAL_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=budget,
        )
