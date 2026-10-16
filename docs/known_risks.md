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
