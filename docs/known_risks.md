# Known Risks and Limitations

> Educational demo with synthetic products. Not real financial advice.

1. **No authentication.** `client_id` is a bearer secret. A real system needs login, sessions and per-user authorisation.
2. **Audit tail truncation.** Deleting the most recent entries (or the whole DB) is not detectable by the chain alone.
   Mitigation for production: periodically anchor the head hash externally (WORM storage, a signed timestamp).
3. **Same trust domain.** Anyone with write access to the SQLite file could recompute the whole chain. A keyed HMAC with a
   key held outside the app would close this.
4. **Regex-based injection detector.** It is deliberately a first layer; novel phrasings or other languages can evade it.
   The decisive defence is structural (compliance + tiers), which does not depend on detection.
5. **Deterministic compliance is only as good as its rules.** R7 uses a phrase list; creative misleading wording could pass.
   The LLM reviewer adds a second opinion but is advisory and can fail open if unavailable (it can never loosen a rule).
6. **Simplified finance.** Flat correlation, class-level shocks, lognormal returns, no tax or transaction costs. Results are
   illustrative, not forecasts.
7. **Synthetic suitability model.** Questionnaire weights are transparent but not calibrated to regulation. Real use would
   follow local KYC/suitability rules.
8. **Mock LLM is scripted.** Demo mode shows the safety architecture, not model quality; live mode quality depends on the model.
9. **Single-process state.** Chat history and pending questions are in memory; a restart loses conversation context (not
   audit or business data).
10. **Prompt-injection through chat.** User messages are flagged but still processed; the user is the principal. Harmful
    requests are stopped by the engines, not by refusing to read.
11. **Chinese coverage is phrase-based.** R7 and the injection guard cover common Chinese wording, not every paraphrase, dialect or mixed-script trick. The structural defence (compliance + tiers) is language independent.
12. **Translation quality is unreviewed.** Live translations are not checked by a human or a second model; only unsafe wording is caught. Mock mode has no translator and shows English.
13. **Voice privacy.** Browser speech recognition may send audio to the browser vendor. The app never receives audio, only the text the user chooses to send.
14. **Third-party LLM.** With Groq or Anthropic, client facts (synthetic here) and chat text are sent to that provider. A real deployment needs a data-processing agreement and data minimisation.
15. **Ledger is self-reported.** Behaviour insights use only what the client enters (or sample data) and the stated income; they are guidance, not a credit or spending assessment. Impulse is a client-set tag.
16. **Command parser is rule-based.** Unusual phrasings are refused with an example rather than guessed; Chinese numerals (e.g. 三百) are not parsed, digits are.
17. **Behaviour data is sensitive.** A real system would need explicit consent, retention limits and access control; the demo uses synthetic entries only.
18. **Real data is history, not a forecast.** Damodaran and Shiller series are US-centric and backward-looking; China macro data is annual and has gaps (inflation starts in 1987). The demo calibrates synthetic products on them and says so.
19. **Damodaran terms.** The page states no explicit license; the data is cited with attribution for an educational demo. Confirm before any redistribution beyond the competition.
20. **Regulation text is a consolidated reprint.** Taken from the State Council Gazette; the CSRC site is authoritative and the law can change. It is retrieval context, not legal advice.
21. **US history as a proxy.** Scenario shocks and the backtest use US returns for synthetic CNY products; currency, China market structure and the asset-class blends (e.g. bond = 60% T-bond + 40% T-bill) are assumptions.
22. **Two probabilities can disagree.** Monte Carlo uses the products' conservative assumptions; the backtest uses real US returns, which were higher. Both are shown and neither is a forecast.
23. **Rolling windows overlap** and survivorship favours the US market, so the share of windows reaching a goal overstates what a typical future path may deliver.
24. **Retrieval is lexical.** The embedder matches Chinese character n-grams and English words, not meaning: rare phrasings, long conversational questions and short Chinese queries can miss the best article. The EN->ZH glossary is hand-written. A neural multilingual embedder can replace the `_tf` function without changing the store.
25. **Regulatory basis is a pointer, not legal analysis.** The article shown is the best textual match to a fixed query and a rule may relate to several articles; the demo does not claim legal compliance.
26. **R7 denial pattern.** Chinese statements that deny a guarantee (不表明/不代表...保证) are not flagged so the regulation can be quoted; a sentence that both denies and then promises is still flagged.
27. **Qdrant verification.** The client follows Qdrant's documented REST API and is unit-tested against an in-memory stand-in. It was also run against a real Qdrant Cloud free cluster (AWS us-west-1) on 2026-10-18 with `python scripts/check_qdrant.py`: the then 61 chunks (now 211 with history cards, re-uploaded automatically) uploaded and a filtered search answered by Qdrant. That run found Qdrant Cloud's strict mode (filters need a payload index), now handled. Other clusters or future Qdrant versions may behave differently; the local index is the fallback.
28. **Free cluster limits.** Free tiers are small and may pause or change; the local index is the real fallback. Chunk text (public regulation, our notes) is stored in Qdrant, never client data or ledger entries.
29. **Readability is a heuristic.** R9 uses sentence length, a Flesch score and a short jargon list; it cannot judge whether a
    particular client understood. The jargon list is hand-written and the Chinese check is character-count based.
