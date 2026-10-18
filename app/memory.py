"""Per-account memory: what the assistant remembers about a user between chats, even after several days.

Three kinds of memory, all stored per account and all visible (and deletable) in the Memory panel:
  fact    structured profile answers (age, horizon, goal, ...). New chats start with them, so nothing is asked twice.
  note    short statements the user made about themselves ("I'm saving for a flat", "remember that ..."), found by fixed
          patterns, not by a model, so what gets saved is predictable and cannot be steered by hidden instructions.
  summary one line per chat: what was asked and what the outcome was.
Recall is retrieval, not a dump: all facts, plus the notes and summaries that best match the current message
(token overlap, most recent first), capped so the prompt stays small. Memory is passed to the model as data, never as instructions.
"""
import json
import re
import uuid
from typing import Optional

from app import db, profiling, store
from app.products import load_personas
from app.security import guard

MAX_NOTES = 60
MAX_CONTEXT_CHARS = 1600
PROFILE_KEYS = [q["id"] for q in profiling.QUESTIONS]
EXTRA_KEYS = ["investable_amount_cny", "goal_target_cny"]
LABELS = {
    "age": "Age", "horizon_years": "Investment horizon (years)", "monthly_income_cny": "Monthly income (CNY)",
    "income_stability": "Income stability", "liquidity_need_pct": "Cash needed at short notice (%)",
    "goal": "Main goal", "loss_reaction": "Reaction to a 20% loss", "experience": "Investing experience",
    "investable_amount_cny": "Amount to invest (CNY)", "goal_target_cny": "Goal target (CNY)",
}
LIMITS = {"age": (18, 100), "horizon_years": (0.5, 60), "monthly_income_cny": (0, 10_000_000),
          "investable_amount_cny": (0, 1_000_000_000), "goal_target_cny": (0, 1_000_000_000)}


class MemoryInputError(ValueError):
    pass


def _upsert(username: str, kind: str, key: str, text: str) -> None:
    now = store.now()
    store._write("INSERT INTO memories (username, kind, key, text, created, updated) VALUES (?,?,?,?,?,?) "
                 "ON CONFLICT(username, kind, key) DO UPDATE SET text=excluded.text, updated=excluded.updated",
                 (username, kind, key, text, now, now))


def _rows(username: str, kind: Optional[str] = None) -> list:
    c = db.connect()
    q, args = "SELECT * FROM memories WHERE username=?", [username]
    if kind:
        q, args = q + " AND kind=?", args + [kind]
    rows = c.execute(q + " ORDER BY updated DESC, id DESC", args).fetchall()
    c.close()
    return rows


# ------------------------------------------------------------------------------------------ facts
def facts(username: str) -> dict:
    return {r["key"]: json.loads(r["text"]) for r in _rows(username, "fact")}


def _clean_fact(key: str, value):
    if key in EXTRA_KEYS or QBY_TYPE.get(key) == "number":
        try:
            v = float(re.search(r"-?\d+(\.\d+)?", str(value).replace(",", "")).group())
        except (AttributeError, ValueError):
            raise MemoryInputError("Enter a number.")
        lo, hi = LIMITS[key]
        if not lo <= v <= hi:
            raise MemoryInputError(f"{LABELS[key]} must be between {lo:g} and {hi:g}.")
        return v
    v = profiling.parse_answer(key, str(value))
    if v is None:
        opts = ", ".join(lab for lab, _ in profiling.QBY[key]["options"].values())
        raise MemoryInputError(f"Choose one of: {opts}.")
    return v


QBY_TYPE = {q["id"]: q["type"] for q in profiling.QUESTIONS}


def set_fact(username: str, key: str, value) -> None:
    if key not in PROFILE_KEYS + EXTRA_KEYS:
        raise MemoryInputError("Unknown fact.")
    _upsert(username, "fact", key, json.dumps(_clean_fact(key, value)))


def delete_fact(username: str, key: str) -> None:
    store._write("DELETE FROM memories WHERE username=? AND kind='fact' AND key=?", (username, key))


