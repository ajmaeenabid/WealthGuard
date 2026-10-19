"""Per-user preferences for the finance module (AI explanations, assistant language, how often to ask about discounts, retention)."""
from app import store
from app.finance import books, jurisdictions, money
from app.finance.books import FinanceError

LANGS = ("auto", "en", "bn", "zh")
UI_LANGS = ("zh", "en", "bn")
SPEECH_LANGS = ("auto", "zh", "en", "bn")
ADJUSTMENT_POLICIES = ("auto", "always", "never")
HISTORY_RANGE = (7, 730)


def get(user: str) -> dict:
    books.base_currency(user)                                  # makes sure the row exists
    r = books._one("SELECT * FROM fin_settings WHERE username=?", (user,))
    return {"base_currency": books.base_currency(user), "ai_reports": bool(r["ai_reports"]), "assistant_lang": r["assistant_lang"],
            "ask_adjustments": r["ask_adjustments"], "voice_replies": bool(r["voice_replies"]), "history_days": r["history_days"],
            "ui_lang": r["ui_lang"], "jurisdiction": r["jurisdiction"], "voice_enabled": bool(r["voice_enabled"]), "speech_lang": r["speech_lang"],
            "large_text": bool(r["large_text"]), "currency_chosen": books.currency_chosen(user), "currencies": [{"code": c, "symbol": money.SYMBOLS[c], "name": money.CURRENCY_NAMES[c]} for c in money.CURRENCIES], "jurisdiction_config": jurisdictions.summary(r["jurisdiction"]),
            "options": {"assistant_lang": list(LANGS), "ask_adjustments": list(ADJUSTMENT_POLICIES), "history_days": list(HISTORY_RANGE), "ui_lang": list(UI_LANGS), "speech_lang": list(SPEECH_LANGS),
                                                                 "jurisdiction": jurisdictions.codes()}}


def update(user: str, patch: dict) -> dict:
    cur = get(user)
    out = {k: cur[k] for k in ("ai_reports", "assistant_lang", "ask_adjustments", "voice_replies", "history_days")}
    for k in ("ai_reports", "voice_replies"):
        if k in patch:
            if not isinstance(patch[k], bool):
                raise FinanceError(f"{k} must be true or false.")
            out[k] = patch[k]
    if "assistant_lang" in patch:
        if patch["assistant_lang"] not in LANGS:
            raise FinanceError("assistant_lang must be one of: " + ", ".join(LANGS) + ".")
        out["assistant_lang"] = patch["assistant_lang"]
    if "ask_adjustments" in patch:
        if patch["ask_adjustments"] not in ADJUSTMENT_POLICIES:
            raise FinanceError("ask_adjustments must be one of: " + ", ".join(ADJUSTMENT_POLICIES) + ".")
        out["ask_adjustments"] = patch["ask_adjustments"]
    if "history_days" in patch:
        d = patch["history_days"]
        if not isinstance(d, int) or isinstance(d, bool) or not HISTORY_RANGE[0] <= d <= HISTORY_RANGE[1]:
            raise FinanceError(f"history_days must be a whole number from {HISTORY_RANGE[0]} to {HISTORY_RANGE[1]}.")
        out["history_days"] = d
    for k, allowed in (("ui_lang", UI_LANGS), ("speech_lang", SPEECH_LANGS)):
        if k in patch:
            if patch[k] not in allowed:
                raise FinanceError(f"{k} must be one of: " + ", ".join(allowed) + ".")
            out[k] = patch[k]
    for k in ("voice_enabled", "large_text"):
        if k in patch:
            if not isinstance(patch[k], bool):
                raise FinanceError(f"{k} must be true or false.")
            out[k] = patch[k]
    jur_changed = False
    if "jurisdiction" in patch:
        try:
            new_j = jurisdictions.validate(patch["jurisdiction"])
        except jurisdictions.JurisdictionError as e:
            raise FinanceError(str(e))
        jur_changed = new_j != cur["jurisdiction"]
        out["jurisdiction"] = new_j
    if "base_currency" in patch and (not cur["currency_chosen"] or books.valid_currency(patch["base_currency"]) != cur["base_currency"]):
        books.set_base_currency(user, patch["base_currency"])                  # allowed any time: records are untouched and never converted
    out.setdefault("ui_lang", cur["ui_lang"]); out.setdefault("speech_lang", cur["speech_lang"]); out.setdefault("jurisdiction", cur["jurisdiction"])
    out.setdefault("voice_enabled", cur["voice_enabled"]); out.setdefault("large_text", cur["large_text"])
    store._write("UPDATE fin_settings SET ai_reports=?, assistant_lang=?, ask_adjustments=?, voice_replies=?, history_days=?, ui_lang=?, jurisdiction=?, voice_enabled=?, speech_lang=?, large_text=? WHERE username=?",
                 (1 if out["ai_reports"] else 0, out["assistant_lang"], out["ask_adjustments"], 1 if out["voice_replies"] else 0, out["history_days"],
                  out["ui_lang"], out["jurisdiction"], 1 if out["voice_enabled"] else 0, out["speech_lang"], 1 if out["large_text"] else 0, user))
    books._audit(user, "fin_settings_updated", {"fields": sorted(patch)})
    res = get(user)
    if jur_changed:
        # Financial records are untouched. Open conversations stay filed under the jurisdiction they started in; the next message opens a fresh one.
        res = get(user)
        books._audit(user, "fin_jurisdiction_changed", {"from": cur["jurisdiction"], "to": out["jurisdiction"], "config_version": jurisdictions.VERSION})
        res["new_conversation"] = True
    return res


def data_version(user: str) -> dict:
    """A cheap fingerprint of everything the money screens show. The page polls it and reloads only when it changes, so a change made by the
    assistant, another tab or another device appears without a manual refresh. It carries counts and timestamps, never any amounts."""
    import hashlib
    parts = []
    for table in ("fin_accounts", "fin_transactions", "fin_budgets", "fin_goals", "fin_obligations", "fin_sessions"):
        r = books._one(f"SELECT COUNT(*) AS n, COALESCE(MAX(updated), '') AS u FROM {table} WHERE username=?", (user,))
        parts.append(f"{table}:{r['n']}:{r['u']}")
    r = books._one("SELECT COUNT(*) AS n FROM fin_obligation_payments WHERE obligation_id IN (SELECT id FROM fin_obligations WHERE username=?)", (user,))
    parts.append(f"pay:{r['n']}")
    row = books._one("SELECT jurisdiction, ui_lang FROM fin_settings WHERE username=?", (user,))
    parts.append(f"set:{row['jurisdiction']}:{row['ui_lang']}" if row else "set:")
    return {"version": hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]}
