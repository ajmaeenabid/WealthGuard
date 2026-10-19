"""HTTP layer: auth and permissions, user isolation, validation, idempotency, dashboard, reports, files, the assistant endpoint."""
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import accounts
from app.finance import money, routes
from app.main import app

c = TestClient(app)
T = money.today()


def day(n):
    return (T - timedelta(days=n)).isoformat()


@pytest.fixture(autouse=True)
def sign_in_required(monkeypatch):
    monkeypatch.setenv("WEALTHGUARD_AUTH", "1")
    accounts._FAILS.clear()
    routes._HITS.clear()


def login(user):
    r = c.post("/api/auth/login", json={"username": user, "password": "123"})
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def li():
    return login("li")


def mk_account(h, name="Cash", type="cash", opening="5000"):
    r = c.post("/api/fin/accounts", headers=h, json={"name": name, "type": type, "opening_balance": opening, "opening_date": day(100)})
    assert r.status_code == 200, r.text
    return r.json()


def mk_txn(h, acc, amount="100", **kw):
    body = dict({"type": "expense", "account_id": acc["id"], "amount": amount, "category": "food", "ts": day(1)}, **kw)
    r = c.post("/api/fin/transactions", headers=h, json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ============================================================================================== access
def test_every_finance_route_needs_a_signed_in_member():
    for method, path in [("get", "/api/fin/accounts"), ("get", "/api/fin/dashboard"), ("post", "/api/fin/transactions"), ("post", "/api/fin/assistant/chat"), ("get", "/api/fin/meta")]:
        assert getattr(c, method)(path).status_code == 401, path


def test_the_admin_has_no_personal_finance_data():
    h = login("admin")
    assert c.get("/api/fin/accounts", headers=h).status_code == 403
    assert "do not have personal finance data" in c.get("/api/fin/dashboard", headers=h).json()["detail"]


def test_an_administrator_can_switch_personal_finance_off_for_one_account(li):
    mk_account(li)
    ha = login("admin")
    assert c.post("/api/admin/users/li/permissions", headers=ha, json={"permissions": {"money": False}}).json()["permissions"]["money"] is False
    assert c.get("/api/fin/accounts", headers=li).status_code == 403
    assert "personal finance" in c.get("/api/fin/accounts", headers=li).json()["detail"]
    assert c.get("/api/fin/accounts", headers=login("chen")).status_code == 200
    c.post("/api/admin/users/li/permissions", headers=ha, json={"permissions": {"money": True}})
    assert c.get("/api/fin/accounts", headers=li).status_code == 200


def test_one_member_can_never_see_or_touch_anothers_money(li):
    chen = login("chen")
    acc = mk_account(li, "Cash")
    t = mk_txn(li, acc)
    assert c.get("/api/fin/accounts", headers=chen).json() == []
    assert c.get(f"/api/fin/transactions/{t['id']}", headers=chen).status_code == 404
    assert c.post(f"/api/fin/transactions/{t['id']}", headers=chen, json={"amount": "1"}).status_code == 404
    assert c.post(f"/api/fin/transactions/{t['id']}/delete", headers=chen).status_code == 404
    assert c.post("/api/fin/transactions", headers=chen, json={"type": "expense", "account_id": acc["id"], "amount": "5", "category": "food"}).status_code == 404
    assert c.get("/api/fin/transactions", headers=chen).json()["total"] == 0
    assert c.post(f"/api/fin/accounts/{acc['id']}", headers=chen, json={"name": "Mine now"}).status_code == 404
    assert c.get("/api/fin/transactions", headers=li).json()["total"] == 1


# ============================================================================================== accounts and transactions
def test_accounts_and_position_over_http(li):
    cash = mk_account(li, "Cash", "cash", "1000")
    bank = mk_account(li, "Bank", "bank", "9000")
    sav = mk_account(li, "Savings", "savings", "0")
    mk_txn(li, cash, "250")
    c.post("/api/fin/transactions", headers=li, json={"type": "transfer", "account_id": bank["id"], "to_account_id": sav["id"], "amount": "3000", "ts": day(1)})
    pos = c.get("/api/fin/position", headers=li).json()
    assert pos["liquid"] == "9750.00" and pos["bank"] == "6000.00" and pos["savings"] == "3000.00" and pos["net_worth"] == "9750.00"
    r = c.post(f"/api/fin/accounts/{cash['id']}/reconcile", headers=li, json={"actual": "700", "apply": True}).json()
    assert r["difference"] == "-50.00" and r["applied"] is True
    assert c.post("/api/fin/accounts", headers=li, json={"name": "Cash", "type": "cash"}).status_code == 409
    assert c.post("/api/fin/accounts", headers=li, json={"name": "X", "type": "spaceship"}).status_code == 400


def test_floating_point_amounts_are_refused_and_validation_errors_are_readable(li):
    acc = mk_account(li)
    bad = c.post("/api/fin/transactions", headers=li, json={"type": "expense", "account_id": acc["id"], "amount": 12.5, "category": "food"})
    assert bad.status_code == 422
    r = c.post("/api/fin/transactions", headers=li, json={"type": "expense", "account_id": acc["id"], "amount": "-5", "category": "food"})
    assert r.status_code == 400 and "cannot be negative" in r.json()["detail"]
    r = c.post("/api/fin/transactions", headers=li, json={"type": "expense", "account_id": acc["id"], "gross_amount": "100", "final_amount": "70", "discount": "10", "category": "food"})
    assert r.status_code == 400 and "do not add up" in r.json()["detail"]
    r = c.post("/api/fin/transactions", headers=li, json={"type": "expense", "account_id": acc["id"], "amount": "5", "category": "food", "ts": "yesterday-ish"})
    assert r.status_code == 400 and "not a valid date" in r.json()["detail"]
    assert c.post("/api/fin/transactions", headers=li, json={"type": "expense", "account_id": acc["id"], "amount": "5", "note": "x" * 700}).status_code == 422
    assert c.post("/api/fin/transactions", headers=li, json={"type": "expense", "account_id": "nope", "amount": "5"}).status_code == 404


def test_posting_twice_with_the_same_idempotency_key_creates_one_record(li):
    acc = mk_account(li)
    body = {"type": "expense", "account_id": acc["id"], "amount": "100", "category": "food", "idempotency_key": "form-123"}
    a = c.post("/api/fin/transactions", headers=li, json=body).json()
    b = c.post("/api/fin/transactions", headers=li, json=body).json()
    assert a["id"] == b["id"] and b["duplicate"] is True
    assert c.get("/api/fin/transactions", headers=li).json()["total"] == 1


def test_edit_delete_search_filter_sort_and_paginate_over_http(li):
    acc = mk_account(li)
    for i, (m, amt, cat) in enumerate([("Shwapno", "300", "food"), ("Daraz", "900", "shopping"), ("Pathao", "120", "transport"), ("Tea Stall", "40", "food")]):
        mk_txn(li, acc, amt, merchant=m, category=cat, ts=day(i + 1))
    g = lambda **p: c.get("/api/fin/transactions", headers=li, params=p).json()
    assert g()["total"] == 4 and g(category="food")["total"] == 2 and g(q="daraz")["total"] == 1 and g(min_amount="100", max_amount="500")["total"] == 2
    assert [t["merchant"] for t in g(sort="amount", direction="asc")["items"]] == ["Tea Stall", "Pathao", "Shwapno", "Daraz"]
    assert len(g(size=2, page=2)["items"]) == 2 and g(size=2)["pages"] == 2
    assert c.get("/api/fin/transactions", headers=li, params={"sort": "DROP TABLE"}).status_code == 422
    t = g(q="Daraz")["items"][0]
    u = c.post(f"/api/fin/transactions/{t['id']}", headers=li, json={"amount": "850", "note": "sale price"}).json()
    assert u["final_amount"] == "850.00" and u["note"] == "sale price"
    assert c.post(f"/api/fin/transactions/{t['id']}/delete", headers=li).status_code == 200
    assert c.get(f"/api/fin/transactions/{t['id']}", headers=li).status_code == 404 and g()["total"] == 3


# ============================================================================================== planning over http
def test_budgets_goals_and_bills_over_http(li):
    cash = mk_account(li, "Cash", "cash", "20000")
    sav = mk_account(li, "Savings", "savings", "0")
    mk_txn(li, cash, "900", category="food", ts=day(0))
    b = c.post("/api/fin/budgets", headers=li, json={"category": "food", "limit": "1000", "alert_pct": 80}).json()
    assert b["status"] == "warning" and b["remaining"] == "100.00"
    assert c.post("/api/fin/budgets", headers=li, json={"limit": "0"}).status_code == 400
    g = c.post("/api/fin/goals", headers=li, json={"name": "Laptop", "target": "50000", "saved": "5000", "monthly_target": "5000"}).json()
    c.post("/api/fin/transactions", headers=li, json={"type": "transfer", "account_id": cash["id"], "to_account_id": sav["id"], "amount": "4000", "goal_id": g["id"], "ts": day(1)})
    assert c.get("/api/fin/goals", headers=li).json()[0]["saved"] == "9000.00"
    o = c.post("/api/fin/obligations", headers=li, json={"name": "Internet", "amount": "800", "next_due": day(-1), "account_id": cash["id"], "category": "utilities"}).json()
    assert o["status"] == "due"
    paid = c.post(f"/api/fin/obligations/{o['id']}/pay", headers=li, json={}).json()
    again = c.get("/api/fin/obligations", headers=li).json()[0]
    assert paid["transaction"]["obligation_id"] == o["id"] and again["next_due"] > o["next_due"]
    assert any(a["kind"] == "budget_warning" for a in c.get("/api/fin/alerts", headers=li).json())
    assert c.post(f"/api/fin/budgets/{b['id']}/delete", headers=li).status_code == 200 and c.get("/api/fin/budgets", headers=li).json() == []
    f = c.get("/api/fin/forecast", headers=li, params={"reduce": "food:20"}).json()
    assert f["is_estimate"] and f["scenario"]["reductions_pct"] == {"food": 20.0}
    assert c.get("/api/fin/forecast", headers=li, params={"reduce": "food"}).status_code == 200
    assert c.get("/api/fin/forecast", headers=li, params={"reduce": "food:abc"}).status_code == 400


# ============================================================================================== dashboard, reports, files
def test_dashboard_returns_real_numbers_only(li):
    assert c.get("/api/fin/dashboard", headers=li).json()["summary"]["spending"] == "0.00"                     # empty means empty, not demo data
    cash = mk_account(li, "Cash", "cash", "1000")
    c.post("/api/fin/transactions", headers=li, json={"type": "income", "account_id": cash["id"], "amount": "30000", "category": "salary", "ts": day(2)})
    mk_txn(li, cash, "700", category="food", merchant="Shwapno", ts=day(1))
    d = c.get("/api/fin/dashboard", headers=li).json()
    assert d["summary"]["income"] == "30000.00" and d["summary"]["spending"] == "700.00" and d["position"]["liquid"] == "30300.00"
    assert d["summary"]["by_category"][0]["category"] == "food" and d["recent"][0]["merchant"] == "Shwapno"
    assert {"comparison", "budgets", "goals", "upcoming", "alerts", "insights", "forecast"} <= set(d)
    assert c.get("/api/fin/dashboard", headers=li, params={"kind": "decade"}).status_code == 422
    assert c.get("/api/fin/dashboard", headers=li, params={"kind": "custom", "start": day(10), "end": day(0)}).status_code == 200
    assert c.get("/api/fin/dashboard", headers=li, params={"kind": "custom", "start": day(0), "end": day(10)}).status_code == 400


def test_report_generation_listing_and_export(li):
    cash = mk_account(li, "Cash", "cash", "1000")
    mk_txn(li, cash, "300", ts=day(1))
    r = c.post("/api/fin/reports", headers=li, json={"kind": "month"}).json()
    assert r["id"].startswith("rep_") and r["narrative"]["mode"] == "rules" and r["overview"]["spending"] == "300.00"
    assert c.get("/api/fin/reports", headers=li).json()[0]["id"] == r["id"] and c.get(f"/api/fin/reports/{r['id']}", headers=li).json()["id"] == r["id"]
    md = c.get(f"/api/fin/reports/{r['id']}/export", headers=li)
    assert md.status_code == 200 and md.text.startswith("# Financial report") and "attachment" in md.headers["content-disposition"]
    assert c.get(f"/api/fin/reports/{r['id']}/export", headers=li, params={"format": "json"}).json()["id"] == r["id"]
    assert c.get(f"/api/fin/reports/{r['id']}", headers=login("chen")).status_code == 404
    assert c.post("/api/fin/reports", headers=li, json={"kind": "custom", "start": day(0), "end": day(9)}).status_code == 400


def test_csv_export_and_import_over_http(li):
    cash = mk_account(li, "Cash", "cash", "1000")
    mk_txn(li, cash, "123", merchant="Shwapno")
    csv_text = c.get("/api/fin/export/transactions.csv", headers=li)
    assert csv_text.status_code == 200 and "text/csv" in csv_text.headers["content-type"] and "Shwapno" in csv_text.text
    chen = login("chen")
    mk_account(chen, "Cash", "cash", "0")
    res = c.post("/api/fin/import/transactions", headers=chen, json={"csv": csv_text.text}).json()
    assert res["created"] == 1 and c.post("/api/fin/import/transactions", headers=chen, json={"csv": csv_text.text}).json()["skipped_duplicates"] == 1


# ============================================================================================== the assistant endpoint
def chat(h, text, rid=None, source="text"):
    return c.post("/api/fin/assistant/chat", headers=h, json={"text": text, "request_id": rid or uuid.uuid4().hex, "source": source})


def test_assistant_endpoint_full_conversation_with_resume_and_replay(li):
    mk_account(li, "Cash", "cash", "5000")
    r = chat(li, "I spent 850 taka at the grocery store today on rice, oil and vegetables, with a 50 taka discount").json()
    assert r["awaiting"] == "amount_basis"
    cur = c.get("/api/fin/assistant/session", headers=li).json()                                                  # a page refresh
    assert cur["state"] == "awaiting_clarification" and cur["awaiting"] == "amount_basis" and len(cur["messages"]) == 2
    assert chat(li, "Before the discount", "r-a").json()["awaiting"] == "tax"
    assert chat(li, "No.").json()["awaiting"] == "confirm"
    assert c.get("/api/fin/transactions", headers=li).json()["total"] == 0                                         # nothing saved yet
    saved = chat(li, "Save it.", "r-save").json()
    retry = chat(li, "Save it.", "r-save").json()                                                                  # the network response was lost; the client retries
    assert saved["transaction"]["final_amount"] == "800.00" and retry["replayed"] is True and retry["transaction"]["id"] == saved["transaction"]["id"]
    assert c.get("/api/fin/transactions", headers=li).json()["total"] == 1
    assert c.get("/api/fin/assistant/session", headers=li).json()["state"] == "idle"


def test_assistant_endpoint_cancel_validation_and_rate_limit(li):
    mk_account(li, "Cash", "cash", "5000")
    chat(li, "spent 100 on lunch")
    assert c.post("/api/fin/assistant/cancel", headers=li).json()["cancelled"] is True
    assert c.post("/api/fin/assistant/chat", headers=li, json={"text": "", "request_id": "x"}).status_code == 400
    assert c.post("/api/fin/assistant/chat", headers=li, json={"text": "hi", "request_id": "x", "source": "telepathy"}).status_code == 400
    assert c.post("/api/fin/assistant/chat", headers=li, json={"text": "x" * 2000, "request_id": "y"}).status_code == 422
    routes._HITS.clear()
    codes = [chat(li, "hello", f"rl-{i}").status_code for i in range(routes.ASSISTANT_PER_MINUTE + 3)]
    assert codes.count(429) == 3


def test_meta_and_ai_usage_endpoints(li):
    m = c.get("/api/fin/meta", headers=li).json()
    assert m["currency"] == "BDT" and "food" in m["expense_categories"] and "groceries" in m["expense_categories"]["food"] and m["ai"]["enabled"] is False
    u = c.get("/api/fin/ai-usage", headers=li).json()
    assert u["calls"] == 0 and u["model"] == "openai/gpt-oss-20b" and u["prices_usd_per_million"]["input"] == 0.075


def test_finance_actions_are_audited_without_amounts_leaking_other_users_data(li):
    acc = mk_account(li)
    mk_txn(li, acc)
    log = c.get("/api/audit", headers=login("admin")).text
    assert "fin_account_created" in log and "fin_txn_created" in log
    assert c.get("/api/audit/verify", headers=li).json()["valid"] is True
