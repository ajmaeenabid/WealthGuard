"""Revealed-risk replay: real episode paths, decisions, and the rule that behaviour can only make the profile more cautious."""
import csv
import os

import pytest
from fastapi.testclient import TestClient

from app import profiling, redteam, replay, service, store
from app.agent.tools import Ctx
from app.main import app
from app.security import audit, tiers

c = TestClient(app)
REAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "data", "real")


@pytest.fixture(autouse=True)
def clean_sessions():
    replay.reset()
    yield
    replay.reset()


def client_with_allocation(persona="persona_li", stated=None):
    cid = redteam._probe(persona)[0]
    if stated:
        d = store.load_client(cid)
        d["facts"]["loss_reaction"] = stated
        store.save_client(cid, d)
    service.run_pipeline(cid, [])
    return cid


def play(cid, episode="crash_2008", portfolio="equity", choices=("hold",)):
    r = replay.start(cid, episode, portfolio)
    i = 0
    while r["state"] == "decision":
        r = replay.step(r["id"], cid, choices[min(i, len(choices) - 1)])
        i += 1
    return r


def prices():
    with open(os.path.join(REAL, "shiller_monthly.csv"), encoding="utf-8") as f:
        return {r["month"]: float(r["sp500"]) for r in csv.DictReader(f)}


def test_equity_replay_matches_an_independent_computation_from_the_raw_csv():
    cid = client_with_allocation()
    a, b, _ = replay.EPISODES["crash_2008"]
    p = prices()
    ms = [m for m in sorted(p) if a <= m <= b]
    r = play(cid, "crash_2008", "equity", ("hold",))
    start = store.load_profile(cid).investable_amount_cny
    assert [h["month"] for h in r["history"]] == ms
    for h, m in zip(r["history"], ms):
        assert h["value"] == pytest.approx(start * p[m] / p[ms[0]], rel=1e-5)
    assert r["result"]["held_value"] == pytest.approx(start * p[ms[-1]] / p[ms[0]], abs=0.01)
    assert r["result"]["final_value"] == r["result"]["held_value"] and r["result"]["cost_of_acting"] == pytest.approx(0, abs=0.01)


def test_decision_points_fire_at_the_first_10_20_and_30_percent_drawdowns():
    cid = client_with_allocation()
    p = prices()
    ms = [m for m in sorted(p) if "2007-10" <= m <= "2009-12"]
    peak, expected = p[ms[0]], []
    for m in ms:
        peak = max(peak, p[m])
        dd = p[m] / peak - 1
        for t in replay.THRESHOLDS:
            if dd <= t and t not in [e[1] for e in expected] and not any(e[1] <= t for e in expected if e[0] == m):
                expected.append((m, t))
    r = replay.start(cid, "crash_2008", "equity")
    seen = []
    while r["state"] == "decision":
        seen.append((r["prompt"]["month"], r["prompt"]["threshold"]))
        r = replay.step(r["id"], cid, "hold")
    assert [t for _, t in seen] == sorted([t for _, t in seen], reverse=True) and len(seen) == 3
    assert seen[0][0] == expected[0][0] and all(replay.THRESHOLDS.count(t) == 1 for _, t in seen)


def test_my_allocation_replay_uses_the_clients_mix_and_is_deterministic():
    cid = client_with_allocation()
    r1 = play(cid, "dotcom_bust", "mine")
    r2 = play(cid, "dotcom_bust", "mine")
    assert r1["history"] == r2["history"] and r1["result"]["worst_drawdown"] > -0.2


def test_selling_before_a_crash_helps_and_the_cost_is_reported_honestly():
    cid = client_with_allocation()
    r = play(cid, "crash_2008", "equity", ("sell_all",))
    x = r["result"]
    assert x["final_value"] > x["held_value"] and x["cost_of_acting"] > 0 and x["decisions"][0]["choice"] == "sell_all"


def test_selling_at_the_bottom_costs_money_in_a_recovery():
    cid = client_with_allocation()
    r = play(cid, "rate_+2", "equity", ("hold", "sell_all"))
    assert r["result"]["cost_of_acting"] != 0 and r["result"]["decisions"][-1]["choice"] == "sell_all"


