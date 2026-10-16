# Architecture

> Educational demo with synthetic products. Not real financial advice.

## Principle

The language model **proposes**; two deterministic engines **dispose**. Nothing the model says can bypass the tier
engine (what may be done) or the compliance engine (what may be shown).

```
 Browser (static HTML/JS/Chart.js)
        |  JSON
 FastAPI  app/main.py  -----------------------------+
        |                                           |
 agent/loop.py  <->  agent/llm.py (Anthropic | mock) |  REST routes call the same services
        | tool calls                                |
 security/tiers.py  (validate args, tier check, audit)
        |
 agent/tools.py  -> profiling | allocation | comparison | simulator | compliance
        |
 SQLite: clients, allocations, tickets, documents, audit (hash chain)
```

## Request flow (chat)

1. `loop.run_turn` audits the message, scans it with the injection guard, records an answer to a pending
   profiling question, then builds the message list (uploaded documents are wrapped as untrusted data).
2. The LLM returns text or tool calls. Every call goes to `tiers.execute`, which rejects unknown tools and unknown
   fields, refuses T3, stages T2, runs T0/T1 handlers, and audits each call.
3. `propose_allocation` creates a **draft**. `check_compliance` runs R1-R8 plus the LLM reviewer. Only a passing
   allocation becomes visible (`store.latest_allocation` returns passed ones only); stress tests, reports and
   tickets refuse non-compliant allocations.
4. A failed draft is revised using `violating_product_ids` (at most 3 blocked drafts per request, then an honest
   refusal).
5. The final reply is checked for guaranteed/risk-free wording (R7) and always ends with the disclaimer.

## Modules

| Module | Role |
|---|---|
| `schemas.py` | All pydantic models, `StrictArgs` base rejecting unknown tool fields |
| `config.py` | Bucket table, templates, limits, env access, `effective_bucket` (R5) |
| `profiling.py` | Adaptive questionnaire, tolerance/capacity scoring, lower-of rule |
| `allocation.py` | Constrained allocation + per-line rationale + disclosures |
| `comparison.py` | Side-by-side table and specific "why not" text |
| `simulator.py` | Stress scenarios, Monte Carlo goal probability |
| `compliance.py` | R1-R8 engine and LLM second opinion (stricter-only) |
| `security/tiers.py` | T0-T3 enforcement, approval endpoint logic, URL allowlist |
| `security/audit.py` | Append-only SHA-256 hash chain and `verify` |
| `security/guard.py` | Injection detector, redaction, untrusted wrapper |
| `agent/*` | Tool definitions, loop, Anthropic wrapper + deterministic mock |
| `service.py`, `store.py`, `db.py` | Shared services and SQLite persistence |

## Additions to the Day-1 schemas

`ClientProfile.name/investable_amount_cny/goal_target_cny`, `Allocation.id/summary/client_text`,
`OrderTicket.kind/detail` (report tickets share the approval flow). The core fields are unchanged.

## Mock mode

`USE_MOCK_LLM=1` (or no API key) swaps in a pure function of (messages, state) that issues the same tool calls a real
model would, including a deliberately over-eager first draft that includes NovaYield, so the compliance block and
retry are visible offline and in tests.

## API

As in CLAUDE.md, plus `GET /api/state`, `GET /api/personas`, `GET /api/health`, `POST /api/reject/{ticket_id}`.
