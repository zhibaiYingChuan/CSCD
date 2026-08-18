"""
Carrier 抽象接口（载体层契约，模型/工具无关）
============================================
所有执行载体（OpenAI 兼容 / CodeBuddy 会话 / DSH / crewAI ...）都实现本接口。
协议层（core/cscd.py）只依赖本抽象，不依赖任何具体运行时。
换载体 = 换一个 Carrier 实现，四阶语义不变。
"""


class Carrier:
    """统一运行时契约。"""

    def anchor(self, question: str) -> str:
        """L2 启动锚定：首轮极简事实锚定，不携带完整协议与工具。"""
        raise NotImplementedError

    def reason(self, prompt: str, system: str, budget: int) -> str:
        """L4 四阶推理：在完整协议下执行，返回含四阶标记的文本。"""
        raise NotImplementedError

    def validate_marks(self, text: str) -> bool:
        """可选：载体侧标记校验（默认委托 core.marks）。"""
        from core.marks import validate_marks
        return validate_marks(text).ok
