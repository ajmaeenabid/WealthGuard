# WealthGuard - Compliant Wealth Advisory Agent

2026 Shenzhen International FinTech Competition, International Track, Topic B (Wealth Advisory Agent).

> **Educational demo with synthetic products. Not real financial advice.**
> All data is synthetic: no real customers, products, money, or broker/bank APIs.

An AI wealth-advisory agent that profiles a client, compares products, proposes an explainable allocation, and
**cannot show or execute anything until an independent compliance layer approves it**. Every step is audited in a
tamper-evident hash chain.

## Install

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
```

Python 3.11+.

## Run

```bash
# offline / deterministic demo (no network or key needed)
set USE_MOCK_LLM=1             # PowerShell: $env:USE_MOCK_LLM="1";  bash: export USE_MOCK_LLM=1
python scripts/demo_seed.py    # resets the DB (optional)
python -m uvicorn app.main:app --port 8000
# open http://localhost:8000
```

Live LLM via Groq: set `GROQ_API_KEY` (optional `GROQ_MODEL`, default `openai/gpt-oss-20b`). Via Anthropic: set `ANTHROPIC_API_KEY` (and optionally `ANTHROPIC_MODEL`, default `claude-sonnet-5-5`) and leave
`USE_MOCK_LLM` unset. The key is only ever read from the environment. If the network or key fails mid-demo, the app
falls back to the mock automatically and logs `llm_fallback_to_mock`. `WEALTHGUARD_DB` overrides the SQLite path.

## Test

```bash
pytest
```

The suite runs fully on the mock LLM (profiling, allocation, one test per compliance rule, tiers, audit chain and
tamper detection, 12 injection strings, attack tests, and an end-to-end persona flow).

## Demo steps (5 minutes)

1. Pick **Ms. Li**, Start session, say "Hi". Answer the three questions with the buttons (only unknown facts are asked).
   The profile card shows tolerance vs capacity and the final bucket (the lower of the two).
2. The agent's first draft contains the tempting **NovaYield Note**; the **draft log** shows it BLOCKED (R1, R3) and the
   revised draft passing. The allocation table shows a rationale per line, and "Why not that product?" explains NovaYield.
3. The compliance panel lists R1-R8 (and the LLM second opinion).
4. Click "Stress test: equities -20%" for portfolio loss and goal probability.
5. Click "Create order ticket", then **Approve** in the queue (T2 needs this click). Click **Verify log**: chain valid.
6. Attack: in section 6 click "Load attack sample" then Upload. The guard quotes the injected sentences. Re-run the flow
   with the same client: the allocation is unchanged and compliance still blocks NovaYield.
7. Tamper: `python scripts/tamper_demo.py` edits one audit row in SQLite; click Verify log: it fails at that row.
   Also try "Try a forbidden action" (T3 refusal, logged).

Other personas: **Mr. Chen** (Growth allocation passes), **Mr. Wang** (68, capped to Moderate by R5).

## Documentation

`docs/architecture.md`, `docs/algorithm.md`, `docs/security_report.md`, `docs/known_risks.md`.
Evidence export: `python scripts/export_audit.py > audit_log.json`.

## Third-party libraries (all open source)

| Library | License |
|---|---|
| FastAPI | MIT |
| Uvicorn | BSD-3-Clause |
| Pydantic | MIT |
| NumPy | BSD-3-Clause |
| Anthropic Python SDK | MIT |
| pytest | MIT |
| HTTPX (tests) | BSD-3-Clause |
| Chart.js (CDN, frontend) | MIT |
| SQLite (stdlib) | Public domain |

The project's own code is provided for the competition under the MIT license.
