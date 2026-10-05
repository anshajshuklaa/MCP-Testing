from pathlib import Path

import pytest

from harness.generate import (
    UnsafeCode,
    check_code,
    collect_test_names,
    extract_code,
    generate,
    remove_tests,
    weak_tests,
)
from harness.llm import fixed_responses

GOOD = '''
from datetime import date


def test_min_payment_rejects_99(fc):
    """Payment rules: minimum payment is 100."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, 5000, 250, date(2026, 1, 3))
    assert fc.pay(card, 99).status_code == 422
'''

WRONG = '''

def test_tier_wrong(fc):
    """Reward tiers: misread on purpose."""
    fc.register()
    fc.set_points(1000)
    assert fc.rewards()["tier"] == "Bronze"
'''

FIXED = '''

def test_tier_silver_at_1000(fc):
    """Reward tiers: Silver starts at 1000."""
    fc.register()
    fc.set_points(1000)
    assert fc.rewards()["tier"] == "Silver"
'''


def block(code: str) -> str:
    return f"Here you go:\n```python\n{code}\n```\n"


def test_wrong_test_is_repaired(tmp_path: Path):
    llm = fixed_responses(block(GOOD + WRONG), block(GOOD + FIXED))

    report = generate(tmp_path, llm, n_tests=2, repair_rounds=2)

    assert report.tests_generated == 2
    assert report.repair_rounds_used == 1
    assert report.removed_tests == []
    code = (tmp_path / "test_ai_generated.py").read_text()
    assert collect_test_names(code) == ["test_min_payment_rejects_99", "test_tier_silver_at_1000"]
    # The repair prompt shows the model the real pytest failure.
    assert "test_tier_wrong" in llm.prompts[1][1] and "assert" in llm.prompts[1][1]


def test_unrepaired_test_is_removed_not_faked(tmp_path: Path):
    llm = fixed_responses(block(GOOD + WRONG), block(GOOD + WRONG))

    report = generate(tmp_path, llm, n_tests=2, repair_rounds=1)

    assert report.removed_tests == ["test_tier_wrong"]
    assert report.tests_kept == 1


def test_generator_never_sees_app_source(tmp_path: Path):
    llm = fixed_responses(block(GOOD))
    generate(tmp_path, llm, n_tests=1)
    prompt = llm.prompts[0][1]
    assert "FINCLUSIVE_BUG" not in prompt and "bug ==" not in prompt
    assert "Minimum payment" in prompt  # the spec is there


@pytest.mark.parametrize(
    "code",
    ["import os\n", "from subprocess import run\n", "x = eval('1')\n", "open('/etc/passwd')\n", "def broken(:\n"],
)
def test_unsafe_or_broken_code_is_refused(code):
    with pytest.raises(UnsafeCode):
        check_code(code)


def test_extract_code_takes_the_python_block():
    assert extract_code("text\n```python\nx = 1\n```\nmore") == "x = 1\n"
    with pytest.raises(ValueError):
        extract_code("I cannot help with that.")


def test_remove_tests_keeps_the_rest():
    assert collect_test_names(remove_tests(GOOD + WRONG, {"test_tier_wrong"})) == ["test_min_payment_rejects_99"]


LOOSE = '''

def test_points_loose(fc):
    """Base points."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, 5000, 250, date(2026, 1, 3))
    r = fc.pay(card, 150)
    assert r.status_code == 201
    assert r.json()["points_earned"] > 0


def test_nothing(fc):
    """Server errors."""
    pass
'''

TIGHT = '''

def test_points_exact(fc):
    """Base points: 1 per 100, rounded down."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, 5000, 250, date(2026, 1, 3))
    assert fc.pay(card, 150).json()["points_earned"] == 1
'''


def test_weak_tests_flags_loose_and_empty_tests():
    assert weak_tests(GOOD + LOOSE) == ["test_points_loose", "test_nothing"]
    assert weak_tests(GOOD + TIGHT) == []
    assert weak_tests("def test_codes(fc):\n    assert fc.get('/x').status_code in [401, 422]\n") == ["test_codes"]


def test_weak_tests_go_back_for_repair_and_empty_ones_are_dropped(tmp_path: Path):
    llm = fixed_responses(block(GOOD + LOOSE), block(GOOD + TIGHT + LOOSE))

    report = generate(tmp_path, llm, n_tests=3, repair_rounds=1)

    assert "test_points_loose" in llm.prompts[1][1] and "no exact assertion" in llm.prompts[1][1]
    assert report.removed_tests == ["test_nothing"]
    assert report.weak_tests == ["test_points_loose"]
    assert report.tests_kept == 3
