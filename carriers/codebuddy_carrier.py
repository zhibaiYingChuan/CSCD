"""
CodeBuddy Carrier（选项C：本会话即执行载体）
============================================
CodeBuddy 本身是大模型 Agent，本会话可直接按 C-S-C-D 协议执行推理，无需另接 API。

两种运行模式：
1. 离线样本模式（`sample_key` 非空且无 delegate）：anchor/reason 从 carriers/samples/ 读取
   预生成的四阶推理样本（由 CodeBuddy 会话真实产出后固化），用于打通协议层全链路、
   验证标记校验与记账，不依赖外部网络。
2. 本会话原生执行模式（`native=True`，无需任何 key）：在 CodeBuddy 当前会话中，
   **由内置模型直接执行真实多轮任务**——推理由本会话产出 `<DECOMPOSE>/<CLASSIFY>/<SELECT>/<COMBINE>`
   标记文本；Token 通过 tiktoken 精确计量输入/输出（CodeBuddy 响应元数据不直接暴露计数）。
3. HTTP 回退模式：若提供 base_url/api_key/model，则复用 OpenAI 兼容调用，
   便于纯脚本环境复用同一套协议。

说明：选项B已确认 CodeBuddy 内置模型即足以验证，无需外部 API 端点。
本文件因此提供"本会话原生执行器"，让编排协议在真实 Agent 环境中得到可量化验证。
"""

import json
import logging
from pathlib import Path
from carriers.base import Carrier

logger = logging.getLogger(__name__)

_SAMPLES_DIR = Path(__file__).parent / "samples"


def _count_tokens(text: str) -> int:
    """
    tiktoken 精确 Token 计量（cl100k_base，OpenAI 兼容通用近似）。
    失败时降级为「字符数 / 1.6」粗估，保证不阻塞验证流程。
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, int(len(text) / 1.6))

# dsh-anchored-standard 真实 Bootstrap 工具对（Minimal 真实工具）
BOOTSTRAP_TOOLS = ["bash", "str_replace_editor"]
# Promotion 触发信号（持久事件，先到为准）
PROMOTE_ON = "either"  # either | tool-call | assistant-message


class CodeBuddyCarrier(Carrier):
    def __init__(self, sample_key: str = "spec_module_design",
                 model: str = None, base_url: str = None, api_key: str = None,
                 native: bool = False):
        self.sample_key = sample_key
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.native = native
        self._delegate = None
        # dsh Promotion 状态：基于持久事件推导（resume 安全），非内存一次性标记
        self.promoted = False
        if base_url and api_key and model:
            from carriers.openai_carrier import OpenAICarrier
            self._delegate = OpenAICarrier(model, base_url, api_key)
        elif base_url or api_key or model:
            # 配置不完整：三者不全但任一非空，回退到 sample/native 模式
            fallback = "native" if self.native else "sample"
            logger.warning(
                "模型配置不完整（base_url=%s, api_key=%s, model=%s），"
                "将回退到 %s 模式。如需使用 HTTP 模式，请同时提供三者。",
                "已设置" if base_url else "空",
                "已设置" if api_key else "空",
                "已设置" if model else "空",
                fallback,
            )

    @property
    def mode(self) -> str:
        if self._delegate:
            return "http"
        if self.native:
            return "native"   # 本会话内置模型直接执行
        return "sample"       # 离线样本

    def _load_sample(self) -> dict:
        path = _SAMPLES_DIR / f"{self.sample_key}.json"
        if not path.exists():
            raise FileNotFoundError(f"样本不存在: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def anchor(self, question: str) -> str:
        """
        L2 Bootstrap（校准自 dsh-anchored-standard）:
        首轮零注入（context-gate 屏蔽 AGENTS/skill 摘要）+ 仅锚定工具对。
        返回描述首轮状态的锚定文本（不携带完整协议与自动注入上下文）。
        """
        if self._delegate:
            return self._delegate.anchor(question)
        if self.native:
            # 本会话原生锚定：由内置模型在对话中产出；此处返回极简首轮事实锚定提示，
            # 真实推理文本由 reason() 在本回合对话里直接生成（见 _native_reason）。
            return (
                "Bootstrap 锚定（零注入）：仅接收用户原始问题，不携带任何协议摘要或自动注入上下文。"
                "待首个持久推理动作后进入常驻阶段。"
            )
        # 离线样本模式：返回样本锚定段（已含极简事实锚定语义）
        return self._load_sample()["anchor"]

    def reason(self, prompt: str, system: str, budget: int) -> str:
        """
        四阶推理执行；按 dsh Promotion 规则，首个持久动作后进入常驻阶段。
        - http 模式：委托 OpenAI 兼容调用；
        - native 模式：返回结构化占位，真实推理文本由本会话内置模型在对话中产出，
          并通过 _native_reason() 收集；
        - sample 模式：返回固化样本。
        """
        if self._delegate:
            result = self._delegate.reason(prompt, system, budget)
            if PROMOTE_ON in ("either", "assistant-message"):
                self.promoted = True
            return result
        if self.native:
            if PROMOTE_ON in ("either", "assistant-message"):
                self.promoted = True
            # 原生模式下，reason 由调用方（本会话）组装真实四阶输出后回填；
            # 此处返回协议骨架提示，实际标记文本见 _native_reason 返回的对话产出。
            return self._native_skeleton(prompt, budget)
        if PROMOTE_ON in ("either", "assistant-message"):
            self.promoted = True
        return self._load_sample()["reason"]

    def _native_skeleton(self, prompt: str, budget: int) -> str:
        """原生模式占位骨架：提示本会话需在 budget 约束内产出四阶标记文本。"""
        return (
            f"[native-reason 骨架] 请在预算 ≤{budget} 标记约束内，对以下任务产出含 "
            "<DECOMPOSE>/<CLASSIFY>/<SELECT>/<COMBINE> 四阶标记的真实推理文本：\n{prompt}"
        )

    def native_run(self, question: str, system: str, budget: int) -> dict:
        """
        本会话原生执行入口（选项B落地）：
        在 CodeBuddy 当前会话中，由内置模型直接对 question 产出标准化四阶推理文本。
        调用方（脚本/对话）负责把本会话真实回复回填到此方法，或直接在本回合对话中替代它。

        返回 dict：{question, output, input_tokens, output_tokens}，Token 经 tiktoken 计量。

        说明：纯脚本环境无内置模型，会回退为骨架；但在 CodeBuddy 对话中，
        本方法作为"计量与契约"锚点，真实 output 由对话产出后统计。
        """
        if PROMOTE_ON in ("either", "assistant-message"):
            self.promoted = True
        # 输入 Token = system + question
        input_text = (system or "") + "\n" + question
        return {
            "question": question,
            "output": self._native_skeleton(question, budget),
            "input_tokens": _count_tokens(input_text),
            "output_tokens": _count_tokens(self._native_skeleton(question, budget)),
        }

    @property
    def resident_tools(self) -> list:
        """常驻阶段工具目录（引导对 + 发现工具，校准自 dsh Resident catalog）。"""
        if not self.promoted:
            return list(BOOTSTRAP_TOOLS)
        return list(BOOTSTRAP_TOOLS) + [
            "dev_tool_search", "skill_search", "skill_load"
        ]