30. **Report scope.** The default report covers all sessions in the deployment (aggregate counts, no client identifiers); in the public
    demo any user can read those aggregates. It is generated on demand, not on a half-yearly schedule, and is not filed anywhere.
31. **The arena is our own attacks.** It demonstrates that the defences hold against this battery, not against an independent penetration test or
    novel attacks. It leaves probe clients and audit entries in the database (labelled "Red-team probe").
32. **Counterfactuals could be misused to game suitability.** The output lists what would have to be true and says it is not advice to change
    answers; it still shows which answers would matter. A real deployment would withhold it from the client or require adviser review.
33. **Single-product view.** The explanation is per product (R1, R3, R4, R5); portfolio-level limits (equity share, concentration) are not part of it.
34. **Receipt key custody.** The HMAC key lives with the server (env or database); anyone holding it can mint receipts. Without `RECEIPT_KEY`, a
    restart on an ephemeral disk (Vercel `/tmp`) generates a new key and a new empty log, so older receipts no longer verify there. Verification of
    membership and anchor needs the issuing server; only the content, entry and dataset hashes can be checked offline.
35. **Receipts are not legal signatures.** The checkpoint is a symmetric HMAC (verified by the issuer), not a public-key signature or a trusted
    timestamp.
36. **Recomputation shares code.** Except for historical stress scenarios (independent re-read of the CSV), the recomputation calls the same engine function
    as the displayed value, so it detects stale or tampered stored values, not a logic error inside that function (the unit tests cover those).
37. **Replay is a simplification.** Equity months use Shiller's monthly *average* price index (dividends omitted), other classes use annual returns spread
    evenly, so intra-year dynamics are smoothed and drawdowns are slightly milder than daily closes. A game decision is not a real-money decision.
38. **Replay sessions are in memory** (lost on restart or between serverless instances). The inference uses one episode and one reaction; it is a nudge for
    the client, not a psychometric test.
39. **Voice privacy.** With the Whisper engine the audio clip leaves the machine for the transcription service (Groq); the browser engine may send it to the browser
    vendor. The local provider (faster-whisper) keeps audio on the machine. Do not speak real personal data in the demo.
40. **Whisper is not perfect.** It can mishear numbers, product names and Chinese homophones and can invent text from noise; the vocabulary hint and the silence filter reduce this,
    and the user always sees and confirms the text before it is used. The local provider was tested against a stand-in, not with a real downloaded model.
41. **Quota and body limits.** Each clip costs a (tiny) transcription request and is capped at 2 MB (about 2 minutes) to stay under hosting body limits; a rate limit protects the
    API key from abuse of the public demo endpoint.
