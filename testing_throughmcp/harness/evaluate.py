"""Measure a pytest suite against FinClusive with real runs.

For a suite directory it reports:
- results on the correct app (passed / failed / skipped per test). A test that
  fails on the correct app is a false alarm: it is listed and ignored below.
- line and branch coverage of the ``finclusive`` package.
- bug detection: the suite is re-run once per seeded bug (finclusive/bugs.py).
  A bug is caught when a test that passed on the correct app fails with the
  bug switched on.

Usage:
    python -m harness.evaluate suites/human_baseline [--json out.json]
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from finclusive.bugs import BUGS

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class SuiteRun:
    outcomes: dict[str, str]  # test id -> passed | failed | skipped | error
    coverage: dict | None = None

    def ids(self, outcome: str) -> list[str]:
        return sorted(t for t, o in self.outcomes.items() if o == outcome)


@dataclass
class Evaluation:
    suite: str
    tests: int
    passed: list[str]
    false_alarms: list[str]  # fail on the correct app
    skipped: list[str]
    line_coverage: float
    branch_coverage: float
    bugs_caught: dict[str, list[str]] = field(default_factory=dict)  # bug -> tests that caught it
    bugs_missed: list[str] = field(default_factory=list)

    @property
    def bug_detection_rate(self) -> float:
        total = len(self.bugs_caught) + len(self.bugs_missed)
        return len(self.bugs_caught) / total if total else 0.0

    def to_dict(self) -> dict:
        return {**asdict(self), "bug_detection_rate": round(self.bug_detection_rate, 4)}


def parse_junit(path: Path) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        test_id = f"{case.get('classname', '')}::{case.get('name', '')}"
        tags = {child.tag for child in case}
        if "skipped" in tags:
            outcomes[test_id] = "skipped"
        elif "error" in tags:
            outcomes[test_id] = "error"
        elif "failure" in tags:
            outcomes[test_id] = "failed"
        else:
            outcomes[test_id] = "passed"
    return outcomes


def run_suite(
    suite: Path | list[Path], bug: str | None = None, with_coverage: bool = False, timeout: int = 300
) -> SuiteRun:
    """Run pytest on ``suite`` (one or more paths) in a subprocess, with ``bug`` switched on."""
    paths = [str(p) for p in (suite if isinstance(suite, list) else [suite])]
    with tempfile.TemporaryDirectory() as tmp:
        junit = Path(tmp) / "junit.xml"
        cmd = [sys.executable, "-m", "pytest", *paths, "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"]
        cov_json = Path(tmp) / "coverage.json"
        if with_coverage:
            cmd += ["--cov=finclusive", "--cov-branch", f"--cov-report=json:{cov_json}"]
        env = {**os.environ, "FINCLUSIVE_BUG": bug or "", "PYTHONPATH": str(ROOT)}
        proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
        if not junit.exists():
            raise RuntimeError(f"pytest produced no report (exit {proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
        coverage = json.loads(cov_json.read_text()) if with_coverage and cov_json.exists() else None
        return SuiteRun(parse_junit(junit), coverage)


def coverage_percent(cov: dict | None) -> tuple[float, float]:
    """(line %, branch %) for the finclusive package, excluding the test kit."""
    if not cov:
        return 0.0, 0.0
    stmts = covered = branches = covered_branches = 0
    for name, data in cov["files"].items():
        if name.endswith("testkit.py"):
            continue
        s = data["summary"]
        stmts += s["num_statements"]
        covered += s["covered_lines"]
        branches += s.get("num_branches", 0)
        covered_branches += s.get("covered_branches", 0)
    return (
        round(100 * covered / stmts, 1) if stmts else 0.0,
        round(100 * covered_branches / branches, 1) if branches else 0.0,
    )


def _label(suite: Path | list[Path]) -> str:
    paths = suite if isinstance(suite, list) else [suite]
    return " + ".join(str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p) for p in paths)


def evaluate(suite: Path | list[Path], bugs: list[str] | None = None, workers: int = 4) -> Evaluation:
    clean = run_suite(suite, with_coverage=True)
    trusted = set(clean.ids("passed"))
    line_cov, branch_cov = coverage_percent(clean.coverage)
    result = Evaluation(
        suite=_label(suite),
        tests=len(clean.outcomes),
        passed=clean.ids("passed"),
        false_alarms=sorted(clean.ids("failed") + clean.ids("error")),
        skipped=clean.ids("skipped"),
        line_coverage=line_cov,
        branch_coverage=branch_cov,
    )
    bug_names = bugs or sorted(BUGS)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        runs = dict(zip(bug_names, pool.map(lambda b: run_suite(suite, bug=b), bug_names)))
    for bug in bug_names:
        catchers = sorted(t for t, o in runs[bug].outcomes.items() if t in trusted and o in ("failed", "error"))
        if catchers:
            result.bugs_caught[bug] = catchers
        else:
            result.bugs_missed.append(bug)
    return result


def summary(ev: Evaluation) -> str:
    total_bugs = len(ev.bugs_caught) + len(ev.bugs_missed)
    lines = [
        f"Suite: {ev.suite}",
        f"Tests: {ev.tests} ({len(ev.passed)} passed, {len(ev.false_alarms)} false alarms, {len(ev.skipped)} skipped)",
        f"Coverage of finclusive: {ev.line_coverage}% lines, {ev.branch_coverage}% branches",
        f"Seeded bugs caught: {len(ev.bugs_caught)}/{total_bugs} ({ev.bug_detection_rate:.0%})",
    ]
    for bug in sorted(ev.bugs_caught):
        lines.append(f"  caught  {bug}")
    for bug in ev.bugs_missed:
        lines.append(f"  MISSED  {bug}: {BUGS[bug]}")
    for test in ev.false_alarms:
        lines.append(f"  false alarm: {test}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("suite", type=Path, help="directory or file with pytest tests")
    parser.add_argument("--json", type=Path, help="write the full evaluation as JSON here")
    parser.add_argument("--bug", action="append", help="evaluate only these bugs (repeatable)")
    args = parser.parse_args(argv)

    ev = evaluate(args.suite.resolve(), args.bug)
    print(summary(ev))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(ev.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