def test_sell_some_moves_a_quarter_and_buy_more_adds_ten_percent_of_the_start():
    cid = client_with_allocation()
    start = store.load_profile(cid).investable_amount_cny
    r = replay.start(cid, "crash_2008", "equity")
    s = replay.SESSIONS[r["id"]]
    risky = s["risky"]
    replay.step(r["id"], cid, "sell_some")
    assert s["cash"] > 0 and s["cash"] == pytest.approx(0.25 * risky, rel=0.05)
    r = replay.start(cid, "crash_2008", "equity")
    replay.step(r["id"], cid, "buy_more")
    assert replay.SESSIONS[r["id"]]["added"] == pytest.approx(0.1 * start)


def test_choice_validation_and_ownership():
    cid = client_with_allocation()
    other = client_with_allocation("persona_chen")
    r = replay.start(cid, "crash_2008", "equity")
    assert replay.step(r["id"], cid, "panic")["status"] == 422 and replay.step(r["id"], other, "hold")["status"] == 403
    assert replay.step("rpl_nope", cid, "hold")["status"] == 403
    while r["state"] == "decision":
        r = replay.step(r["id"], cid, "hold")
    assert replay.step(r["id"], cid, "hold")["status"] == 409


def test_start_needs_a_profile_and_an_approved_allocation_and_a_known_episode():
    fresh = c.post("/api/session", json={"persona_id": "persona_li"}).json()["client_id"]
    assert replay.start(fresh, "crash_2008")["ok"] is False
    cid = client_with_allocation()
    assert "unknown episode" in replay.start(cid, "mars")["error"] and "portfolio" in replay.start(cid, "crash_2008", "x")["error"]


@pytest.mark.parametrize("stated,revealed,more_cautious", [
    ("hold", "sell_all", True), ("hold", "sell_some", True), ("buy_more", "hold", True), ("sell_some", "sell_all", True),
    ("sell_some", "sell_some", False), ("sell_all", "hold", False), ("hold", "buy_more", False), ("sell_all", "sell_all", False),
])
def test_comparison_is_more_cautious_only_when_the_reaction_was_more_cautious(stated, revealed, more_cautious):
    cid = client_with_allocation(stated=stated)
    r = play(cid, "crash_2008", "equity", ("hold", revealed, revealed))
    x = r["result"]
    assert x["stated_loss_reaction"] == stated and x["revealed_loss_reaction"] == revealed
    assert (x["comparison"] == "more_cautious") is more_cautious and x["can_apply"] is more_cautious


def test_a_replay_that_never_reaches_minus_20_percent_cannot_infer_anything():
    cid = client_with_allocation()
    x = play(cid, "dotcom_bust", "mine")["result"]
    assert x["comparison"] == "not_tested" and x["revealed_loss_reaction"] is None and x["can_apply"] is False


def test_applying_makes_the_profile_more_cautious_and_is_audited_and_single_use():
    cid = client_with_allocation(stated="hold")
    tol_before = store.load_profile(cid).risk_tolerance_score
    r = play(cid, "crash_2008", "equity", ("hold", "sell_all", "sell_all"))
    out = replay.apply(r["id"], cid)
    assert out["ok"] and (out["from"], out["to"]) == ("hold", "sell_all")
    d = store.load_client(cid)
    assert d["facts"]["loss_reaction"] == "sell_all" and d["profile"] is None
    tiers.execute("compute_risk_profile", {}, Ctx(cid))
    assert store.load_profile(cid).risk_tolerance_score < tol_before
    assert replay.apply(r["id"], cid)["status"] == 409
    acts = [e["action"] for e in audit.list_entries(cid)]
    assert {"replay_started", "replay_finished", "replay_applied"} <= set(acts) and audit.verify()["valid"]