def display(key: str, value) -> str:
    q = profiling.QBY.get(key)
    if q and q["type"] == "choice":
        for v, (lab, _) in q["options"].items():
            if str(v) == str(value) or v == value:
                return lab
    if isinstance(value, (int, float)):
        return f"{value:,.0f}" if float(value).is_integer() else f"{value:g}"
    return str(value)


def seed(username: str) -> tuple[dict, dict]:
    """(facts, extra) a new chat starts with."""
    f = facts(username)
    return {k: f[k] for k in PROFILE_KEYS if k in f}, {k: f[k] for k in EXTRA_KEYS if k in f}


def sync_from_client(username: str, client_id: str) -> None:
    """Answers given in a chat become part of the account's memory."""
    d = store.load_client(client_id) or {}
    for k in PROFILE_KEYS:
        if k in (d.get("facts") or {}):
            _upsert(username, "fact", k, json.dumps(d["facts"][k]))
    for k in EXTRA_KEYS:
        if k in (d.get("extra") or {}):
            _upsert(username, "fact", k, json.dumps(d["extra"][k]))


def load_demo(username: str, persona_id: str) -> None:
    per = load_personas().get(persona_id)
    if not per:
        raise MemoryInputError("Unknown demo profile.")
    store._write("DELETE FROM memories WHERE username=? AND kind='fact'", (username,))
    for k in per["known"]:
        _upsert(username, "fact", k, json.dumps(per[k]))
    for k in EXTRA_KEYS:
        if k in per:
            _upsert(username, "fact", k, json.dumps(per[k]))


# ------------------------------------------------------------------------------------------ notes
_EN = [
    (r"\b(?:please\s+)?remember(?:\s+that)?[:,]?\s+(.{4,200}?)(?:[.!?\n]|$)", "{0}"),
    (r"\bmy name is\s+((?-i:[A-Z][a-z]+(?: [A-Z][a-z]+)?))", "Name: {0}"),
    (r"\bcall me\s+((?-i:[A-Z][a-z]+(?: [A-Z][a-z]+)?))", "Likes to be called {0}"),
    (r"\b(i(?:'m| am)?\s+(?:saving|planning|hoping|looking|preparing|trying)\b[^.!?\n]{4,160})", "{0}"),
    (r"\b(i\s+(?:prefer|like|love|dislike|avoid|hate|own|owe|don't like|do not like|don't want|do not want|want to|need to)\b[^.!?\n]{3,160})", "{0}"),
    (r"\b(i\s+have\s+(?:a|an|two|three|\d+)\b[^.!?\n]{3,140})", "{0}"),
    (r"\b(my\s+(?:goal|plan|budget|salary|income|savings|mortgage|debt|child|children|son|daughter|wife|husband|partner|business|house|flat|car)\b[^.!?\n]{3,160})", "{0}"),
]
_ZH = [
    (r"记住[:：,，]?\s*(.{2,100})", "{0}"),
    (r"我叫\s*([^\s，。！？,.]{1,20})", "姓名：{0}"),
    (r"(我(?:想|打算|准备|计划|希望|喜欢|不喜欢|不想|需要|有)[^。！？\n]{2,80})", "{0}"),
    (r"(我的(?:目标|计划|预算|收入|储蓄|孩子|房贷|工资)[^。！？\n]{2,80})", "{0}"),
]
_PATTERNS = [(re.compile(p, re.I), t) for p, t in _EN + _ZH]


def extract_notes(message: str) -> list[str]:
    """Statements worth remembering. Nothing is saved from messages the injection guard flags."""
    if not message or len(message) > 1500 or guard.scan(message):
        return []
    out = []
    for rx, tpl in _PATTERNS:
        for m in rx.finditer(message):
            text = re.sub(r"\s+", " ", tpl.format(*[g.strip(" .,!?，。！？") for g in m.groups()])).strip()
            if 6 <= len(text) <= 200 and text.lower() not in {o.lower() for o in out}:
                out.append(text[0].upper() + text[1:])
    out = [o for o in out if not any(o != p and o.lower() in p.lower() for p in out)]   # keep the fuller sentence only
    return out[:3]


