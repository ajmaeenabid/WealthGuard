# WealthGuard - Compliant Wealth Advisory Agent

2026 Shenzhen International FinTech Competition, International Track, Topic B (Wealth Advisory Agent).

> **Educational demo with synthetic products. Not real financial advice.**
> Advisor clients and products are synthetic: no real customers, products, money, or broker/bank APIs.

WealthGuard has two parts that share one sign-in:

- **Advisor** - an AI wealth-advisory agent that profiles a client, compares products and proposes an explainable allocation. It **cannot show or execute anything until an independent compliance layer approves it**, and every step is written to a tamper-evident hash-chained audit log.
- **My money** - a personal-finance module (accounts, income, expenses, transfers, budgets, reports) with a chat-style **money assistant**. The assistant only *reads* your message into a structured guess; the backend decides what to ask next and nothing is saved until you confirm.

Stack: FastAPI, SQLite, pydantic v2, vanilla JS (no frontend build step), Chart.js from a CDN.

## Features

### Advisor
- Risk profile (tolerance vs capacity, the lower of the two wins), allocation with a rationale per line, product comparison.
- Compliance layer (rules R1-R9 plus an LLM second opinion), stress tests (including real historical episodes), approval queue for order tickets, forbidden actions refused and logged.
- Insights: purchase history and behaviour, history replay, regulation search. Trust and evidence: advice receipt, red-team arena, self-inspection report, document upload (prompt-injection guard), audit log.
- Answers are grounded in the signed-in user's own database rows, not in model memory. A per-user context summary is kept in the database and refreshed from what the user tells the app.

### My money
- Accounts, income, expenses, transfers, budgets, goals, reports and charts. Money is stored as integer minor units and the API uses decimal strings (floats are rejected).
- Money assistant in English, Chinese and Bangla. Rules-based extraction runs first; the model (Groq `openai/gpt-oss-20b` with a strict JSON schema) only fills gaps. A draft is shown, you confirm, then it is saved. Requests are idempotent (request id), and each user has a lock against double submits.
- Chat conversations can be renamed; names are stored in the database.
- A **primary account** can be chosen as the default for new entries.

### Currency and exchange rates
- Three currencies: **USD, CNY, BDT**. The display currency is a setting; choosing a **region** (Bangladesh, China) sets the matching currency.
- Real conversion, not relabelling: USD is the pivot. Rates come from two keyless providers (open.er-api.com as primary, a jsDelivr currency dataset as cross-check). If they disagree by more than 3% the conversion is refused. Rates are cached in the database with their source, provider date and fetch time; stale rates are flagged and refused after 72 hours; no rate is ever invented.
- Results are rounded to minor units (half up). The original amount and the rate used are stored next to the converted figure, and a quote pinned to a draft is re-checked if you confirm more than 30 minutes later.
- Rates are indicative mid-market rates, not what a bank or exchange would give you.

### Languages and jurisdictions
- Interface and assistant: **English, Simplified Chinese (zh-CN) and Bangla (bn-BD)**; switchable on the sign-in page and inside the app.
- Jurisdiction (Bangladesh or China) is a separate setting from the language, so a Bangla speaker in China still gets China rules and the other way round. Per-jurisdiction data is kept isolated.

