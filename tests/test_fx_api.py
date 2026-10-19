"""HTTP side of currency conversion: rate endpoints, converted transactions, and the converted estimate next to the exact totals."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import accounts
from app.finance import money, routes
from app.main import app

c = TestClient(app)
T = money.today()


@pytest.fixture(autouse=True)
def sign_in(monkeypatch):
    monkeypatch.setenv("WEALTHGUARD_AUTH", "1")
    accounts._FAILS.clear()
    routes._HITS.clear()


@pytest.fixture
def li():
    r = c.post("/api/auth/login", json={"username": "li", "password": "123"})
    return {"Authorization": "Bearer " + r.json()["token"]}


def mk(h, name, cur, opening="1000", typ="cash"):
    r = c.post("/api/fin/accounts", headers=h, json={"name": name, "type": typ, "opening_balance": opening, "opening_date": (T - timedelta(days=30)).isoformat(), "currency": cur})
    assert r.status_code == 200, r.text
    return r.json()


def test_rates_endpoint_shows_provenance(fx_live, li):
    j = c.get("/api/fin/fx", headers=li).json()
    assert j["available"] and j["source"].startswith("ExchangeRate-API") and j["provider_date"] == "2026-10-19" and "Indicative" in j["note"] and j["attribution"]


def test_convert_endpoint_and_errors(fx_live, li):
    j = c.get("/api/fin/fx/convert", headers=li, params={"amount": "10", "from": "BDT", "to": "CNY"}).json()
    assert j["converted"] == "0.54" and j["quote"]["source"] == "er-api"
    assert c.get("/api/fin/fx/convert", headers=li, params={"amount": "10", "from": "BDT", "to": "EUR"}).status_code == 503
    assert c.get("/api/fin/fx/convert", headers=li, params={"amount": "abc", "from": "BDT", "to": "CNY"}).status_code == 400


def test_no_rate_gives_a_clear_503_not_a_number(li):
    r = c.get("/api/fin/fx/convert", headers=li, params={"amount": "10", "from": "BDT", "to": "CNY"})
    assert r.status_code == 503 and "no current exchange rate" in r.json()["detail"].lower()
    assert c.get("/api/fin/fx", headers=li).json()["available"] is False


def test_requires_sign_in(fx_live):
    assert c.get("/api/fin/fx").status_code == 401


def test_posting_a_transaction_in_another_currency_converts_and_keeps_the_original(fx_live, li):
    a = mk(li, "Yuan", "CNY")
    body = {"type": "expense", "account_id": a["id"], "amount": "10", "currency": "BDT", "category": "food"}
    assert c.post("/api/fin/transactions", headers=li, json=body).status_code == 400          # not converted unless asked
    t = c.post("/api/fin/transactions", headers=li, json=dict(body, convert=True)).json()
    assert t["final_amount"] == "0.54" and t["original"]["currency"] == "BDT" and t["original"]["amount"] == "10.00"
    got = c.get(f"/api/fin/transactions/{t['id']}", headers=li).json()
    assert got["original"]["rate"] == t["original"]["rate"]


def test_position_shows_other_currency_accounts_as_a_labelled_estimate(fx_live, li):
    c.post("/api/fin/settings", headers=li, json={"base_currency": "CNY"})
    mk(li, "Yuan", "CNY", "500")
    mk(li, "Taka", "BDT", "12340")
    c.get("/api/fin/fx", headers=li)                                                           # warms the cache the way any conversion would
    pos = c.get("/api/fin/position", headers=li).json()
    est = pos["converted_estimate"]
    assert pos["liquid"] == "500.00" and pos["excluded_other_currency"] == ["Taka"]           # the exact figures are untouched
    assert est["available"] and est["liquid"] == "1169.27" and est["accounts"][0]["converted"] == "669.27" and "Estimate" in est["note"]
