"""Saved chats. One conversation = one advisory session (client_id) owned by an account; messages are kept in order."""
from typing import Optional

from app import db, memory, profiling, service, state, store
from app.agent import llm

HISTORY_TURNS = 12


def create(user: dict) -> dict:
    """New chat. It starts blank, with whatever this account already remembers (profile answers), never a preset persona."""
    facts, extra = memory.seed(user["username"])
    s = service.create_session(None, facts=facts, extra=extra, name=user["display_name"])
    now = store.now()
    store._write("INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)",
                 (s["client_id"], user["username"], "New chat", None, s["name"],
                  state.PENDING_QUESTION.get(s["client_id"]), now, now))
    return s


def get(client_id: str):
    return store._one("SELECT * FROM conversations WHERE client_id=?", (client_id,))


def can_access(user: Optional[dict], client_id: str) -> bool:
    """True for the owner and for sessions that predate accounts (no saved conversation). Administrators manage
    accounts; they cannot read other people's chats."""
    conv = get(client_id)
    if conv is None:
        return True
    return bool(user) and conv["username"] == user["username"]


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
        title = f"Advice for {conv['name']}"
    store._write("UPDATE conversations SET title=?, updated=?, pending_question=? WHERE client_id=?",
                 (title, store.now(), state.PENDING_QUESTION.get(client_id), client_id))
    # remember: profile answers, things the user said about themselves, and a one-line summary of this chat
    user = conv["username"]
    memory.sync_from_client(user, client_id)
    for note in memory.extract_notes(message):
        memory.add_note(user, note)
    memory.update_summary(user, client_id, title)


def listing(user: dict) -> list[dict]:
    c = db.connect()
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
    return {"client_id": client_id, "title": conv["title"], "name": conv["name"], "persona_id": None,
            "story": None, "messages": msgs, "next_question": q}


def delete(client_id: str) -> None:
    store._write("DELETE FROM messages WHERE client_id=?", (client_id,))
    store._write("DELETE FROM conversations WHERE client_id=?", (client_id,))
    memory.delete_summary(client_id)
    state.HISTORY.pop(client_id, None)
