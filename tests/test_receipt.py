"""Verifiable advice receipt: what each check proves, and that every kind of tampering is caught."""
import copy
import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app import db, receipt, redteam
from app.main import app
from app.security import audit

c = TestClient(app)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def approved_client(persona="persona_li"):
    cid = redteam._probe(persona)[0]
    from app import service
    from app.agent.tools import Ctx
    from app.security import tiers
    out = service.run_pipeline(cid, [])
    t = tiers.execute("create_order_ticket", {"allocation_id": out["allocation"].id}, Ctx(cid))
    tiers.approve_ticket(t["ticket_id"], cid)
    return cid


def reseal(r):
    r["content_hash"] = receipt._sha(receipt._content_of(r))
    return r


def failed(res):
    return {x["name"] for x in res["checks"] if not x["ok"]}


def test_a_fresh_receipt_passes_every_check():
    cid = approved_client()
    r = receipt.build(cid)
    res = receipt.verify(r)
    assert res["valid"] and failed(res) == set()
    assert [x["name"] for x in res["checks"]] == ["content_hash", "entry_hashes", "membership", "anchor", "checkpoint",
                                                  "data_hashes", "compliance", "same_allocation"]


def test_receipt_contents_cover_the_advice_the_proof_and_the_data():
    r = receipt.build(approved_client())
    assert r["compliance"]["passed"] and r["allocation"]["lines"] and "Not real financial advice" in r["disclaimer"]
    assert r["regulatory_basis"]["R3"]["article"] == "第十六条" and len(r["regulatory_basis"]["R3"]["article_text_sha256"]) == 64
    assert [t["status"] for t in r["tickets"]] == ["approved"]
    assert {d["file"] for d in r["data_provenance"]} == {"returns_annual.csv", "shiller_monthly.csv", "china_macro.csv", "suitability_zh.json"}
    a = r["audit"]
    assert a["chain_valid_at_issue"] and a["chain_head"]["id"] == r["checkpoint"]["head_id"] and a["entries"]


def test_the_receipt_holds_hashes_only_and_only_this_clients_entries():
    cid = approved_client()
    other = approved_client("persona_chen")
    r = receipt.build(cid)
    assert {e["client_id"] for e in r["audit"]["entries"]} <= {cid, None} and other not in json.dumps(r)
    assert all("payload" not in e for e in r["audit"]["entries"])


def test_no_receipt_without_a_compliance_approved_allocation():
    cid = c.post("/api/session", json={"persona_id": "persona_li"}).json()["client_id"]
    assert receipt.build(cid) is None
    assert c.get("/api/receipt", params={"client_id": cid}).status_code == 409


def test_editing_the_advice_breaks_the_content_hash():
    r = receipt.build(approved_client())
    r["allocation"]["lines"][0]["weight"] = 0.99
    assert failed(receipt.verify(r)) >= {"content_hash"}


def test_a_forger_who_recomputes_the_hash_is_stopped_by_the_checkpoint():
    r = receipt.build(approved_client())
    r["allocation"]["lines"][0]["weight"] = 0.99
    res = receipt.verify(reseal(r))
    assert "content_hash" not in failed(res) and "checkpoint" in failed(res) and not res["valid"]


def test_forging_an_audit_entry_is_caught_by_its_own_hash_or_by_membership():
    r = receipt.build(approved_client())
    r["audit"]["entries"][1]["action"] = "approve_order"
    res = receipt.verify(reseal(r))
    assert "entry_hashes" in failed(res)
    r2 = receipt.build(approved_client())
    e = r2["audit"]["entries"][1]
    e["action"] = "forged"
    e["entry_hash"] = audit._entry_hash(e["id"], e["ts"], e["client_id"], e["actor"], e["action"], e["tier"], e["payload_hash"], e["prev_hash"])
    res2 = receipt.verify(reseal(r2))
    assert "entry_hashes" not in failed(res2) and "membership" in failed(res2)


def test_truncating_the_audit_log_after_issue_is_detected_by_the_anchor():
    cid = approved_client()
    r = receipt.build(cid)
    head = r["checkpoint"]["head_id"]
    conn = db.connect()
    conn.execute("DELETE FROM audit WHERE id > ?", (head - 3,))
    conn.commit()
    conn.close()
    res = receipt.verify(r)
    assert {"anchor", "membership"} & failed(res) and not res["valid"]
    assert audit.verify()["valid"]


def test_rewriting_history_in_the_live_log_is_detected():
    cid = approved_client()
    r = receipt.build(cid)
    conn = db.connect()
    conn.execute("UPDATE audit SET action='edited' WHERE id=2")
    conn.commit()
    conn.close()
    assert "anchor" in failed(receipt.verify(r))


