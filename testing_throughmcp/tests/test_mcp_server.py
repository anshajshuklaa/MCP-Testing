"""End-to-end: a real MCP client talks to the server over stdio."""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from harness.evaluate import ROOT

GOOD = '''
from datetime import date


def test_min_payment(fc):
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, 5000, 250, date(2026, 1, 3))
    assert fc.pay(card, 99).status_code == 422


def test_wrong(fc):
    fc.register()
    assert fc.rewards()["tier"] == "Gold"
'''


async def _session_run(suites_dir: Path):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "harness.mcp_server"],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT), "AITEST_SUITES_DIR": str(suites_dir)},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = {t.name for t in (await session.list_tools()).tools}
        docs = (await session.call_tool("get_product_docs", {})).content[0].text
        written = await session.call_tool("write_test_module", {"name": "demo", "code": GOOD})
        refused = await session.call_tool("write_test_module", {"name": "bad", "code": "import os\n"})
        escape = await session.call_tool("score_suite", {"suite": "../../etc"})
        return tools, docs, json.loads(written.content[0].text), refused, escape


def test_mcp_client_can_write_and_run_tests(tmp_path: Path):
    tools, docs, written, refused, escape = asyncio.run(_session_run(tmp_path / "suites"))

    assert {"get_product_docs", "write_test_module", "run_suite_on_correct_app", "score_suite"} <= tools
    assert "Minimum payment" in docs and "bug ==" not in docs
    assert written["tests"] == 2
    assert written["failing"] == ["test_wrong"]
    assert "Gold" in written["failure_output"]
    assert refused.isError and "not allowed" in refused.content[0].text
    assert escape.isError
