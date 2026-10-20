"""Saved chats. One conversation = one advisory session (client_id) owned by an account; messages are kept in order."""
from typing import Optional

from app import db, memory, profiling, service, state, store
from app.agent import llm

HISTORY_TURNS = 12


def create(user: dict) -> dict:
    facts, extra = memory.seed(user["username"])
    s = service.create_session(None, facts=facts, extra=extra, name=user["display_name"])
    now = store.now()
    store._write("INSERT INTO conversations (client_id, username, title, persona_id, name, pending_question, created, updated) VALUES (?,?,?,?,?,?,?,?)",
                 (s["client_id"], user["username"], "New chat", None, s["name"],
                  state.PENDING_QUESTION.get(s["client_id"]), now, now))
    return s


def adopt(user: dict, session: dict) -> None:
    now = store.now()
    store._write("INSERT INTO conversations (client_id, username, title, persona_id, name, pending_question, created, updated) VALUES (?,?,?,?,?,?,?,?)",
                 (session["client_id"], user["username"], "New chat", None, session["name"],
                  state.PENDING_QUESTION.get(session["client_id"]), now, now))


def get(client_id: str):
    return store._one("SELECT * FROM conversations WHERE client_id=?", (client_id,))


def can_access(user: Optional[dict], client_id: str) -> bool:
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
    if conv["title_custom"]:
        pass
    elif title == "New chat" and len(text) >= 15 and not llm.SMALL_TALK.match(text):
        title = text[:42]
    elif title == "New chat" and store.latest_allocation(client_id):
        title = f"Advice for {conv['name']}"
    store._write("UPDATE conversations SET title=?, updated=?, pending_question=? WHERE client_id=?",
                 (title, store.now(), state.PENDING_QUESTION.get(client_id), client_id))
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


MAX_TITLE = 60


def clean_title(raw: str) -> str:
    t = "".join(ch for ch in (raw or "") if ch.isprintable()).strip()
    t = " ".join(t.split())
    if not t:
        raise ValueError("The chat needs a name.")
    if len(t) > MAX_TITLE:
        raise ValueError(f"Keep the name under {MAX_TITLE} characters.")
    return t


def rename(client_id: str, raw_title: str) -> dict:
    title = clean_title(raw_title)
    store._write("UPDATE conversations SET title=?, title_custom=1, updated=? WHERE client_id=?", (title, store.now(), client_id))
    conv = get(client_id)
    memory.update_summary(conv["username"], client_id, title)
    return {"id": client_id, "title": title}


def delete(client_id: str) -> None:
    store._write("DELETE FROM messages WHERE client_id=?", (client_id,))
    store._write("DELETE FROM conversations WHERE client_id=?", (client_id,))
    memory.delete_summary(client_id)
    state.HISTORY.pop(client_id, None)
