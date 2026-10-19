"""Per-user preferences for the finance module (AI explanations, assistant language, how often to ask about discounts, retention)."""
from app import store
from app.finance import books
from app.finance.books import FinanceError

LANGS = ("auto", "en", "bn")
ADJUSTMENT_POLICIES = ("auto", "always", "never")
HISTORY_RANGE = (7, 730)


def get(user: str) -> dict:
    books.base_currency(user)                                  # makes sure the row exists
    r = books._one("SELECT * FROM fin_settings WHERE username=?", (user,))
    return {"base_currency": r["base_currency"], "ai_reports": bool(r["ai_reports"]), "assistant_lang": r["assistant_lang"],
            "ask_adjustments": r["ask_adjustments"], "voice_replies": bool(r["voice_replies"]), "history_days": r["history_days"],
            "options": {"assistant_lang": list(LANGS), "ask_adjustments": list(ADJUSTMENT_POLICIES), "history_days": list(HISTORY_RANGE)}}


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
    if "base_currency" in patch and patch["base_currency"].upper() != cur["base_currency"]:
        if books._one("SELECT 1 FROM fin_accounts WHERE username=?", (user,)):
            raise FinanceError("The main currency can only be changed before you add accounts, so balances are never mislabelled.", 409)
        books.set_base_currency(user, patch["base_currency"])
    store._write("UPDATE fin_settings SET ai_reports=?, assistant_lang=?, ask_adjustments=?, voice_replies=?, history_days=? WHERE username=?",
                 (1 if out["ai_reports"] else 0, out["assistant_lang"], out["ask_adjustments"], 1 if out["voice_replies"] else 0, out["history_days"], user))
    books._audit(user, "fin_settings_updated", {"fields": sorted(patch)})
    return get(user)
