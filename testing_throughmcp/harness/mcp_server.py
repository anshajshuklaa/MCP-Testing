"""MCP server: lets any MCP client (Claude Desktop, Claude Code, Cursor...) act as
the test-writing agent, while the server enforces the rules and keeps score.

Tools:
- get_product_docs: the FinClusive spec and API contract (the only product
  knowledge a test writer gets; never the source code)
- write_test_module: save a pytest module after the same safety checks as
  harness/generate.py, run it on the correct app, and return the failures
- run_suite_on_correct_app: run a saved suite on the correct app
- score_suite: coverage and seeded-bug detection, as numbers only. Bug names
  are withheld so the client can't write tests aimed at a known answer key.
- generate_with_model: run harness/generate.py with a litellm model

Run it over stdio:
    python -m harness.mcp_server
Claude Desktop config:
    {"mcpServers": {"finclusive-tests": {"command": "python",
      "args": ["-m", "harness.mcp_server"], "cwd": "<repo>/testing_throughmcp"}}}
"""

import os
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from harness import generate as gen
from harness.evaluate import ROOT, evaluate, run_suite

# Overridable so tests can point the server at a scratch directory.
SUITES = Path(os.environ.get("AITEST_SUITES_DIR") or ROOT / "suites").resolve()
CLIENT_SUITE = SUITES / "mcp_client"

mcp = FastMCP("finclusive-tests")


def _suite_path(suite: str) -> Path:
    """Resolve a suite name under suites/, refusing anything outside it."""
    path = (SUITES / suite).resolve()
    if not path.is_relative_to(SUITES) or not path.exists():
        raise ValueError(f"Unknown suite {suite!r}. Suites live under suites/, e.g. 'human_baseline'.")
    return path


@mcp.tool()
def get_product_docs() -> str:
    """The FinClusive specification and API contract, including the pytest `fc` test kit."""
    return f"# Specification\n\n{gen.SPEC.read_text()}\n\n{gen.API.read_text()}"


@mcp.tool()
def write_test_module(name: str, code: str) -> dict:
    """Save a pytest module to suites/mcp_client/test_<name>.py and run it on the correct app.

    Use the `fc` fixture; allowed imports are pytest, datetime, decimal, re and
    finclusive.testkit. Any failing test is wrong (the app is correct): read the
    failure, fix the test, and write the module again.
    """
    if not re.fullmatch(r"[a-z0-9_]{1,40}", name):
        raise ValueError("name must be 1-40 characters of a-z, 0-9 and _")
    gen.check_code(code)
    CLIENT_SUITE.mkdir(parents=True, exist_ok=True)
    (CLIENT_SUITE / "__init__.py").touch()
    if not SUITES.is_relative_to(ROOT / "suites"):
        # Outside suites/ the shared conftest isn't visible; re-export the fixture.
        (CLIENT_SUITE / "conftest.py").write_text("from suites.conftest import fc  # noqa: F401\n")
    module = CLIENT_SUITE / f"test_{name}.py"
    module.write_text(code)
    failing = gen.failing_tests(module)
    return {
        "saved": str(module.relative_to(SUITES.parent)),
        "tests": len(gen.collect_test_names(code)),
        "failing": failing,
        "failure_output": gen.failure_details(module, failing) if failing else "",
    }


@mcp.tool()
def run_suite_on_correct_app(suite: str = "mcp_client") -> dict:
    """Run a suite under suites/ (e.g. 'human_baseline', 'mcp_client') and return each test's outcome."""
    return run_suite(_suite_path(suite)).outcomes


@mcp.tool()
def score_suite(suite: str = "mcp_client") -> dict:
    """Score a suite: false alarms, coverage, and how many seeded bugs it catches (count only)."""
    ev = evaluate(_suite_path(suite))
    return {
        "suite": ev.suite,
        "tests_passing": len(ev.passed),
        "false_alarms": ev.false_alarms,
        "line_coverage": ev.line_coverage,
        "branch_coverage": ev.branch_coverage,
        "bugs_caught": len(ev.bugs_caught),
        "bugs_total": len(ev.bugs_caught) + len(ev.bugs_missed),
    }


@mcp.tool()
def generate_with_model(model: str, n_tests: int = 30) -> dict:
    """Have a litellm model (e.g. 'gemini/gemini-2.5-flash') write suites/ai_generated. Needs that provider's API key."""
    from dataclasses import asdict

    from harness.llm import litellm_complete

    complete = litellm_complete(model)
    return asdict(gen.generate(SUITES / "ai_generated", complete, n_tests, model_name=model))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
