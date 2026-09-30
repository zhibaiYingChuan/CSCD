from core.jspace_modules import (
    load_modules,
    load_selected_modules,
    modules_context,
    modules_for_phase,
    load_phase_modules,
    select_modules,
)


def test_loop_loads_actual_module_content(tmp_path):
    (tmp_path / "capacity.md").write_text("容量规则", encoding="utf-8")
    (tmp_path / "broadcast.md").write_text("广播规则", encoding="utf-8")

    names = select_modules("loop")
    loaded = load_selected_modules("loop", root=tmp_path)

    assert names == ["capacity", "broadcast"]
    assert loaded == {"capacity": "容量规则", "broadcast": "广播规则"}
    assert "容量规则" in modules_context(loaded)
    assert "广播规则" in modules_context(loaded)


def test_fast_does_not_load_modules(tmp_path):
    (tmp_path / "capacity.md").write_text("不应加载", encoding="utf-8")
    assert load_selected_modules("fast", root=tmp_path) == {}


def test_phase_modules_change_with_runtime_phase(tmp_path):
    for name in ("capacity", "broadcast", "deep-reasoning", "empirics", "self-monitoring"):
        (tmp_path / f"{name}.md").write_text(f"{name} 正文", encoding="utf-8")

    explore_names = modules_for_phase("explore", "loop")
    verify_names, verify_content = load_phase_modules("verify", "loop", root=tmp_path)

    assert "deep-reasoning" in explore_names
    assert "empirics" in verify_names
    assert "self-monitoring" in verify_names
    assert "empirics" in verify_content
    assert "capacity" not in verify_content


def test_all_runtime_phases_have_explicit_module_contract(tmp_path):
    for name in ("directed-focus", "capacity", "broadcast", "deep-reasoning", "empirics", "self-monitoring"):
        (tmp_path / f"{name}.md").write_text(name, encoding="utf-8")

    expected = {
        "anchor": ["directed-focus"],
        "explore": ["capacity", "broadcast", "deep-reasoning"],
        "implement": ["capacity", "broadcast", "directed-focus"],
        "verify": ["empirics", "self-monitoring"],
        "ship": ["self-monitoring", "empirics"],
    }
    for phase, names in expected.items():
        selected, content = load_phase_modules(phase, "full", root=tmp_path)
        assert selected == names
        assert list(content) == names


def test_missing_phase_module_is_auditable_not_fabricated(tmp_path):
    selected, content = load_phase_modules("verify", "full", root=tmp_path)
    assert selected == ["empirics", "self-monitoring"]
    assert content == {}
