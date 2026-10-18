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

Live LLM, PowerShell (use one provider):

```powershell
$env:LLM_PROVIDER="groq"; $env:GROQ_API_KEY="..."        # optional GROQ_MODEL, default openai/gpt-oss-20b
$env:LLM_PROVIDER="anthropic"; $env:ANTHROPIC_API_KEY="..."  # optional ANTHROPIC_MODEL, default claude-sonnet-5-5
```

Leave `USE_MOCK_LLM` unset. If `LLM_PROVIDER` is unset, Anthropic is used when its key exists, else Groq. The key is only ever read from the environment. If the network or key fails mid-demo, the app
falls back to the mock automatically and logs `llm_fallback_to_mock`. `WEALTHGUARD_DB` overrides the SQLite path.

## Voice and language

- **Mic** fills the chat box from speech (browser Web Speech API, Chrome or Edge); you press Send, so spoken and typed text take the same guarded path. **Read aloud** speaks replies. Some browsers send audio to their vendor for recognition; typing always works.
- **EN / 中文** toggle: fixed UI labels come from a dictionary; engine text (rationales, compliance details) is translated by `/api/translate`. Chinese is also accepted in chat (answers, injection and R7 checks). With `USE_MOCK_LLM=1` there is no translator, so dynamic text stays English (never a guess); use a live LLM to demo it.

## Purchase history and behaviour

A ledger of planned, bought and cancelled purchases. Type or speak a command (English or Chinese): "I bought headphones for 300", "plan to buy a laptop 6000", "I didn't buy the laptop", "change headphones to 250", "delete lunch", 买了耳机花了300元, 取消耳机. A command only creates a **proposal**; nothing changes until you click Confirm (voice can never confirm). The form buttons (Mark bought, Cancel item, Delete) are your own clicks. Totals, category/month sums and the guidance are computed by code from your entries, never by the model. Heavy or impulse-driven spending lowers risk *capacity* by at most 10 points; it can never raise risk. Ask the chat "How is my spending?" for a summary. "Load sample history" fills synthetic data for the demo.

## Real-world data

Clients and products stay synthetic. Real public data calibrates and grounds them. Every file is listed with its source, license and SHA-256 in `app/data/real/MANIFEST.json`; `python -I scripts/build_real_data.py` rebuilds the processed files from `app/data/real/raw/` (needs `pip install xlrd`, dev only).

| Dataset | Source | License | Used for |
|---|---|---|---|
| Annual returns 1928-2025 (S&P 500, small caps, T-bills, T-bonds, Baa bonds, real estate, gold) | [Damodaran, NYU Stern](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histretSP.html) | not stated; used with attribution, confirm before redistribution | calibrating returns, volatility, correlations, stress episodes |
| Monthly S&P 500, dividends, earnings, CPI, 10-year rate since 1871 | [Shiller via Open Knowledge mirror](https://datahub.io/core/s-and-p-500) | ODC-PDDL-1.0 (public domain) | real inflation and interest-rate episodes |
| China CPI inflation, deposit and lending rate, GDP growth | [World Bank Open Data](https://data.worldbank.org/country/china) | CC BY 4.0 | China-specific context |
| Suitability Management Measures, 43 articles (Chinese original) | [State Council Gazette](https://www.gov.cn/gongbao/content/2023/content_5742209.htm) (CSRC) | PRC regulations are not copyrightable (Copyright Law Art. 5) | grounding compliance explanations |

## Deploy to Vercel (frontend and backend together)

`api/index.py` serves the FastAPI app and the static UI as one serverless function; `vercel.json` routes every path to it.

```bash
npm i -g vercel
vercel login
vercel            # preview deploy
vercel --prod     # production deploy
```

In the Vercel project settings add environment variables as needed: `LLM_PROVIDER`, `GROQ_API_KEY` or `ANTHROPIC_API_KEY`
(and optionally `GROQ_MODEL` / `ANTHROPIC_MODEL`). With no key the hosted app runs on the deterministic mock LLM.
Vercel's disk is read-only except `/tmp`, so SQLite (and the audit chain) lives there per instance and resets on a cold
start; the tamper demo (`scripts/tamper_demo.py`) is a local-only step. Never commit keys; set them only in Vercel.

## Test

```bash
pytest
```

The suite runs fully on the mock LLM (profiling, allocation, one test per compliance rule, tiers, audit chain and
tamper detection, 12 injection strings, attack tests, Chinese R7/guard/answer parsing, translation, and an end-to-end persona flow).

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

8. Purchase history: click **Load heavy-spender sample**, read the insights, say "cancel the new phone" (Mic or type), then **Confirm**; ask the chat "How is my spending?".
9. Language: click **中文**, or answer in Chinese (e.g. 稳定, 大约10%, 卖出一部分); use Mic for speech.

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
| xlrd (dev only, rebuilds data) | BSD-3-Clause |

The project's own code is provided for the competition under the MIT license.
