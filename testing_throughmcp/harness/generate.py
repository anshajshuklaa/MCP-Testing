"""Have an LLM write executable pytest tests for FinClusive.

The generator is black-box on purpose. It sees the spec, the API contract and
the existing human tests, never the FinClusive source code. The source contains
the seeded-bug switches, so showing it would leak the answer key.

Pipeline:
1. Generate: one LLM call returns a Python test module.
2. Check: the code must parse and import only from an allowlist, because we
   are about to execute model-written code.
3. Run on the correct app. A failing test means the model misread the spec or
   the API, never that the app is wrong.
4. Repair: failing tests and their pytest output go back to the model, for up
   to ``repair_rounds`` rounds.
5. Prune: tests still failing are removed and listed in the report. Nothing is
   invented to fill the gap.

Usage:
    python -m harness.generate --out suites/ai_generated --model gemini/gemini-2.5-flash
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from harness.evaluate import ROOT, run_suite
from harness.llm import litellm_complete

SPEC = ROOT / "spec" / "FinClusive_Scenario.md"
API = ROOT / "spec" / "API.md"
HUMAN_SUITE = ROOT / "suites" / "human_baseline" / "test_human_baseline.py"

ALLOWED_IMPORTS = {"pytest", "datetime", "decimal", "finclusive.testkit", "re"}

SYSTEM = """You are a senior QA engineer writing black-box API tests in Python with pytest.
You only know the product from its specification and API contract. Each test checks one
business rule, sets up exactly the state it needs, and asserts the observable result
(status code, response field, balance). Prefer boundary values: just below, at, and just
above every limit in the spec. Reply with one Python module in a single ```python block."""

GENERATE = """Write a pytest module that tests FinClusive against its specification.

# Specification
{spec}

# API contract and test kit
{api}

# Existing human-written tests (do not repeat what they already check)
```python
{human}
```

Rules:
- Use the `fc` fixture (already defined in conftest.py; do not define it or import conftest).
- Imports allowed: pytest, datetime, decimal, re, finclusive.testkit. Nothing else.
- Today is 2026-01-01. Use fixed dates, never date.today().
- Name tests test_<rule>_<case>, with a one-line docstring naming the spec rule.
- Write about {n_tests} tests, covering as many different spec rules as you can.
"""

REPAIR = """These tests fail against a correct implementation of the spec, so the tests are wrong:
either the expectation misreads the spec, or the API is used incorrectly.

{failures}

Here is the full module:
```python
{code}
```

Return the whole module again with the failing tests fixed to match the spec and the API
contract. Keep every passing test unchanged. If you cannot tell what the spec requires for a
test, delete that test.
"""


class UnsafeCode(ValueError):
    pass


@dataclass
class GenerationReport:
    model: str
    output: str
    tests_generated: int = 0
    tests_kept: int = 0
    repair_rounds_used: int = 0
    removed_tests: list[str] = field(default_factory=list)


def extract_code(reply: str) -> str:
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", reply, flags=re.S)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    if "def test_" in reply:
        return reply.strip() + "\n"
    raise ValueError("The model's reply contains no Python code")


def check_code(code: str) -> ast.Module:
    """Parse ``code`` and refuse imports outside the allowlist."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise UnsafeCode(f"Generated code does not parse: {e}") from e
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) in {"exec", "eval", "__import__", "open"}:
                raise UnsafeCode(f"Generated code calls {node.func.id}()")
            continue
        for name in names:
            if name not in ALLOWED_IMPORTS:
                raise UnsafeCode(f"Generated code imports {name!r}, which is not allowed")
    return tree


def collect_test_names(code: str) -> list[str]:
    return [n.name for n in ast.parse(code).body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]


def remove_tests(code: str, names: set[str]) -> str:
    tree = ast.parse(code)
    tree.body = [n for n in tree.body if not (isinstance(n, ast.FunctionDef) and n.name in names)]
    return ast.unparse(tree) + "\n"


def failure_details(module: Path, names: list[str], limit: int = 4000) -> str:
    """pytest's own short output for the failing tests, to show the model."""
    ids = [f"{module}::{n}" for n in names]
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *ids, "-q", "-p", "no:cacheprovider", "--tb=short", "--no-header"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT), "FINCLUSIVE_BUG": ""},
        timeout=300,
    )
    return proc.stdout[-limit:]


def failing_tests(module: Path) -> list[str]:
    run = run_suite(module)
    return sorted(t.split("::")[-1] for t, o in run.outcomes.items() if o in ("failed", "error"))


def generate(
    out_dir: Path,
    complete: Callable[[str, str], str],
    n_tests: int = 30,
    repair_rounds: int = 2,
    model_name: str = "unknown",
) -> GenerationReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    module = out_dir / "test_ai_generated.py"
    (out_dir / "__init__.py").touch()
    if not out_dir.is_relative_to(ROOT / "suites"):
        # Suites outside suites/ don't see suites/conftest.py, so re-export its fixture.
        (out_dir / "conftest.py").write_text("from suites.conftest import fc  # noqa: F401\n")
    report = GenerationReport(model=model_name, output=str(module.relative_to(ROOT)) if module.is_relative_to(ROOT) else str(module))

    prompt = GENERATE.format(
        spec=SPEC.read_text(), api=API.read_text(), human=HUMAN_SUITE.read_text(), n_tests=n_tests
    )
    code = extract_code(complete(SYSTEM, prompt))
    check_code(code)
    report.tests_generated = len(collect_test_names(code))
    module.write_text(code)

    failing = failing_tests(module)
    while failing and report.repair_rounds_used < repair_rounds:
        report.repair_rounds_used += 1
        reply = complete(SYSTEM, REPAIR.format(failures=failure_details(module, failing), code=code))
        try:
            candidate = extract_code(reply)
            check_code(candidate)
        except (ValueError, UnsafeCode):
            break  # keep the last good module and prune below
        code = candidate
        module.write_text(code)
        failing = failing_tests(module)

    if failing:
        report.removed_tests = failing
        code = remove_tests(code, set(failing))
        module.write_text(code)
    report.tests_kept = len(collect_test_names(code))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "suites" / "ai_generated")
    parser.add_argument("--model", help="litellm model name (default: AITEST_MODEL or gemini/gemini-2.5-flash)")
    parser.add_argument("--tests", type=int, default=30, help="roughly how many tests to ask for")
    parser.add_argument("--repair-rounds", type=int, default=2)
    args = parser.parse_args(argv)

    complete = litellm_complete(args.model)
    report = generate(args.out.resolve(), complete, args.tests, args.repair_rounds, complete.model)
    print(json.dumps(asdict(report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
