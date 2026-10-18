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

Live LLM: copy `.env.example` to `.env`, put your key in it, save, and start the server. `.env` is read every
time the app starts, so it is permanent; it is git-ignored and excluded from Vercel uploads, so the key never leaves
your machine. Real environment variables, if set, override the file.

```
LLM_PROVIDER=groq
GROQ_API_KEY=your_key_here
GROQ_MODEL=openai/gpt-oss-20b
```

(or `LLM_PROVIDER=anthropic` with `ANTHROPIC_API_KEY` and optional `ANTHROPIC_MODEL`, default `claude-sonnet-5-5`).
The terminal prints `WealthGuard LLM: groq (live), model ...` at startup, and the page badge shows "live LLM"; if it
says mock, the key was not found or `USE_MOCK_LLM=1` is set. Leave `USE_MOCK_LLM` unset. If `LLM_PROVIDER` is unset, Anthropic is used when its key exists, else Groq. Tests ignore `.env` and always use the mock. The key is only ever read from the environment. If the network or key fails mid-demo, the app
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

## Knowledge base (vector database)

The real CSRC *Suitability Management Measures* (43 articles, Chinese original), our data sources, the historical stress
episodes, our compliance rules and 150 real **history cards** (one per US year 1928-2025 with returns and inflation, one per
China year 1985-2025 with inflation, deposit/lending rates and GDP growth, and decade averages, generated from the real CSVs) are indexed in a small vector database on SQLite + numpy (`app/vectorstore.py`,
`app/knowledge.py`): hashing TF-IDF vectors (Chinese character n-grams, English words), cosine search, no network or
model download, so mock mode, tests and Vercel behave the same. English questions reach the Chinese text through a small
EN->ZH glossary. Use the **Regulation & data search** card, or ask the chat ("What does the CSRC regulation say about
disclosing principal loss?"); the compliance panel also shows the **regulatory basis** (article) under each rule.
The index is rebuilt automatically when the data changes.

**Qdrant Cloud (optional, real vector database).** Create a free cluster at [cloud.qdrant.io](https://cloud.qdrant.io), copy
its https URL (REST port 6333) and an API key into `.env`:

```
QDRANT_URL=https://xxxx.region.cloud.qdrant.io:6333
QDRANT_API_KEY=your_key_here
```

On start the app mirrors the 211 chunks to a collection named `wealthguard_kb_<index version>` and answers searches through
Qdrant; the terminal prints `WealthGuard vector DB: qdrant`, `/api/health` shows `vector_db.backend`, and each search
response says which backend answered. `python scripts/check_qdrant.py` verifies the setup (verified on a real Qdrant Cloud free cluster). If the service is unreachable,
the key is wrong or the URL is not https, the app silently uses the local index (and retries after 60 s), so the demo never
depends on it. On Vercel, set the same two variables in the project settings. The key is sent only as an `api-key` header.
 Lexical retrieval is not deep semantic search; see known risks.

## Counterfactuals: "What would it take?"

Under each "why not" note, **What would it take?** shows, rule by rule (with the CSRC article), whether the product passes today, and
searches all 720 combinations of the five changeable questionnaire answers for the smallest set of *different answers* under which the
product would be eligible, using the real scoring and eligibility code. Facts that cannot change (age, horizon, income) are respected, so
an impossible case says so and why (for example Ms. Li and NovaYield: "even with the most favourable truthful answers your best bucket is
Growth, below the Aggressive this product needs"). It is an explanation, never advice to change an answer, and it changes nothing. The chat
answers the same question ("What would it take for NovaYield to be allowed?").

## Red-team arena

The **Red-team arena** card runs 54 deterministic attacks (about a second) against the live defences and shows which layer stopped each:
English and Chinese prompt injection, a poisoned brochure, the five forbidden (T3) actions, tool abuse, compliance bypasses (NovaYield,
guaranteed wording in both languages, concentration, jargon, minimums, a vulnerable client, missing disclosures), approval bypasses
(agent self-approval, cross-client, replay), purchase-history tricks, a hostile translation, a non-allowlisted URL, and four kinds of
audit tampering (on an in-memory copy). Three benign **controls** must *not* be flagged, so it is not just blocking everything.
No language model is called; results export as JSON and the run is audited.

## Self-inspection report (Art. 30)

The **Self-inspection report** card generates, from the hash-chained audit log, a report modelled on Article 30 of the CSRC
Measures (a periodic self-check): per regulatory duty (Art. 6, 18, 20, 21, 22, 23, 24, 32) how the system addresses it and the
evidence count, findings (drafts blocked before display and by which rule, injections flagged, forbidden actions refused,
approvals, chain validity) and an honest list of duties the demo does not implement. English or Chinese, downloadable as Markdown.

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
3. The compliance panel lists R1-R9 (and the LLM second opinion).
4. Click "Stress test: equities -20%" for portfolio loss and goal probability, then pick a **real** episode (2008, 2022, 1974, dot-com, Great Depression) from the dropdown: the shocks are the real returns of those years, followed by a rolling-window check on 1928-2025 history.
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
