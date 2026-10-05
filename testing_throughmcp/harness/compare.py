"""Compare test suites on the same metrics: human, AI-generated, and both together.

Usage:
    python -m harness.compare suites/human_baseline suites/ai_generated [--json results/comparison.json]
"""

import argparse
import json
from pathlib import Path

from finclusive.bugs import BUGS
from harness.evaluate import Evaluation, evaluate


def table(evals: list[Evaluation]) -> str:
    rows = [
        ("Tests kept", lambda e: str(len(e.passed))),
        ("False alarms", lambda e: str(len(e.false_alarms))),
        ("Line coverage", lambda e: f"{e.line_coverage}%"),
        ("Branch coverage", lambda e: f"{e.branch_coverage}%"),
        ("Seeded bugs caught", lambda e: f"{len(e.bugs_caught)}/{len(BUGS)} ({e.bug_detection_rate:.0%})"),
    ]
    header = "| Metric | " + " | ".join(e.suite for e in evals) + " |"
    lines = [header, "|" + "---|" * (len(evals) + 1)]
    lines += ["| " + name + " | " + " | ".join(f(e) for e in evals) + " |" for name, f in rows]
    lines += ["", "| Bug | " + " | ".join(e.suite for e in evals) + " |", "|" + "---|" * (len(evals) + 1)]
    for bug in sorted(BUGS):
        lines.append(f"| {bug} | " + " | ".join("caught" if bug in e.bugs_caught else "-" for e in evals) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("suites", type=Path, nargs="+")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    paths = [p.resolve() for p in args.suites]
    evals = [evaluate(p) for p in paths]
    if len(paths) > 1:
        evals.append(evaluate(paths))
    print(table(evals))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps([e.to_dict() for e in evals], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
