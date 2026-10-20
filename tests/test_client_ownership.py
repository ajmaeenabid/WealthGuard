"""A signed-in user cannot read or act on another user's advisor chat through any client_id endpoint."""
import pytest
from fastapi.testclient import TestClient

from app import accounts
from app.main import app

c = TestClient(app)


@pytest.fixture(autouse=True)
def sign_in_required(monkeypatch):
    monkeypatch.setenv("WEALTHGUARD_AUTH", "1")
    accounts._FAILS.clear()


def login(user):
    r = c.post("/api/auth/login", json={"username": user, "password": "123"})
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_other_account_gets_403_on_every_client_id_endpoint():
    li, wang = login("li"), login("wang")
    cid = c.post("/api/session", headers=li, json={"persona_id": "persona_li"}).json()["client_id"]
    for m in ["Hi, please advise me", "Stable", "About 10%", "Sell some"]:
        out = c.post("/api/chat", headers=li, json={"client_id": cid, "message": m}).json()
    ticket = c.post("/api/chat", headers=li, json={"client_id": cid, "message": "Please create the order ticket"}).json()["pending_actions"][0]["id"]
    alloc_id = out["allocation"]["id"]
    calls = [
        ("post", f"/api/approve/{ticket}", {"json": {"client_id": cid}}),
        ("post", f"/api/reject/{ticket}", {"json": {"client_id": cid}}),
        ("post", "/api/stress", {"json": {"allocation_id": alloc_id, "scenario": "equity_-20"}}),
        ("post", "/api/allocation", {"json": {"client_id": cid}}),
        ("post", "/api/documents", {"json": {"client_id": cid, "filename": "a.txt", "text": "hello"}}),
        ("post", "/api/ledger/sample", {"json": {"client_id": cid}}),
        ("get", "/api/ledger", {"params": {"client_id": cid}}),
        ("get", "/api/receipt", {"params": {"client_id": cid}}),
        ("get", "/api/provenance", {"params": {"client_id": cid, "kind": "bucket"}}),
        ("get", "/api/selfinspection", {"params": {"client_id": cid}}),
        ("get", "/api/state", {"params": {"client_id": cid}}),
    ]
    for method, path, kw in calls:
        r = getattr(c, method)(path, headers=wang, **kw)
        assert r.status_code == 403, (path, r.status_code, r.text[:120])
    r = c.post(f"/api/approve/{ticket}", headers=li, json={"client_id": cid})
    assert r.status_code == 200 and r.json()["status"] == "approved"


def test_security_headers_are_sent():
    r = c.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "same-origin" and "microphone=(self)" in r.headers["permissions-policy"]
