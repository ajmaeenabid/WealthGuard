"""Stress scenarios and backtests computed from real historical data (app/data/real)."""
import csv
import os

import pytest
from fastapi.testclient import TestClient

from app import allocation as al
from app import realdata, simulator
from app.compliance import banned_phrases
from app.main import app
from app.schemas import AllocationLine
from tests.helpers import PRODUCTS, persona_profile

c = TestClient(app)
REAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "data", "real", "returns_annual.csv")


def raw(year):
    return next({k: float(v) for k, v in r.items()} for r in csv.DictReader(open(REAL)) if int(r["year"]) == year)


def test_real_scenarios_match_the_raw_data():
    s = simulator.SCENARIOS["crash_2008"]["shocks"]
    r = raw(2008)
    assert s["equity_fund"] == pytest.approx(r["sp500"] * 100, abs=0.05)
    assert s["gold"] == pytest.approx(r["gold"] * 100, abs=0.05)
    assert s["cash"] == pytest.approx(r["tbill_3m"] * 100, abs=0.05)
    assert s["bond"] == pytest.approx((0.6 * r["tbond_10y"] + 0.4 * r["tbill_3m"]) * 100, abs=0.05)
    assert s["balanced_fund"] == pytest.approx((0.6 * r["sp500"] + 0.4 * r["tbond_10y"]) * 100, abs=0.05)


def test_multi_year_episodes_compound_the_real_years():
    g = 1.0
    for y in (1929, 1930, 1931, 1932):
        g *= 1 + raw(y)["sp500"]
    assert simulator.SCENARIOS["great_depression"]["shocks"]["equity_fund"] == pytest.approx((g - 1) * 100, abs=0.05)
    assert simulator.SCENARIOS["great_depression"]["shocks"]["equity_fund"] < -60


def test_scenarios_tell_the_real_story():
    sc = simulator.SCENARIOS
    assert sc["crash_2008"]["shocks"]["bond"] > 0 and sc["crash_2008"]["shocks"]["equity_fund"] < -30
    assert sc["rate_+2"]["shocks"]["bond"] < 0 and sc["rate_+2"]["shocks"]["equity_fund"] < 0   # 2022: stocks and bonds fell
    assert sc["inflation_spike"]["shocks"]["gold"] > 50
    assert sc["dotcom_bust"]["shocks"]["equity_fund"] < -30


def test_every_scenario_declares_its_basis_and_hypothetical_is_labelled():
    for k, v in simulator.SCENARIOS.items():
        b = v["basis"]
        assert b["note"] and banned_phrases(b["note"]) == []
        if k == "equity_-20":
            assert b["type"] == "hypothetical" and b["source"] is None
        else:
            assert b["type"] == "historical" and b["source"] and "Real" in b["note"]
    assert "10-year rate rose" in simulator.SCENARIOS["rate_+2"]["basis"]["note"]
    assert "12.3%" in simulator.SCENARIOS["inflation_spike"]["basis"]["note"]
    assert "lost purchasing power" in simulator.SCENARIOS["inflation_spike"]["basis"]["note"]   # cash 7.8% < CPI 12.3%


def test_stress_uses_the_real_shocks():
    pr = persona_profile("persona_li")
    a = al.build(pr, PRODUCTS)
    r = simulator.stress(a, PRODUCTS, "crash_2008")
    expected = sum(l.weight * simulator.SCENARIOS["crash_2008"]["shocks"][PRODUCTS[l.product_id].asset_class] for l in a.lines)
    assert r["loss_pct"] == pytest.approx(expected, abs=0.01) and r["basis"]["type"] == "historical"


def _single_line(profile, product_id, horizon):
    a = al.build(profile, PRODUCTS)
    a = a.model_copy(update={"lines": [AllocationLine(product_id=product_id, weight=1.0, rationale="test")]})
    p = profile.model_copy(update={"horizon_years": horizon, "investable_amount_cny": 100000, "goal_target_cny": 110000})
    return a, p


