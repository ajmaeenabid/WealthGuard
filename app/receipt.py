"""Verifiable advice receipt.

A receipt is a JSON document that bundles one client's compliance-approved advice with everything needed to check it later:
the compliance result, the CSRC article behind each rule, the hashes of the real datasets used, the client's audit entries with their
chain hashes, and an anchor to the head of the global audit chain at issue time, sealed by a content hash and an HMAC checkpoint.

What each check proves (see verify()):
  content hash   the receipt was not edited after issue (anyone can recompute it)
  entry hashes   each audit entry in it is internally consistent (anyone can recompute them)
  membership     each entry exists, unchanged, in the live audit log
  anchor         the chain head recorded at issue is still where it was, and the chain up to it is intact (detects later
                 truncation or rewriting of history, which the chain alone cannot)
  checkpoint     the HMAC was made by this server (only the server holds the key), so the receipt was really issued here
  data hashes    the datasets behind the numbers still match the manifest
"""
import hashlib
import hmac
import json
import os
import secrets
from typing import Optional

from app import config, db, knowledge, store
from app.security import audit

VERSION = 1


def _key() -> bytes:
    """RECEIPT_KEY from the environment, else a random key stored with the database (created once)."""
    env = (os.environ.get("RECEIPT_KEY") or "").strip()
    if env:
        return env.encode()
    with db.LOCK:
        conn = db.connect()
        conn.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        r = conn.execute("SELECT value FROM app_meta WHERE key='receipt_key'").fetchone()
        if not r:
            conn.execute("INSERT INTO app_meta VALUES ('receipt_key', ?)", (secrets.token_hex(32),))
            conn.commit()
            r = conn.execute("SELECT value FROM app_meta WHERE key='receipt_key'").fetchone()
        conn.close()
    return r["value"].encode()


