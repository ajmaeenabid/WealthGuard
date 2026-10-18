"""Saved chats. One conversation = one advisory session (client_id) owned by an account; messages are kept in order."""
from typing import Optional

from app import db, profiling, service, state, store
from app.agent import llm
from app.products import load_personas

HISTORY_TURNS = 12


def _greeting(s: dict) -> str:
    who = f", {s['name']}" if s.get("persona_id") else ""
    tail = " - I'll only ask what I don't already know." if s.get("next_question") else "."
    return (f"Hello{who}! I'm WealthGuard. Nothing I propose is shown to you until an independent compliance check "
            f"approves it. Say hi to begin{tail}")


def create(user: dict, persona_id: Optional[str]) -> dict:
    """New chat. Accounts locked to a persona always use it; others may pick any persona or a blank client."""
    persona = user["persona_id"] or persona_id or None
    s = service.create_session(persona)
    now = store.now()
    store._write("INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)",
                 (s["client_id"], user["username"], "New chat", persona, s["name"],
                  state.PENDING_QUESTION.get(s["client_id"]), now, now))
    s["greeting"] = _greeting(s)
    add_message(s["client_id"], "agent", s["greeting"])
    return s


def get(client_id: str):
    return store._one("SELECT * FROM conversations WHERE client_id=?", (client_id,))


def can_access(user: Optional[dict], client_id: str) -> bool:
    """True for the owner, for admins, and for sessions that predate accounts (no saved conversation)."""
    conv = get(client_id)
    if conv is None:
        return True
    return bool(user) and (user["role"] == "admin" or conv["username"] == user["username"])


def add_message(client_id: str, role: str, text: str) -> None:
    store._write("INSERT INTO messages (client_id,role,text,ts) VALUES (?,?,?,?)", (client_id, role, text, store.now()))


def record_turn(client_id: str, message: str, reply: str) -> None:
    conv = get(client_id)
    if conv is None:
        return
    add_message(client_id, "user", message)
    add_message(client_id, "agent", reply)
    title = conv["title"]
    text = message.strip().replace(chr(10), " ")
    if title == "New chat" and len(text) >= 15 and not llm.SMALL_TALK.match(text):   # short replies are questionnaire answers
        title = text[:42]
    elif title == "New chat" and store.latest_allocation(client_id):
        title = f"Advice for {conv['name']}" if conv["persona_id"] else "Allocation advice"
    store._write("UPDATE conversations SET title=?, updated=?, pending_question=? WHERE client_id=?",
                 (title, store.now(), state.PENDING_QUESTION.get(client_id), client_id))


def listing(user: dict) -> list[dict]:
    c = db.connect()
    if user["role"] == "admin":
        rows = c.execute("SELECT * FROM conversations ORDER BY updated DESC, rowid DESC LIMIT 100").fetchall()
    else:
        rows = c.execute("SELECT * FROM conversations WHERE username=? ORDER BY updated DESC, rowid DESC LIMIT 100",
                         (user["username"],)).fetchall()
    c.close()
    return [{"id": r["client_id"], "title": r["title"], "name": r["name"], "persona_id": r["persona_id"],
             "owner": r["username"], "updated": r["updated"]} for r in rows]


def open_chat(client_id: str) -> dict:
    """Messages plus the in-memory state the agent needs to carry on where the chat stopped."""
    conv = get(client_id)
    c = db.connect()
    rows = c.execute("SELECT role, text, ts FROM messages WHERE client_id=? ORDER BY id", (client_id,)).fetchall()
    c.close()
    msgs = [{"role": r["role"], "text": r["text"], "ts": r["ts"]} for r in rows]
    if client_id not in state.HISTORY:
        state.HISTORY[client_id] = [{"role": "user" if m["role"] == "user" else "assistant", "content": m["text"]}
                                    for m in msgs if m["role"] in ("user", "agent")][-HISTORY_TURNS:]
    if conv["pending_question"] and client_id not in state.PENDING_QUESTION:
        state.PENDING_QUESTION[client_id] = conv["pending_question"]
    d = store.load_client(client_id) or {"facts": {}}
    q = profiling.next_question(d["facts"]) if state.PENDING_QUESTION.get(client_id) else None
    per = load_personas().get(conv["persona_id"] or "") or {}
    return {"client_id": client_id, "title": conv["title"], "name": conv["name"], "persona_id": conv["persona_id"],
            "story": per.get("story"), "messages": msgs, "next_question": q}


def delete(client_id: str) -> None:
    store._write("DELETE FROM messages WHERE client_id=?", (client_id,))
    store._write("DELETE FROM conversations WHERE client_id=?", (client_id,))
    state.HISTORY.pop(client_id, None)