def add_note(username: str, text: str) -> bool:
    text = re.sub(r"\s+", " ", text or "").strip()[:200]
    if len(text) < 3:
        raise MemoryInputError("Write a few words.")
    if any(r["text"].lower() == text.lower() for r in _rows(username, "note")):
        return False
    _upsert(username, "note", uuid.uuid4().hex[:10], text)
    old = _rows(username, "note")
    for r in old[MAX_NOTES:]:                       # keep the newest MAX_NOTES
        store._write("DELETE FROM memories WHERE id=?", (r["id"],))
    return True


# ------------------------------------------------------------------------------------------ chat summaries
def summarise(client_id: str, title: str = "") -> str:
    from app.agent import llm
    c = db.connect()
    msgs = [r["text"] for r in c.execute("SELECT text FROM messages WHERE client_id=? AND role='user' ORDER BY id", (client_id,))]
    c.close()
    topics = [m.replace("\n", " ")[:80] for m in msgs if len(m) >= 15 and not llm.SMALL_TALK.match(m)][:3]
    d = store.load_client(client_id) or {}
    parts = []
    if topics:
        parts.append("Asked: " + "; ".join(topics) + ".")
    prof = d.get("profile") or {}
    if prof.get("bucket"):
        parts.append(f"Risk bucket: {prof['bucket']}.")
    if store.latest_allocation(client_id):
        parts.append("An allocation passed the compliance check.")
    done = [t for t in store.list_tickets(client_id) if t.status == "approved"]
    if done:
        parts.append(f"{len(done)} sandbox ticket(s) approved.")
    return " ".join(parts) or (f"Chat: {title}." if title and title != "New chat" else "")


def update_summary(username: str, client_id: str, title: str) -> None:
    text = summarise(client_id, title)
    if text:
        _upsert(username, "summary", client_id, json.dumps({"title": title, "text": text}))


def delete_summary(client_id: str) -> None:
    store._write("DELETE FROM memories WHERE kind='summary' AND key=?", (client_id,))


# ------------------------------------------------------------------------------------------ panel + recall
def overview(username: str) -> dict:
    f = [{"key": r["key"], "label": LABELS.get(r["key"], r["key"]), "value": json.loads(r["text"]),
          "text": display(r["key"], json.loads(r["text"])), "updated": r["updated"]}
         for r in _rows(username, "fact")]
    order = {k: i for i, k in enumerate(PROFILE_KEYS + EXTRA_KEYS)}
    f.sort(key=lambda x: order.get(x["key"], 99))
    notes = [{"id": r["id"], "text": r["text"], "updated": r["updated"]} for r in _rows(username, "note")]
    sums = []
    for r in _rows(username, "summary"):
        v = json.loads(r["text"])
        sums.append({"id": r["id"], "chat_id": r["key"], "title": v.get("title", ""), "text": v["text"], "updated": r["updated"]})
    return {"facts": f, "notes": notes, "summaries": sums, "count": len(f) + len(notes) + len(sums)}


def delete_item(username: str, item_id: int) -> None:
    store._write("DELETE FROM memories WHERE id=? AND username=?", (item_id, username))


def clear(username: str) -> None:
    store._write("DELETE FROM memories WHERE username=?", (username,))


def _score(message: str, text: str) -> int:
    from app.vectorstore import tokens
    return len(set(tokens(message)) & set(tokens(text)))


def context(username: str, message: str, k: int = 6) -> str:
    """The remembered facts plus the k notes / chat summaries most relevant to this message, as plain text for the model."""
    ov = overview(username)
    pool = [("note", n["text"]) for n in ov["notes"]] + [("chat", f"{s['title'] or 'earlier chat'} ({s['updated'][:10]}): {s['text']}") for s in ov["summaries"]]
    ranked = sorted(enumerate(pool), key=lambda p: (-_score(message, p[1][1]), p[0]))[:k]
    lines = []
    if ov["facts"]:
        lines.append("Profile: " + "; ".join(f"{f['label']}: {f['text']}" for f in ov["facts"]))
    for _, (kind, text) in sorted(ranked, key=lambda p: p[0]):
        lines.append(("Note: " if kind == "note" else "Earlier chat: ") + text)
    return "\n".join(lines)[:MAX_CONTEXT_CHARS]
