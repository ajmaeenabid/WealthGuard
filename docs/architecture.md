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
| `agent/*` | Tool definitions, loop, Anthropic/Groq wrapper + deterministic mock |
| `vectorstore.py` | Vector DB: SQLite tables `kb_chunks`/`kb_meta`, hashing TF-IDF embedder (1024 dims), cosine search |
| `qdrant_backend.py` | Optional Qdrant Cloud client over REST (httpx): create collection, upsert, query; allowlist-checked |
| `knowledge.py` | Builds the index from the CSRC text, MANIFEST, stress episodes and rules; EN->ZH glossary; `basis_for_rule` |
| `ledger.py` | Purchase ledger storage; EN/ZH command parser that only creates proposals; confirm/reject endpoints |
| `behaviour.py` | Deterministic totals, category/month sums, flags and guidance; capped one-way capacity penalty |
| `translate.py` | EN <-> ZH translation; output re-checked by R7, disclaimers fixed, falls back to English |
| `static/voice.js`, `static/i18n.js` | Mic and read-aloud (browser API); EN/ZH labels and on-demand text translation |
| `service.py`, `store.py`, `db.py` | Shared services and SQLite persistence |

## Additions to the Day-1 schemas

`ClientProfile.name/investable_amount_cny/goal_target_cny`, `Allocation.id/summary/client_text`,
`OrderTicket.kind/detail` (report tickets share the approval flow). The core fields are unchanged.

## Mock mode

`USE_MOCK_LLM=1` (or no API key) swaps in a pure function of (messages, state) that issues the same tool calls a real
model would, including a deliberately over-eager first draft that includes NovaYield, so the compliance block and
retry are visible offline and in tests.

## API

The API also includes `POST /api/translate` (T1, audited), `GET /api/state`, `GET /api/personas`, `GET /api/health`, `POST /api/reject/{ticket_id}`.

## Language handling

The agent, allocation engine and compliance engine work on English. Chinese input is understood directly (answer parsing, R7 phrase list, injection patterns); Chinese output is translated text, which is untrusted: it is re-checked for guaranteed-return wording in both languages and, on any doubt, the English original is shown. Disclaimers are replaced by fixed strings the model never sees. Voice input only fills the chat box.

## Purchase ledger and behaviour

Entries are `planned`, `bought` or `cancelled`; only `bought` counts as spending. Spoken or typed commands are parsed by fixed rules (no model) into a proposal row; `POST /api/ledger/confirm/{id}` applies it (T2-style explicit click, audited, single use, owner-checked). `behaviour.insights` derives every number and sentence from the entries and the client's stated income. `compute_risk_profile` subtracts the capped penalty from risk capacity, so the final bucket (the lower of tolerance and capacity) can only become more cautious. A ledger change that alters the penalty invalidates the stored profile so it is recomputed.

## Knowledge base and regulatory basis

`knowledge.ensure_index()` builds 211 chunks (43 CSRC articles, 4 data sources, 6 stress episodes, 8 rules, 150 history cards) and records a
fingerprint of the content; any change to the data or code rebuilds the index, an unchanged index is reused. Each rule
R1/R3-R7 has a fixed Chinese retrieval query; the best-matching CSRC article above a score threshold is returned by
`/api/state` as `regulatory_basis` and shown under the rule in the compliance panel (R2 and R8 have no matching article, so
nothing is shown). `search_knowledge` is a T0 tool and `/api/knowledge/search` is audited as a T0 read. The regulation text
is public data, so retrieved passages are not treated as untrusted instructions, but tool results never change tiers.
Quoting Article 4 (which denies that advice is a guarantee) passes R7 through a Chinese denial pattern.

### Vector backends

The local SQLite index is always built first (it holds the IDF weights and is the fallback). When `QDRANT_URL` and
`QDRANT_API_KEY` are set, `vectorstore.ensure_remote` mirrors the chunks to the collection `<prefix>_<fingerprint>` (reused if
it already holds every chunk, older versions deleted) and `search_ex` queries Qdrant with the locally computed query vector.
Any error (network, 4xx/5xx, bad shape, URL not allowlisted) falls back to the local index and starts a 60-second
cooldown, so a failing service is not hammered. The Qdrant origin joins the URL allowlist only while it is configured.

History cards (`knowledge.history_items`) are short English texts generated from `returns_annual.csv`, `shiller_monthly.csv` and
`china_macro.csv`: every figure is computed from the data (including Dec-to-Dec inflation and the real deposit return), missing
years carry no invented figure, and a few Chinese keywords let Chinese questions reach them.

## R9 plain language

