"""End-to-end flows through the HTTP API with the mock LLM."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security import audit

c = TestClient(app)


def start(persona="persona_li"):
    return c.post("/api/session", json={"persona_id": persona}).json()["client_id"]


def chat(cid, msg):
    r = c.post("/api/chat", json={"client_id": cid, "message": msg})
    assert r.status_code == 200, r.text
    return r.json()


def profile_via_chat(cid):
    out = chat(cid, "Hi, please advise me")
    assert out["question"], out
    for ans in ["Stable", "About 10%", "Sell some"]:
        out = chat(cid, ans)
    return out


def test_health_and_disclaimer():
    h = c.get("/api/health").json()
    assert h["mock_llm"] and "Not real financial advice" in h["disclaimer"]


def test_persona1_full_flow_chat_to_approved_ticket():
    cid = start()
    out = chat(cid, "Hi, please advise me")
    assert out["question"]["id"] == "income_stability" and out["allocation"] is None  # asks only the unknown
    chat(cid, "Stable")
    chat(cid, "About 10%")
    out = chat(cid, "Sell some")
    # first draft (with the tempting note) was blocked, the revision passed
    assert out["allocation"] is not None
    assert [a["passed"] for a in out["attempts"]] == [False, True]
    assert "R1" in out["attempts"][0]["failed_rules"] and "R3" in out["attempts"][0]["failed_rules"]
    assert out["compliance"].get("passed") if isinstance(out["compliance"], dict) else False
    ids = [l["product_id"] for l in out["allocation"]["lines"]]
    assert "P13" not in ids and all(l["rationale"] for l in out["allocation"]["lines"])
    assert "P13" in out["why_not"] and "R3" in out["why_not"]["P13"]["text"]
    assert "Not real financial advice" in out["reply"]

    st = chat(cid, "What if equities fall 20%?")
    assert "-" in st["reply"] and "%" in st["reply"]

    out = chat(cid, "Please create the order ticket")
    assert len(out["pending_actions"]) == 1 and out["pending_actions"][0]["status"] == "awaiting_approval"
    tid = out["pending_actions"][0]["id"]
    r = c.post(f"/api/approve/{tid}", json={"client_id": cid})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert c.get("/api/audit/verify").json()["valid"]
    acts = [e["action"] for e in c.get("/api/audit", params={"client_id": cid}).json()]
    for a in ["compliance_check", "tool:propose_allocation", "tool:create_order_ticket", "approve_order"]:
        assert a in acts


def test_approval_endpoint_guards():
    cid, other = start(), start("persona_chen")
    profile_via_chat(cid)
    tid = chat(cid, "create order ticket")["pending_actions"][0]["id"]
    assert c.post(f"/api/approve/{tid}", json={"client_id": other}).status_code == 403
    assert c.post("/api/approve/nope", json={"client_id": cid}).status_code == 403
    assert c.post(f"/api/approve/{tid}", json={"client_id": cid}).status_code == 200
    assert c.post(f"/api/approve/{tid}", json={"client_id": cid}).status_code == 403


def test_order_without_allocation_refused():
    cid = start()
    out = chat(cid, "create the order ticket now")
    assert out["pending_actions"] == []


def test_persona_wang_vulnerable_cap():
    cid = start("persona_wang")
    chat(cid, "advise me")
    for a in ["Stable", "About 25%", "Hold and wait"]:
        out = chat(cid, a)
    assert out["allocation"]
    r5 = [x for x in out["compliance"]["checks"] if x["rule_id"] == "R5"][0]
    assert r5["passed"] and "Moderate" in r5["detail"]
    assert "vulnerable" in out["allocation"]["summary"]


def test_persona_chen_growth_passes():
    cid = start("persona_chen")
    chat(cid, "advise me")
    for a in ["Stable", "About 10%", "Hold and wait"]:
        out = chat(cid, a)
    assert out["allocation"] and out["compliance"]["passed"]


def test_rest_pipeline_and_stress():
    cid = start()
    r = c.post("/api/profile", json={"client_id": cid, "answers": {
        "loss_reaction": "sell_some", "income_stability": "stable", "liquidity_need_pct": 10}})
    assert r.status_code == 200 and r.json()["bucket"] == "Moderate"
    a = c.post("/api/allocation", json={"client_id": cid, "preferred_ids": ["P13"]}).json()
    assert a["allocation"] and len(a["attempts"]) == 2 and a["why_not"]
    s = c.post("/api/stress", json={"allocation_id": a["allocation"]["id"], "scenario": "equity_-20"}).json()
    assert s["loss_pct"] < 0 and s["by_line"] and 0 <= s["goal"]["probability"] <= 1
    assert c.post("/api/stress", json={"allocation_id": a["allocation"]["id"], "scenario": "zzz"}).status_code == 422
    assert c.post("/api/stress", json={"allocation_id": "nope", "scenario": "equity_-20"}).status_code == 404


def test_profile_incomplete_returns_409():
    cid = start()
    r = c.post("/api/profile", json={"client_id": cid, "answers": {"loss_reaction": "hold"}})
    assert r.status_code == 409 and r.json()["detail"]["missing"]


def test_unknown_client_and_bad_input():
    assert c.post("/api/chat", json={"client_id": "x", "message": "hi"}).status_code == 404
    assert c.post("/api/chat", json={"client_id": "x", "message": "a" * 5000}).status_code == 422
    assert c.post("/api/session", json={"persona_id": "nobody"}).status_code == 404


def test_compare_and_products():
    assert len(c.get("/api/products").json()) == 15
    r = c.post("/api/compare", json={"product_ids": ["P13", "P03"]}).json()
    assert len(r["rows"]) == 2


def test_blank_client_flow_asks_everything():
    cid = c.post("/api/session", json={}).json()["client_id"]
    out = chat(cid, "hello")
    assert out["question"]["id"] == "age"
    out = chat(cid, "I am 50")
    assert out["question"]["id"] == "horizon_years"
