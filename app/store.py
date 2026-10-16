"""Persistence helpers for clients, allocations, tickets, documents."""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from app import db
from app.schemas import Allocation, ClientProfile, ComplianceResult, OrderTicket


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _write(sql: str, params: tuple) -> None:
    with db.LOCK:
        c = db.connect()
        c.execute(sql, params)
        c.commit()
        c.close()


def _one(sql: str, params: tuple):
    c = db.connect()
    r = c.execute(sql, params).fetchone()
    c.close()
    return r


# clients: data = {"name": str, "facts": {answers}, "profile": ClientProfile|None, "extra": {...}}
def save_client(client_id: str, data: dict) -> None:
    _write("INSERT OR REPLACE INTO clients VALUES (?,?)", (client_id, json.dumps(data, default=str)))


def load_client(client_id: str) -> Optional[dict]:
    r = _one("SELECT data FROM clients WHERE id=?", (client_id,))
    return json.loads(r["data"]) if r else None


def load_profile(client_id: str) -> Optional[ClientProfile]:
    d = load_client(client_id)
    if d and d.get("profile"):
        return ClientProfile(**d["profile"])
    return None


def save_allocation(a: Allocation, status: str = "draft") -> None:
    with db.LOCK:
        c = db.connect()
        seq = c.execute("SELECT COALESCE(MAX(seq),0)+1 FROM allocations").fetchone()[0]
        c.execute("INSERT OR REPLACE INTO allocations (id,client_id,data,compliance,status,seq) VALUES (?,?,?,?,?,?)",
                  (a.id, a.client_id, a.model_dump_json(), None, status, seq))
        c.commit()
        c.close()


def load_allocation(aid: str) -> Optional[Allocation]:
    r = _one("SELECT data FROM allocations WHERE id=?", (aid,))
    return Allocation.model_validate_json(r["data"]) if r else None


def set_compliance(aid: str, res: ComplianceResult) -> None:
    _write("UPDATE allocations SET compliance=?, status=? WHERE id=?",
           (res.model_dump_json(), "approved_by_compliance" if res.passed else "blocked", aid))


def load_compliance(aid: str) -> Optional[ComplianceResult]:
    r = _one("SELECT compliance FROM allocations WHERE id=?", (aid,))
    return ComplianceResult.model_validate_json(r["compliance"]) if r and r["compliance"] else None


def latest_allocation(client_id: str, passed_only: bool = True) -> Optional[Allocation]:
    q = "SELECT data FROM allocations WHERE client_id=?"
    if passed_only:
        q += " AND status='approved_by_compliance'"
    r = _one(q + " ORDER BY seq DESC LIMIT 1", (client_id,))
    return Allocation.model_validate_json(r["data"]) if r else None


def consecutive_blocked(client_id: str) -> int:
    """Number of blocked drafts since the last compliant allocation."""
    c = db.connect()
    rows = c.execute("SELECT status FROM allocations WHERE client_id=? ORDER BY seq DESC", (client_id,)).fetchall()
    c.close()
    n = 0
    for r in rows:
        if r["status"] == "blocked":
            n += 1
        elif r["status"] == "approved_by_compliance":
            break
    return n


def save_ticket(t: OrderTicket) -> None:
    _write("INSERT OR REPLACE INTO tickets VALUES (?,?,?)", (t.id, t.client_id, t.model_dump_json()))


def load_ticket(tid: str) -> Optional[OrderTicket]:
    r = _one("SELECT data FROM tickets WHERE id=?", (tid,))
    return OrderTicket.model_validate_json(r["data"]) if r else None


def list_tickets(client_id: str) -> list[OrderTicket]:
    c = db.connect()
    rows = c.execute("SELECT data FROM tickets WHERE client_id=? ORDER BY rowid", (client_id,)).fetchall()
    c.close()
    return [OrderTicket.model_validate_json(r["data"]) for r in rows]


def add_document(client_id: str, filename: str, text: str, warnings: list) -> None:
    _write("INSERT INTO documents (client_id,filename,text,warnings) VALUES (?,?,?,?)",
           (client_id, filename, text, json.dumps(warnings)))


def list_documents(client_id: str) -> list[dict]:
    c = db.connect()
    rows = c.execute("SELECT filename,text,warnings FROM documents WHERE client_id=?", (client_id,)).fetchall()
    c.close()
    return [{"filename": r["filename"], "text": r["text"], "warnings": json.loads(r["warnings"])} for r in rows]
