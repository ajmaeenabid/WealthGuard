"""Append-only, hash-chained audit log."""
import hashlib
import json
from typing import Optional

from app import db
from app.schemas import AuditEntry
from app.store import now

GENESIS = "0" * 64


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _entry_hash(id_, ts, client_id, actor, action, tier, payload_hash, prev_hash) -> str:
    return _sha(canonical([id_, ts, client_id, actor, action, tier, payload_hash, prev_hash]))


def append(actor: str, action: str, tier: str, payload: Optional[dict] = None,
           client_id: Optional[str] = None) -> AuditEntry:
    payload = payload or {}
    with db.LOCK:
        conn = db.connect()
        last = conn.execute("SELECT id, entry_hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        id_ = (last["id"] + 1) if last else 1
        prev = last["entry_hash"] if last else GENESIS
        ts = now()
        pj = canonical(payload)
        ph = _sha(pj)
        eh = _entry_hash(id_, ts, client_id, actor, action, tier, ph, prev)
        conn.execute(
            "INSERT INTO audit (id,ts,client_id,actor,action,tier,payload,payload_hash,prev_hash,entry_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)", (id_, ts, client_id, actor, action, tier, pj, ph, prev, eh))
        conn.commit()
        conn.close()
    return AuditEntry(id=id_, ts=ts, actor=actor, action=action, tier=tier, payload_hash=ph, prev_hash=prev,
                      entry_hash=eh)


def list_entries(client_id: Optional[str] = None) -> list[dict]:
    conn = db.connect()
    if client_id:
        rows = conn.execute("SELECT * FROM audit WHERE client_id=? OR client_id IS NULL ORDER BY id",
                            (client_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM audit ORDER BY id").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out


def raw_rows() -> list[dict]:
    conn = db.connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM audit ORDER BY id").fetchall()]
    conn.close()
    return rows


def verify_rows(rows: list[dict]) -> dict:
    prev = GENESIS
    expected_id = 1
    for r in rows:
        bad = (
            r["id"] != expected_id
            or r["prev_hash"] != prev
            or _sha(r["payload"]) != r["payload_hash"]
            or _entry_hash(r["id"], r["ts"], r["client_id"], r["actor"], r["action"], r["tier"],
                           r["payload_hash"], r["prev_hash"]) != r["entry_hash"]
        )
        if bad:
            return {"valid": False, "broken_at": r["id"], "checked": expected_id - 1}
        prev = r["entry_hash"]
        expected_id += 1
    return {"valid": True, "checked": len(rows), "head": prev}


def verify() -> dict:
    return verify_rows(raw_rows())
