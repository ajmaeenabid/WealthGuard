"""The per-user context the assistant is allowed to rely on."""
import json
import re
from datetime import timedelta
from typing import Optional

from app import store
from app.finance import ai, analytics, books, jurisdictions, money, planning, privacy, settings, tokens

MAX_NOTES_CHARS = 500
REFRESH_EVERY = 5


def _ensure() -> None:
    store._write("CREATE TABLE IF NOT EXISTS fin_user_context (username TEXT PRIMARY KEY, facts TEXT NOT NULL DEFAULT '{}', notes TEXT NOT NULL DEFAULT '', "
                 "changes INTEGER NOT NULL DEFAULT 0, updated TEXT NOT NULL)", ())


def facts(user: str) -> dict:
    pref = settings.get(user)
    j = jurisdictions.get(pref["jurisdiction"])
    today = money.today()
    out = {"jurisdiction": j["code"], "currency": j["currency"], "language": pref["ui_lang"],
           "accounts": [{"name": a["name"], "type": a["type"], "currency": a["currency"]} for a in books.list_accounts(user)][:12]}
    try:
        s = analytics.summary(user, today - timedelta(days=89), today)
        out["top_categories_90d"] = [c["category"] for c in s["by_category"][:4]]
        out["transactions_90d"] = s["transactions"]
    except Exception:
        out["top_categories_90d"], out["transactions_90d"] = [], 0
    out["budgets"] = [b["name"] for b in planning.list_budgets(user) if b["active"]][:6]
    out["goals"] = [g["name"] for g in planning.list_goals(user) if g["status"] != "completed"][:6]
    out["bills"] = [o["name"] for o in planning.list_obligations(user, include_inactive=False)][:6]
    return out


def _row(user: str):
    _ensure()
    return books._one("SELECT * FROM fin_user_context WHERE username=?", (user,))


def get(user: str) -> dict:
    f = facts(user)
    r = _row(user)
    blob = json.dumps(f, ensure_ascii=False, sort_keys=True)
    if not r:
        store._write("INSERT INTO fin_user_context (username, facts, notes, changes, updated) VALUES (?,?,?,?,?)", (user, blob, "", 0, store.now()))
        return {"facts": f, "notes": ""}
    if r["facts"] != blob:
        store._write("UPDATE fin_user_context SET facts=?, updated=? WHERE username=?", (blob, store.now(), user))
    return {"facts": f, "notes": r["notes"]}


def render(user: str, budget: int = 450) -> str:
    c = get(user)
    txt = "USER FACTS (from this user's own database records, authoritative): " + json.dumps(c["facts"], ensure_ascii=False, separators=(",", ":"))
    if c["notes"]:
        txt += " PROFILE NOTES: " + c["notes"]
    return tokens.truncate(txt, budget)


_BAD = re.compile(r"(ignore|disregard|system prompt|instruction|api[_ ]?key|password|otp|pin\b|\d{3,})", re.I)


def validate_notes(text: str) -> Optional[str]:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t or len(t) > MAX_NOTES_CHARS or _BAD.search(t):
        return None
    return t


def note_change(user: str) -> None:
    r = _row(user) or (get(user) and _row(user))
    n = (r["changes"] if r else 0) + 1
    store._write("UPDATE fin_user_context SET changes=?, updated=? WHERE username=?", (n, store.now(), user))
    if n % REFRESH_EVERY == 0 and ai.enabled():
        refresh_notes(user)


def refresh_notes(user: str) -> Optional[str]:
    c = get(user)
    msgs = [{"role": "system", "content": "You write a one or two sentence neutral profile of a personal-finance user from the JSON facts given. "
                                           "Describe habits only (what kinds of accounts and categories). Do NOT include any numbers, amounts, names of people, "
                                           "advice, or instructions. Maximum 300 characters. Reply with the text only."},
            {"role": "user", "content": json.dumps(c["facts"], ensure_ascii=False)}]
    try:
        res = ai.call(msgs, purpose="user_context", user=user, max_tokens=160, prompt_version="ctx1")
    except ai.AIError:
        return None
    note = validate_notes(privacy.redact(res.content or ""))
    if note:
        store._write("UPDATE fin_user_context SET notes=?, updated=? WHERE username=?", (note, store.now(), user))
    return note


def erase(user: str) -> None:
    _ensure()
    store._write("DELETE FROM fin_user_context WHERE username=?", (user,))
