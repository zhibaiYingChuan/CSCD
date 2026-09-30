"""打包相关的一致性校验。

背景：CSCD 通过 `uvx --from git+... cscd-mcp` 分发，config.yaml 必须随包分发
（core/config.yaml）。为只维护一份人工编辑源，约定：
  - 根目录 config.yaml —— 唯一人工编辑来源
  - core/config.yaml  —— 随包副本，由 package-data 分发
两者不一致会让"开发态正确、安装态错误"，故用测试锁死。
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def test_config_copy_in_sync():
    """随包副本必须与根目录配置完全一致。"""
    src = ROOT / "config.yaml"
    dst = ROOT / "core" / "config.yaml"
    assert src.exists(), "根目录 config.yaml 缺失"
    assert dst.exists(), "core/config.yaml 缺失（随包分发副本，构建会静默丢配置）"
    assert src.read_text(encoding="utf-8") == dst.read_text(encoding="utf-8"), (
        "core/config.yaml 与根目录 config.yaml 不一致。根目录是唯一人工编辑来源，"
        "修改后请同步复制：Copy-Item config.yaml core\\config.yaml"
    )


def test_builtin_defaults_match_config():
    """内置默认必须与 config.yaml 一致。

    内置默认是 config.yaml **完全缺失**时的兜底。若二者不一致，一旦配置未随包分发，
    行为会静默漂移（例如 prefer_action_plan 退回 True 会导致四阶协议不执行）。
    """
    yaml = pytest.importorskip("yaml")
    from core.cscd import _DEFAULT_CONFIG

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    for key in ("prefer_action_plan", "max_rounds", "simple_shortcut_to_baseline",
                "marks_blocking", "legacy_marks_fallback", "early_stop_on_stable"):
        if key in cfg:
            assert _DEFAULT_CONFIG.get(key) == cfg[key], (
                f"_DEFAULT_CONFIG[{key}]={_DEFAULT_CONFIG.get(key)!r} 与 config.yaml 的 "
                f"{cfg[key]!r} 不一致；内置默认必须与配置保持一致"
            )


def test_rounds_by_complexity_present_in_defaults():
    """动态轮次映射必须存在于内置默认。

    缺失会让 max_rounds 的 min() 计算拿到 None，进而崩溃或轮次失控。
    """
    from core.cscd import _DEFAULT_CONFIG

    assert _DEFAULT_CONFIG.get("rounds_by_complexity"), "内置默认缺少 rounds_by_complexity"