`compliance.r9_plain_language` makes Article 24 of the CSRC Measures (warnings must be easy to understand) a deterministic
rule: average sentence length at most 24 words and no sentence over 40 (Chinese: 60 and 120 characters), Flesch reading
ease at least 40 for English text of 40+ words, and no jargon term (alpha, Sharpe, convexity, autocall, 久期, 敲入...) unless
a bracketed plain explanation follows it. A failure blocks the allocation like any other rule.

## Self-inspection report

`selfinspection.build` counts the audit log (compliance checks and failed rules, blocked reply wording, injections by source,
T3/invalid refusals, approvals, refused approvals, ledger confirmations, LLM fallbacks) and re-verifies the chain, then renders
duties, findings and gaps from fixed English/Chinese templates (no model). The report is audited after it is computed, so it
never counts itself; a broken chain becomes a high-severity finding.

## Red-team arena

`redteam.ATTACKS` is a list of (id, category, name, layer, runner). Runners call the real engines (`guard`, `tiers`, `compliance`,
`ledger`, `translate`, `audit`) on throw-away probe clients; none calls a language model, so results are reproducible. A result is
`defended` only if the intended layer stopped the attack; a crashing runner counts as a failure. Audit tampering works on an in-memory
copy of the rows via `audit.verify_rows`, never on the live log.

## Counterfactual compliance

`counterfactual.explain(client_id, product_id)` evaluates R1, R3, R4 and R5 for one product against the stored answers (each row cites the
CSRC article from `knowledge.basis_for_rule`), then enumerates every combination of the five changeable answers (loss reaction, income
stability, liquidity need, goal, experience), scoring each with `profiling.compute_scores` (minus any behaviour penalty) and testing
eligibility with the same logic as `allocation.eligible` (including the R5 cap). Paths are ordered by number of changed answers, then score
movement; if none exist, the reasons (vulnerable-client cap, lock-up longer than the horizon, best reachable bucket) are stated. It is a T1 tool
(`explain_counterfactual`) and an audited endpoint; it never writes to the profile.

## Advice receipt

`receipt.build` bundles the latest compliance-approved allocation with its compliance result, rule->article basis, dataset hashes (from
`MANIFEST.json`) and this client's audit entries (hashes only, no payloads), records the global chain head (`id`, `entry_hash`), and seals
the whole with `content_hash` = SHA-256 of the canonical JSON and `checkpoint.mac` = HMAC-SHA256(key, content_hash | head). `receipt.verify`
runs eight checks: content_hash, entry_hashes, membership, anchor (head still where it was and the chain up to it verifies), checkpoint,
data_hashes, compliance, same_allocation. The key is `RECEIPT_KEY` or a random value stored in `app_meta` with the database.

## Number provenance

`provenance.explain(client_id, kind, ...)` supports nine kinds (tolerance, capacity, bucket, expected_return, volatility, stress_loss,
goal_probability, backtest_share, ledger_total). Each returns the formula, the inputs with sources (client answers; `products.json` with its
hash; real datasets with license and SHA-256 from `MANIFEST.json`) and a recomputation through the same engine function; `stress_loss` for
historical scenarios recomputes straight from `returns_annual.csv` with separate arithmetic. `GET /api/provenance` is a T0 read, audited as
`provenance_viewed` with the match flag.

## Revealed-risk replay

`replay.start` builds a session from the client's profile and latest compliance-approved allocation (or 100% equities): the monthly portfolio
return is the weighted sum of its asset classes' mapped series (`realdata.ASSET_MIX`), with the S&P 500 monthly price index from Shiller for
equities and the year's Damodaran return spread evenly for bonds, cash and gold, minus weighted fees. A risky sleeve and a cash sleeve are
tracked; at the first 10%/20%/30% drawdown the session pauses for a choice (hold, sell 25%, sell all, buy 10% of the start). `_result` compares
the reaction at -20% (plus any earlier cautious sale) with the stored `loss_reaction` answer; `apply` is only allowed when strictly more cautious,
replaces the answer, invalidates the profile and is audited (`replay_started`, `replay_finished`, `replay_applied`). Sessions are in memory.

## Whisper voice commands

`static/voice.js` records a short clip (MediaRecorder, at most 30 s) and posts the raw bytes to `POST /api/transcribe`; the answer is text that is
placed in the chat or purchase-command box, never sent to the agent automatically. `transcribe.py` validates the upload (size limit of 2 MB, file
signature for webm/ogg/wav/mp3/m4a/flac, language en/zh, 20 requests per client per minute), then calls Groq's `/openai/v1/audio/transcriptions` with
`verbose_json` (so segments Whisper itself marks as silence are dropped), a vocabulary prompt, and the allowlisted URL check, or runs faster-whisper
locally on a temporary file that is always deleted. Stock silence phrases ("Thank you for watching", 谢谢观看) are discarded. Mock mode turns it off.