def _norm(o):
    """Integral floats become ints: JSON in a browser cannot tell 100000.0 from 100000, so the hash must not either."""
    if isinstance(o, float):
        return int(o) if o.is_integer() and abs(o) < 1e15 else o
    if isinstance(o, dict):
        return {k: _norm(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_norm(v) for v in o]
    return o


def _sha(obj) -> str:
    return hashlib.sha256(audit.canonical(_norm(obj)).encode("utf-8")).hexdigest()


def _file_sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest() -> dict:
    with open(os.path.join(knowledge.REAL, "MANIFEST.json"), encoding="utf-8") as f:
        return json.load(f)


def _mac(content_hash: str, head_id: int, head_hash: str) -> str:
    return hmac.new(_key(), f"{VERSION}|{content_hash}|{head_id}|{head_hash}".encode(), hashlib.sha256).hexdigest()


def _entry_view(e: dict) -> dict:
    return {k: e[k] for k in ("id", "ts", "client_id", "actor", "action", "tier", "payload_hash", "prev_hash", "entry_hash")}


def build(client_id: str) -> Optional[dict]:
    d = store.load_client(client_id)
    alloc = store.latest_allocation(client_id)
    prof = store.load_profile(client_id)
    if not d or not alloc or not prof:
        return None
    comp = store.load_compliance(alloc.id)
    rows = audit.raw_rows()
    head = rows[-1] if rows else None
    entries = [_entry_view(r) for r in rows if r["client_id"] in (client_id, None)]
    basis = {}
    for ck in comp.checks:
        b = knowledge.basis_for_rule(ck.rule_id)
        if b:
            basis[ck.rule_id] = {"article": b["article"], "article_text_sha256": hashlib.sha256(b["text"].encode()).hexdigest()}
    man = _manifest()
    content = {
        "version": VERSION, "issued_at": store.now(),
        "disclaimer": config.DISCLAIMER + " " + config.DISCLAIMER_ZH,
        "client": {"id": client_id, "name": d.get("name")},
        "profile": prof.model_dump(),
        "allocation": alloc.model_dump(),
        "compliance": comp.model_dump(),
        "regulatory_basis": basis,
        "tickets": [{"id": t.id, "kind": t.kind, "status": t.status, "sandbox": t.sandbox}
                    for t in store.list_tickets(client_id) if t.allocation_id == alloc.id],
        "data_provenance": [{"file": x["file"], "sha256": x["sha256"], "license": x["license"], "url": x["url"]}
                            for x in man["datasets"]],
        "audit": {"entries": entries, "chain_head": {"id": head["id"], "entry_hash": head["entry_hash"]} if head else None,
                  "chain_entries_total": len(rows), "chain_valid_at_issue": audit.verify_rows(rows)["valid"]},
    }
    content_hash = _sha(content)
    hid, hh = (head["id"], head["entry_hash"]) if head else (0, audit.GENESIS)
    return {**content, "content_hash": content_hash,
            "checkpoint": {"alg": "HMAC-SHA256", "head_id": hid, "head_hash": hh, "mac": _mac(content_hash, hid, hh)}}


def _content_of(receipt: dict) -> dict:
    return {k: v for k, v in receipt.items() if k not in ("content_hash", "checkpoint")}


def check_entry_hashes(entries: list[dict]) -> list[int]:
    """Ids of entries whose stored entry_hash does not match their own fields (pure, key-free)."""
    bad = []
    for e in entries:
        if audit._entry_hash(e["id"], e["ts"], e["client_id"], e["actor"], e["action"], e["tier"], e["payload_hash"],
                             e["prev_hash"]) != e["entry_hash"]:
            bad.append(e["id"])
    return bad


def check_data_hashes(receipt: dict) -> list[str]:
    """Dataset files whose current hash differs from what the receipt recorded (needs the repository files)."""
    bad = []
    for d in receipt.get("data_provenance", []):
        p = os.path.join(knowledge.REAL, d["file"])
        if not os.path.isfile(p) or _file_sha(p) != d["sha256"]:
            bad.append(d["file"])
    return bad


def verify(receipt: dict) -> dict:
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    try:
        content = _content_of(receipt)
        cp = receipt["checkpoint"]
        entries = content["audit"]["entries"]
        add("content_hash", _sha(content) == receipt.get("content_hash"), "the receipt content matches its hash")
        bad = check_entry_hashes(entries)
        add("entry_hashes", not bad, "every audit entry is internally consistent" if not bad else f"entries {bad} do not match their own hash")
        rows = {r["id"]: r for r in audit.raw_rows()}
        missing = [e["id"] for e in entries if e["id"] not in rows or rows[e["id"]]["entry_hash"] != e["entry_hash"]]
        add("membership", not missing, "every entry exists unchanged in the live audit log" if not missing else f"entries {missing} are missing or changed in the live log")
        head = rows.get(cp["head_id"]) if cp["head_id"] else None
        anchored = (cp["head_id"] == 0 and not rows) or bool(head and head["entry_hash"] == cp["head_hash"])
        prefix = [rows[i] for i in sorted(rows) if i <= cp["head_id"]]
        chain = audit.verify_rows(prefix) if prefix else {"valid": True}
        add("anchor", anchored and chain["valid"], "the chain head recorded at issue is intact and the chain up to it verifies"
            if anchored and chain["valid"] else "the chain head recorded at issue is missing or changed, or the chain is broken (history was altered or truncated)")
        add("checkpoint", hmac.compare_digest(cp["mac"], _mac(receipt["content_hash"], cp["head_id"], cp["head_hash"])),
            "the HMAC checkpoint was issued by this server")
        bad_data = check_data_hashes(receipt)
        add("data_hashes", not bad_data, "the datasets behind the numbers still match" if not bad_data else f"changed or missing: {bad_data}")
        comp = content["compliance"]
        add("compliance", comp["passed"] and all(c["passed"] for c in comp["checks"]), "the advice in this receipt passed every compliance rule")
        add("same_allocation", comp["allocation_id"] == content["allocation"]["id"], "compliance result belongs to this allocation")
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        add("well_formed", False, f"not a valid receipt ({type(e).__name__})")
    return {"valid": all(c["ok"] for c in checks), "checks": checks}
