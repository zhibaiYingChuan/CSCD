"""
CSCD 对照实验运行脚本
=====================
三组对比：A-直答（无协议）/ B-CSCD单轮 / C-CSCD多轮

用法：
  set LLM_API_URL=https://your-endpoint
  set LLM_API_KEY=sk-xxx
  python tests/run_comparison.py --model deepseek-v4-flash

输出：tests/results/ 目录下每个任务独立 jsonl + 汇总 summary.json
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from carriers.openai_carrier import OpenAICarrier
from core.cscd import CscdEngine
from core.assess import assess_complexity


def load_suite(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_group_a(carrier, task_prompt: str):
    """A组：直答（无协议基线）"""
    text = carrier.reason_baseline(task_prompt)
    usage = getattr(carrier, "last_usage", None) or {}
    return {
        "text": text,
        "usage": usage,
        "completion_tokens": usage.get("completion_tokens", 0),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "latency_ms": usage.get("latency_ms", 0),
    }


def run_group_b(carrier, task_prompt: str):
    """B组：CSCD单轮（max_rounds=1）"""
    eng = CscdEngine(carrier, config={
        "max_rounds": 1,
        "rounds_by_complexity": {"simple": 1, "medium": 1, "complex": 1},
        "compress_ratios": {"round_1": 0.6, "round_2": 0.5, "round_3": 0.4, "round_default": 0.4},
        "budget_per_round": 2048,
        "early_stop_on_stable": False,
        "simple_shortcut_to_baseline": False,
    })
    res = eng.run(task_prompt)
    return {
        "text": res.reason,
        "raw_reason": res.raw_reason,
        "rounds": res.rounds,
        "completion_tokens": res.total_completion_tokens,
        "cache_hits": res.cache_hits,
        "marks_valid": getattr(res, "marks_valid", None),
    }


def run_group_c(carrier, task_prompt: str):
    """C组：CSCD多轮递归（max_rounds=3）"""
    eng = CscdEngine(carrier, config={
        "max_rounds": 3,
        "rounds_by_complexity": {"simple": 1, "medium": 2, "complex": 3},
        "compress_ratios": {"round_1": 0.6, "round_2": 0.5, "round_3": 0.4, "round_default": 0.4},
        "budget_per_round": 2048,
        "early_stop_on_stable": True,
        "simple_shortcut_to_baseline": False,
    })
    res = eng.run(task_prompt)
    return {
        "text": res.reason,
        "raw_reason": res.raw_reason,
        "rounds": res.rounds,
        "completion_tokens": res.total_completion_tokens,
        "cache_hits": res.cache_hits,
        "marks_valid": getattr(res, "marks_valid", None),
        "summaries": res.summaries,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--suite", default="tests/test_suite.json")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--skip-groups", default="", help="跳过指定组，如 'A,B'")
    args = ap.parse_args()

    skip = set(args.skip_groups.split(",")) if args.skip_groups else set()
    base_url = args.base_url or os.getenv("LLM_API_URL") or os.getenv("OPENAI_BASE_URL")
    api_key = args.api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")

    if not base_url or not api_key:
        print("[错误] 请设置 LLM_API_URL 和 LLM_API_KEY 环境变量")
        sys.exit(1)

    suite = load_suite(args.suite)
    carrier = OpenAICarrier(model=args.model, base_url=base_url, api_key=api_key)

    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary = {
        "meta": {
            **suite["meta"],
            "timestamp": timestamp,
            "tasks": len(suite["tasks"]),
            "endpoint": base_url,
            "temperature": 0.3,
            "max_tokens_per_call": 2048,
            "timeout_s": int(os.environ.get("CSCD_TIMEOUT", "60")),
            "retry_policy": "指数退避 1s/2s/4s, max 3 次",
            "system_prompt_A": "你是一个有用的助手，请直接完成任务。",
            "system_prompt_BC": "cscd-system-prompt.md（完整协议模板）",
        },
        "results": {},
    }

    total_start = time.time()

    for task in suite["tasks"]:
        tid = task["id"]
        print(f"\n{'='*60}")
        print(f"[{tid}] {task['category']}: {task['title']}")
        print(f"{'='*60}")

        task_result = {
            "category": task["category"],
            "title": task["title"],
            "prompt": task["prompt"],
            "checkpoints": task["checkpoints"],
            "groups": {},
        }

        # A组：直答
        if "A" not in skip:
            print(f"  → A组（直答）...", end=" ", flush=True)
            t0 = time.time()
            task_result["groups"]["A"] = run_group_a(carrier, task["prompt"])
            task_result["groups"]["A"]["latency_s"] = round(time.time() - t0, 1)
            print(f"完成 ({task_result['groups']['A']['completion_tokens']} tok)")

        # B组：CSCD单轮
        if "B" not in skip:
            print(f"  → B组（CSCD单轮）...", end=" ", flush=True)
            t0 = time.time()
            task_result["groups"]["B"] = run_group_b(carrier, task["prompt"])
            task_result["groups"]["B"]["latency_s"] = round(time.time() - t0, 1)
            print(f"完成 ({task_result['groups']['B']['rounds']}轮, {task_result['groups']['B']['completion_tokens']} tok)")

        # C组：CSCD多轮
        if "C" not in skip:
            print(f"  → C组（CSCD多轮）...", end=" ", flush=True)
            t0 = time.time()
            task_result["groups"]["C"] = run_group_c(carrier, task["prompt"])
            task_result["groups"]["C"]["latency_s"] = round(time.time() - t0, 1)
            print(f"完成 ({task_result['groups']['C']['rounds']}轮, {task_result['groups']['C']['completion_tokens']} tok, cache={task_result['groups']['C']['cache_hits']})")

        # 落盘（每个任务独立文件）
        out_file = out_dir / f"{tid}_{timestamp}.jsonl"
        out_file.write_text(json.dumps(task_result, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["results"][tid] = {
            "category": task["category"],
            "groups": {
                g: {"completion_tokens": d.get("completion_tokens", 0), "rounds": d.get("rounds", 1)}
                for g, d in task_result["groups"].items()
            },
        }
        print(f"  [OK] 已保存: {out_file.name}")

    total_elapsed = round(time.time() - total_start, 1)
    summary["total_elapsed_s"] = total_elapsed

    # 汇总
    summary_file = out_dir / f"summary_{timestamp}.json"
    summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{'='*60}")
    print(f"全部完成，耗时 {total_elapsed}s")
    print(f"汇总: {summary_file}")
    print(f"结果: {out_dir}")


if __name__ == "__main__":
    main()