def test_a_receipt_sealed_with_another_key_is_rejected(monkeypatch):
    r = receipt.build(approved_client())
    monkeypatch.setenv("RECEIPT_KEY", "a-different-server-key")
    assert failed(receipt.verify(r)) == {"checkpoint"}


def test_changed_dataset_hashes_are_reported():
    r = receipt.build(approved_client())
    r["data_provenance"][0]["sha256"] = "0" * 64
    assert "data_hashes" in failed(receipt.verify(reseal(r)))


def test_a_receipt_for_a_blocked_or_foreign_allocation_is_rejected():
    r = receipt.build(approved_client())
    bad = copy.deepcopy(r)
    bad["compliance"]["passed"] = False
    assert "compliance" in failed(receipt.verify(reseal(bad)))
    bad2 = copy.deepcopy(r)
    bad2["compliance"]["allocation_id"] = "alloc_other"
    assert "same_allocation" in failed(receipt.verify(reseal(bad2)))


def test_garbage_is_rejected_not_crashing():
    for junk in [{}, {"checkpoint": 1}, {"content_hash": "x", "checkpoint": {}, "audit": {}}]:
        res = receipt.verify(junk)
        assert res["valid"] is False and "well_formed" in failed(res)


def test_the_key_is_stable_per_database_and_overridable(monkeypatch):
    k1, k2 = receipt._key(), receipt._key()
    assert k1 == k2 and len(k1) == 64
    monkeypatch.setenv("RECEIPT_KEY", "fixed-key")
    assert receipt._key() == b"fixed-key"


def test_api_issue_and_verify_round_trip_with_audit():
    cid = approved_client()
    r = c.get("/api/receipt", params={"client_id": cid}).json()
    v = c.post("/api/receipt/verify", json={"receipt": r}).json()
    assert v["valid"] is True
    v2 = c.post("/api/receipt/verify", json=r).json()
    assert v2["valid"] is True
    acts = [e["action"] for e in c.get("/api/audit", params={"client_id": cid}).json()]
    assert "receipt_issued" in acts and c.get("/api/audit/verify").json()["valid"]
    r["allocation"]["summary"] = "edited"
    assert c.post("/api/receipt/verify", json={"receipt": r}).json()["valid"] is False


def test_api_validation():
    assert c.get("/api/receipt", params={"client_id": "nope"}).status_code == 404
    assert c.post("/api/receipt/verify", json={}).json()["valid"] is False


def test_the_offline_script_verifies_and_catches_tampering(tmp_path):
    r = receipt.build(approved_client())
    good = tmp_path / "good.json"
    good.write_text(json.dumps(r), encoding="utf-8")
    run = lambda p: subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "verify_receipt.py"), str(p)],
                                   capture_output=True, text=True, encoding="utf-8", timeout=60)
    out = run(good)
    assert out.returncode == 0 and "RESULT: valid" in out.stdout and "[OK] content hash" in out.stdout
    r["allocation"]["summary"] = "edited"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(r), encoding="utf-8")
    out = run(bad)
    assert out.returncode == 1 and "[FAIL] content hash" in out.stdout


def test_ui_has_the_receipt_card():
    html = c.get("/").text
    assert 'id="rcCard"' in html and 'id="rcDl"' in html and 'id="rcFile"' in html and "rcVerifyFile" in c.get("/static/app.js").text


def js_roundtrip(o):
    if isinstance(o, float):
        return int(o) if o.is_integer() else o
    if isinstance(o, dict):
        return {k: js_roundtrip(v) for k, v in o.items()}
    if isinstance(o, list):
        return [js_roundtrip(v) for v in o]
    return o


def test_a_receipt_survives_a_browser_json_round_trip():
    r = receipt.build(approved_client())
    assert json.dumps(r) != json.dumps(js_roundtrip(r))
    res = receipt.verify(js_roundtrip(r))
    assert res["valid"] and failed(res) == set()


def test_the_offline_script_accepts_a_browser_saved_receipt(tmp_path):
    r = js_roundtrip(receipt.build(approved_client()))
    f = tmp_path / "browser.json"
    f.write_text(json.dumps(r), encoding="utf-8")
    out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "verify_receipt.py"), str(f)], capture_output=True, text=True,
                         encoding="utf-8", timeout=60)
    assert out.returncode == 0 and "[OK] content hash" in out.stdout


def test_normalisation_does_not_hide_real_edits():
    r = js_roundtrip(receipt.build(approved_client()))
    r["profile"]["investable_amount_cny"] = 200001
    assert "content_hash" in failed(receipt.verify(r))
    r2 = js_roundtrip(receipt.build(approved_client()))
    r2["allocation"]["lines"][0]["weight"] = round(r2["allocation"]["lines"][0]["weight"] + 0.001, 4)
    assert "content_hash" in failed(receipt.verify(r2))