@pytest.mark.parametrize("stated", profiling.QBY["loss_reaction"]["options"].keys())
@pytest.mark.parametrize("revealed", replay.CHOICES)
def test_behaviour_can_never_make_the_profile_less_cautious(stated, revealed):
    cid = client_with_allocation(stated=stated)
    r = play(cid, "crash_2008", "equity", ("hold", revealed, revealed))
    out = replay.apply(r["id"], cid)
    order = replay.REACTION_ORDER
    if out["ok"]:
        assert order.index(revealed) < order.index(stated)
        assert order.index(store.load_client(cid)["facts"]["loss_reaction"]) < order.index(stated)
    else:
        assert store.load_client(cid)["facts"]["loss_reaction"] == stated


def test_another_client_cannot_apply_my_replay():
    cid = client_with_allocation(stated="hold")
    other = client_with_allocation("persona_chen")
    r = play(cid, "crash_2008", "equity", ("hold", "sell_all", "sell_all"))
    assert replay.apply(r["id"], other)["status"] == 403 and store.load_client(cid)["facts"]["loss_reaction"] == "hold"


def test_api_round_trip():
    cid = client_with_allocation(stated="hold")
    r = c.post("/api/replay/start", json={"client_id": cid, "episode": "crash_2008", "portfolio": "equity"}).json()
    assert r["state"] == "decision" and r["prompt"]["choices"] == replay.CHOICES
    while r["state"] == "decision":
        r = c.post(f"/api/replay/{r['id']}/step", json={"client_id": cid, "choice": "sell_all"}).json()
    assert r["state"] == "done" and r["result"]["can_apply"]
    a = c.post(f"/api/replay/{r['id']}/apply", json={"client_id": cid})
    assert a.status_code == 200 and a.json()["to"] == "sell_all"
    assert c.post(f"/api/replay/{r['id']}/apply", json={"client_id": cid}).status_code == 409


@pytest.mark.parametrize("path,body,code", [
    ("/api/replay/start", {"client_id": "nope", "episode": "crash_2008"}, 404),
    ("/api/replay/start", {"client_id": "x", "episode": "crash_2008", "portfolio": "bad"}, 422),
    ("/api/replay/rpl_x/step", {"client_id": "nope", "choice": "hold"}, 404),
])
def test_api_validation(path, body, code):
    assert c.post(path, json=body).status_code == code


def test_api_error_codes_for_episode_and_state():
    cid = client_with_allocation()
    assert c.post("/api/replay/start", json={"client_id": cid, "episode": "mars"}).status_code == 422
    fresh = c.post("/api/session", json={"persona_id": "persona_li"}).json()["client_id"]
    assert c.post("/api/replay/start", json={"client_id": fresh, "episode": "crash_2008"}).status_code == 409


def test_ui_has_the_replay_card():
    html, js = c.get("/").text, c.get("/static/app.js").text
    assert 'id="rpCard"' in html and 'id="rpGo"' in html and 'id="rpChart"' in html and "rpApply" in js
    assert "用你的资金重演历史" in c.get("/static/i18n.js").text


def test_selling_out_at_the_first_prompt_still_reveals_the_reaction():
    cid = client_with_allocation(stated="hold")
    r = play(cid, "crash_2008", "equity", ("sell_all",))
    x = r["result"]
    assert len(x["decisions"]) == 1 and x["revealed_loss_reaction"] == "sell_all" and x["comparison"] == "more_cautious"


def test_an_early_partial_sale_counts_even_if_the_client_then_holds_at_minus_20():
    cid = client_with_allocation(stated="hold")
    x = play(cid, "crash_2008", "equity", ("sell_some", "hold", "hold"))["result"]
    assert x["revealed_loss_reaction"] == "sell_some" and x["can_apply"]


def test_holding_at_the_mild_drop_and_buying_more_later_is_reported_as_bolder_not_cautious():
    cid = client_with_allocation(stated="sell_some")
    x = play(cid, "crash_2008", "equity", ("hold", "buy_more", "buy_more"))["result"]
    assert x["revealed_loss_reaction"] == "buy_more" and x["comparison"] == "same_or_bolder" and x["can_apply"] is False
