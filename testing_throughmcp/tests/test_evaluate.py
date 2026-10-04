from pathlib import Path

from harness.evaluate import coverage_percent, evaluate, parse_junit

SUITE = '''
import os
from datetime import date
from finclusive.testkit import FinClusive


def _fc():
    return FinClusive(bug=os.environ.get("FINCLUSIVE_BUG") or None)


def test_rejects_99():
    fc = _fc()
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, 5000, 250, date(2026, 1, 3))
    assert fc.pay(card, 99).status_code == 422


def test_wrong_expectation():
    fc = _fc()
    fc.register()
    assert fc.rewards()["points"] == 999
'''


def test_evaluate_scores_a_small_suite(tmp_path: Path):
    suite = tmp_path / "test_small.py"
    suite.write_text(SUITE)

    ev = evaluate(suite, bugs=["min_payment_99", "luhn_unchecked"], workers=2)

    assert ev.tests == 2
    assert [t.split("::")[-1] for t in ev.false_alarms] == ["test_wrong_expectation"]
    assert list(ev.bugs_caught) == ["min_payment_99"]
    assert ev.bugs_missed == ["luhn_unchecked"]
    assert ev.bug_detection_rate == 0.5
    assert ev.line_coverage > 0


def test_parse_junit_reads_every_outcome(tmp_path: Path):
    xml = tmp_path / "j.xml"
    xml.write_text(
        '<testsuites><testsuite>'
        '<testcase classname="m" name="ok"/>'
        '<testcase classname="m" name="bad"><failure/></testcase>'
        '<testcase classname="m" name="boom"><error/></testcase>'
        '<testcase classname="m" name="skip"><skipped/></testcase>'
        '</testsuite></testsuites>'
    )
    assert parse_junit(xml) == {"m::ok": "passed", "m::bad": "failed", "m::boom": "error", "m::skip": "skipped"}


def test_coverage_percent_ignores_testkit():
    cov = {
        "files": {
            "finclusive/rules.py": {"summary": {"num_statements": 10, "covered_lines": 5, "num_branches": 4, "covered_branches": 1}},
            "finclusive/testkit.py": {"summary": {"num_statements": 90, "covered_lines": 90, "num_branches": 0, "covered_branches": 0}},
        }
    }
    assert coverage_percent(cov) == (50.0, 25.0)