def test_backtest_matches_a_hand_computation_for_cash():
    a, p = _single_line(persona_profile("persona_li"), "P01", 3)   # P01 is cash, fee 0.2%
    h = simulator.historical_backtest(a, PRODUCTS, p)
    ys = realdata.years()
    assert h["windows"] == len(ys) - 3 + 1 and h["first_year"] == 1928 and h["last_year"] == 2025
    v = 100000.0
    for y in (1928, 1929, 1930):
        v *= 1 + raw(y)["tbill_3m"] - 0.002
    finals = []
    for i in range(len(ys) - 2):
        x = 100000.0
        for y in ys[i:i + 3]:
            x *= 1 + raw(y)["tbill_3m"] - 0.002
        finals.append(x)
    assert h["worst_cny"] == pytest.approx(min(finals), abs=0.01) and h["best_cny"] == pytest.approx(max(finals), abs=0.01)
    assert h["windows_reaching_target"] == sum(1 for f in finals if f >= 110000)


def test_backtest_is_deterministic_and_ordered():
    pr = persona_profile("persona_chen")
    a = al.build(pr, PRODUCTS)
    h1, h2 = simulator.historical_backtest(a, PRODUCTS, pr), simulator.historical_backtest(a, PRODUCTS, pr)
    assert h1 == h2 and h1["worst_cny"] <= h1["median_cny"] <= h1["best_cny"]
    assert 0 <= h1["share_reaching_target"] <= 1 and 0 <= h1["bootstrap_probability"] <= 1
    assert h1["windows"] == 98 - round(pr.horizon_years) + 1
    assert "Past performance is not a reliable indicator" in h1["note"] and banned_phrases(h1["note"]) == []


def test_equity_heavy_has_a_worse_worst_case_than_cash():
    pr = persona_profile("persona_chen")
    eq, p = _single_line(pr, "P11", 10)
    cash, _ = _single_line(pr, "P01", 10)
    assert simulator.historical_backtest(eq, PRODUCTS, p)["worst_cny"] < simulator.historical_backtest(cash, PRODUCTS, p)["worst_cny"]


# ------------------------------------------------------------------------------------------ API and chat
def _allocation():
    cid = c.post("/api/session", json={"persona_id": "persona_li"}).json()["client_id"]
    c.post("/api/profile", json={"client_id": cid, "answers": {"loss_reaction": "sell_some", "income_stability": "stable",
                                                                "liquidity_need_pct": 10}})
    return c.post("/api/allocation", json={"client_id": cid}).json()["allocation"]["id"]


def test_api_stress_returns_basis_and_historical_for_every_scenario():
    aid = _allocation()
    for sc in simulator.SCENARIOS:
        r = c.post("/api/stress", json={"allocation_id": aid, "scenario": sc})
        assert r.status_code == 200, sc
        j = r.json()
        assert j["basis"]["note"] and j["goal"]["historical"]["windows"] > 0
    assert c.post("/api/stress", json={"allocation_id": aid, "scenario": "mars"}).status_code == 422


def test_chat_stress_reply_cites_real_history_and_passes_language_rules():
    cid = c.post("/api/session", json={"persona_id": "persona_li"}).json()["client_id"]
    chat = lambda m: c.post("/api/chat", json={"client_id": cid, "message": m}).json()
    for m in ["hi", "Stable", "About 10%", "Sell some"]:
        chat(m)
    out = chat("What if there is a 2008 style crash?")
    assert "Real 2008 market returns" in out["reply"] and "Real-history check" in out["reply"]
    assert "Past performance is not a reliable indicator" in out["reply"] and banned_phrases(out["reply"]) == []
    out = chat("what about the great depression?")
    assert "1929-1932" in out["reply"]


def test_ui_offers_the_real_scenarios():
    html = c.get("/").text
    for v in ["dotcom_bust", "great_depression", "crash_2008", "rate_+2", "inflation_spike", 'id="histOut"']:
        assert v in html
