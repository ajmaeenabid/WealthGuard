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
