from core.cognition import UnderstandContract, build_understand_prompt


def test_icot_contract_requires_six_fields():
    contract = UnderstandContract()
    assert contract.fields == (
        "algorithm_intent", "input_output", "state_change", "problem", "plan", "complexity",
    )
    check = contract.validate("算法意图：x\n输入输出：y\n状态变化：z\n问题定位：p\n修复方案：q\n复杂度：O(n)")
    assert check["valid"] is True


def test_icot_contract_rejects_missing_complexity():
    check = UnderstandContract().validate("算法意图：x\n输入输出：y\n状态变化：z\n问题定位：p\n修复方案：q")
    assert check["valid"] is False
    assert "complexity" in check["missing"]


def test_understand_prompt_is_generated_from_contract():
    prompt = build_understand_prompt()
    assert "算法意图" in prompt
    assert "时间复杂度和空间复杂度" in prompt
    assert "UNDERSTAND" in prompt
