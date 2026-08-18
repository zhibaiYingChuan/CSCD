"""
C-S-C-D 通用推理编排器（模型无关 · 入口）
========================================
通过 Carrier 接口驱动任意执行载体（OpenAI 兼容 / CodeBuddy / DSH ...）。
协议层（core/cscd.py）与载体层（carriers/*）解耦，换模型=换 Carrier。

用法:
    export OPENAI_BASE_URL="https://api.deepseek.com"
    export OPENAI_API_KEY="sk-..."
    python orchestrator.py --model deepseek-chat --task "你的问题"

依赖: pip install openai
"""

import os
import sys
import json
import argparse
from pathlib import Path

# 允许以脚本方式直接运行（将项目根加入 sys.path）
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from core.cscd import CscdEngine
from carriers.openai_carrier import OpenAICarrier


def main():
    ap = argparse.ArgumentParser(description="C-S-C-D 通用推理编排器（模型无关）")
    ap.add_argument("--model", required=True, help="模型名，如 deepseek-chat / gpt-4o")
    ap.add_argument("--task", required=True, help="要处理的问题")
    ap.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL"), help="OpenAI 兼容端点")
    ap.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY"), help="API Key")
    ap.add_argument("--json", action="store_true", help="仅输出 JSON 结果")
    args = ap.parse_args()

    if not args.base_url or not args.api_key:
        print("错误: 需设置 OPENAI_BASE_URL 与 OPENAI_API_KEY，或通过参数传入。", file=sys.stderr)
        sys.exit(1)

    carrier = OpenAICarrier(args.model, args.base_url, args.api_key)
    engine = CscdEngine(carrier)
    res = engine.run(args.task)

    out = {
        "task_type": res.task_type,
        "complexity": res.complexity,
        "strategy": res.strategy,
        "budget": res.budget,
        "marks_valid": res.marks_valid,
        "missing_marks": res.missing_marks,
        "recursed": res.recursed,
        "anchor": res.anchor,
        "result": res.reason,
        "usage": carrier.last_usage,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
