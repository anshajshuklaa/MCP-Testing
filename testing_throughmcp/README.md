# FinClusive AI Test Lab

Can an LLM write better tests than a human? This project answers that with real runs instead of claims.

- **`finclusive/`** is a small FastAPI implementation of the FinClusive credit-card payment and rewards spec (`spec/FinClusive_Scenario.md`), with **16 switchable seeded bugs**.
- **`suites/human_baseline/`** holds the 7 original human-written tests, as executable pytest.
- **`harness/generate.py`** has an LLM write a pytest suite from the spec and API contract only. The code is safety-checked, run, repaired using the real failures, and pruned. No fallback tests are invented.
- **`harness/evaluate.py`** scores any suite: false alarms, code coverage, and how many seeded bugs it catches.
- **`harness/mcp_server.py`** is an MCP server, so Claude Desktop, Claude Code or any MCP client can be the test-writing agent while the server enforces the rules and keeps score.

## How a suite is scored

1. Run it on the correct app with coverage. A test that fails here is a **false alarm** and is ignored from then on, so an always-failing test can't "catch" everything.
2. Re-run it once per seeded bug (`FINCLUSIVE_BUG=<name>`). A bug is **caught** when a test that passed on the correct app now fails.
3. `tests/test_seeded_bugs.py` proves every seeded bug is observable through the API, so a missed bug is the suite's fault, not the harness's.

The seeded bugs are one-rule mistakes a reviewer would care about: points rounded up, early bonus needing 6 days instead of 5, an OTP threshold of ₹50k instead of ₹10k, no Luhn check, a 6th card allowed, the wrong redemption rate, and so on. The full list is in `finclusive/bugs.py`.

## Results

| Metric | Human baseline (7 tests) |
|---|---|
| Tests run | 6 (AP-001 skipped) |
| False alarms | 0 |
| Line / branch coverage | 82.0% / 50.0% |
| Seeded bugs caught | **3 / 16 (19%)** |

From `results/human_baseline.json`. AI-generated results go here once `harness.compare` has been run with a model (see below).

What the human baseline shows:
- **AP-001 tests an "Auto-Pay bonus" the spec never defines**, so it can't be executed. That's a requirements-traceability gap.
- **PP-001 pays ₹100 against a ₹1,250 minimum due**, so it never exercises the "no full-payment bonus on a minimum payment" rule.
- **Line coverage flatters.** 82% of lines ran, but only 3 of 16 wrong behaviours would be noticed.

## Run it

```bash
cd testing_throughmcp
pip install -r requirements.txt

python -m pytest                                   # harness tests + human suite
python -m harness.evaluate suites/human_baseline   # score one suite

export GEMINI_API_KEY=...                          # or ANTHROPIC_API_KEY / OPENAI_API_KEY, or a local Ollama
python -m harness.generate --model gemini/gemini-2.5-flash --out suites/ai_generated
python -m harness.compare suites/human_baseline suites/ai_generated --json results/comparison.json

uvicorn finclusive.app:app --reload                # browse the API at http://localhost:8000/docs
```

### Use it from an MCP client

```json
{"mcpServers": {"finclusive-tests": {
  "command": "python", "args": ["-m", "harness.mcp_server"],
  "cwd": "/path/to/MCP-Testing/testing_throughmcp"}}}
```

Tools: `get_product_docs`, `write_test_module`, `run_suite_on_correct_app`, `score_suite`, `generate_with_model`. `score_suite` returns counts only, so the client can't target the answer key.

## Design choices

- **Black-box generation.** The generator never sees `finclusive/` source, because the seeded-bug switches live there. It gets the spec, `spec/API.md` and the human tests.
- **Generated code is untrusted.** It must parse, may import only `pytest`, `datetime`, `decimal`, `re` and `finclusive.testkit`, and may not call `exec`/`eval`/`open`. This is a guardrail, not a sandbox; run unknown models in a container.
- **Fail loudly.** If the model's output can't be used, generation errors out. Tests that still fail after repair are removed and listed, never replaced with placeholders.
- **Limitations.** 16 hand-picked bugs is a small sample, and they were chosen by the same author as the app. State is in-memory, so there are no concurrency or persistence bugs. LLM results vary between runs, so compare several runs.

## Layout

```
spec/        FinClusive spec, API contract, original human test cases (JSON)
finclusive/  the app, business rules, seeded bugs, shared test kit
suites/      human_baseline/, ai_generated/ (created by harness.generate)
harness/     evaluate, generate, compare, llm, mcp_server
tests/       tests for the app's seeded bugs and for the harness
results/     saved evaluation output
```