### Interface
- Light theme (grey canvas, white cards, lime `#b3f948` accent) and dark theme (near-black with a green glow). Both come from shared design tokens in `static/tokens.css`, with automated contrast tests.
- Thinking animation while the model works, token-by-token reply rendering, and markdown tables in answers.
- Hard AI deadlines: if the provider does not answer in time the user sees a clear error instead of waiting, and the rules-based path takes over where it can.
- Prompt and context **token budgets** (`app/finance/tokens.py`) truncate long history so inputs and outputs stay inside the model limits.
- **Voice**: microphone fills the chat box (Whisper via Groq, local `faster-whisper`, or the browser speech API), read-aloud for replies, and a turn-based voice mode. Spoken text takes the same guarded path as typed text and voice can never confirm an action.
- Admin portal, reports, per-user memory, and a sign-in page with English/Chinese/Bangla and theme switches.

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
python scripts/demo_seed.py    # resets the DB and creates the demo users (optional)
python -m uvicorn app.main:app --port 8000
# open http://localhost:8000
```

### Configuration (`.env`)

Copy `.env.example` to `.env` and fill in the values you need. **`.env` is git-ignored and must never be committed**; only the placeholder file `.env.example` is in the repository. Real environment variables override the file. Minimum for live AI:

```
LLM_PROVIDER=groq
GROQ_API_KEY=your_key_here
GROQ_MODEL=openai/gpt-oss-20b
```

(or `LLM_PROVIDER=anthropic` with `ANTHROPIC_API_KEY`). The terminal prints which provider is active at startup. If the key or network fails, the advisor falls back to the deterministic mock and logs `llm_fallback_to_mock`.

Other settings in `.env.example` cover: the money-assistant model and limits (`FINANCE_MODEL`, `FIN_AI_*`), AI deadlines, token budgets, exchange rates (`FX_PROVIDER`, `FX_CACHE_HOURS`, `FX_MAX_STALE_HOURS`, `FX_TIMEOUT`), Whisper (`WHISPER_*`), Qdrant (`QDRANT_*`), `RECEIPT_KEY`, `WEALTHGUARD_DB` and `FIN_TZ`.

Check your setup without starting the server:

```bash
python scripts/check_env.py
```

It reports unknown, misspelled or malformed variables (values are never printed). Set `WEALTHGUARD_STRICT_CONFIG=1` to make the app refuse to start on a bad configuration.

## Test

```bash
pytest
```

The suite runs on the mock LLM and with exchange rates switched off by default (tests that need conversion use fixtures). It covers the advisor pipeline, compliance rules, audit chain, money handling, FX, the assistant in three languages, jurisdiction isolation, token budgets, deadlines, markdown rendering, voice mode, design tokens and more.

An opt-in browser test drives headless Edge/Chrome through the My money flows (slow):

```bash
RUN_E2E=1 pytest tests/test_e2e_browser.py     # PowerShell: $env:RUN_E2E="1"; pytest tests/test_e2e_browser.py
```

## Known limits

- Only USD, CNY and BDT are supported.
- Exchange rates are indicative; budget and report charts do not blend amounts in other currencies.
- The Bangla wording has not had a native-speaker review.
- Voice mode is turn-based and has not been tested with real Whisper on Bengali speech.
- Live Groq extraction of the assistant's `currency` field was tested only against a stub, not against the live model.
- The advisor uses synthetic products and clients; it is a demonstration, not advice.
- Dataset licences (below) should be checked again before this repository is ever made public.
- See `docs/known_risks.md` for the longer list.

## Real-world data

Clients and products stay synthetic. Real public data calibrates and grounds them. Every file is listed with its source, license and SHA-256 in `app/data/real/MANIFEST.json`; `python -I scripts/build_real_data.py` rebuilds the processed files from `app/data/real/raw/` (needs `pip install xlrd`, dev only).

| Dataset | Source | License | Used for |
|---|---|---|---|
| Annual returns 1928-2025 (S&P 500, small caps, T-bills, T-bonds, Baa bonds, real estate, gold) | [Damodaran, NYU Stern](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histretSP.html) | not stated; used with attribution, confirm before redistribution | calibrating returns, volatility, correlations, stress episodes |
| Monthly S&P 500, dividends, earnings, CPI, 10-year rate since 1871 | [Shiller via Open Knowledge mirror](https://datahub.io/core/s-and-p-500) | ODC-PDDL-1.0 (public domain) | real inflation and interest-rate episodes |
| China CPI inflation, deposit and lending rate, GDP growth | [World Bank Open Data](https://data.worldbank.org/country/china) | CC BY 4.0 | China-specific context |
| Suitability Management Measures, 43 articles (Chinese original) | [State Council Gazette](https://www.gov.cn/gongbao/content/2023/content_5742209.htm) (CSRC) | PRC regulations are not copyrightable (Copyright Law Art. 5) | grounding compliance explanations |

Exchange rates are fetched at runtime from open.er-api.com and a jsDelivr-hosted currency dataset; check their terms for your use.

## Knowledge base (vector database)

The CSRC *Suitability Management Measures*, the data sources, historical stress episodes, compliance rules and 150 history cards (US years 1928-2025, China years 1985-2025, decade averages) are indexed in a small vector database on SQLite + numpy (`app/vectorstore.py`, `app/knowledge.py`): hashing TF-IDF vectors, cosine search, no network or model download. English questions reach the Chinese text through a small EN->ZH glossary. Retrieval is lexical, not deep semantic search.

**Qdrant Cloud (optional).** Put `QDRANT_URL` (https, REST port 6333) and `QDRANT_API_KEY` in `.env` and the app mirrors the index to Qdrant; `python scripts/check_qdrant.py` verifies it. If the service is unreachable the app silently uses the local index.

## Trust and evidence tools

- **Click any number**: dotted numbers open the formula in words, each input with its source, and a fresh recomputation with a match flag.
- **Advice receipt**: downloadable JSON sealed by a content hash and an HMAC checkpoint tied to the audit chain; verify offline with `python scripts/verify_receipt.py receipt.json`. Set `RECEIPT_KEY` so receipts stay verifiable across restarts.
- **Replay**: relive a real episode (2008, dot-com, 2022, the 1970s, the Great Depression) month by month; behaviour can only make the profile more cautious.
- **Counterfactuals**: "What would it take?" searches the changeable questionnaire answers for the smallest truthful change that would make a product eligible.
- **Red-team arena**: 54 deterministic attacks plus benign controls against the live defences, no model called.
- **Self-inspection report**: a report modelled on Article 30 of the CSRC Measures, generated from the audit log, in English or Chinese.

## Deploy to Vercel

`api/index.py` serves the FastAPI app and the static UI as one serverless function; `vercel.json` routes every path to it.

```bash
npm i -g vercel
vercel login
vercel            # preview deploy
vercel --prod     # production deploy
```

Set environment variables in the Vercel project settings (never in the repository). With no key the hosted app runs on the deterministic mock. Vercel's disk is read-only except `/tmp`, so SQLite and the audit chain live there per instance and reset on a cold start.

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
