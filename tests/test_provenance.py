"""Number provenance: every displayed number explains itself and recomputes."""
import hashlib
import os

import pytest
from fastapi.testclient import TestClient

from app import ledger, provenance, redteam, service, store
from app.main import app
from app.products import load_products

c = TestClient(app)
REAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "data", "real")


def setup_client(persona="persona_li"):
    cid = redteam._probe(persona)[0]
    aid = service.run_pipeline(cid, [])["allocation"].id
    return cid, aid


@pytest.mark.parametrize("kind,kw", [
    ("tolerance", {}), ("capacity", {}), ("bucket", {}), ("expected_return", {}), ("volatility", {}),
    ("stress_loss", {"scenario": "crash_2008"}), ("stress_loss", {"scenario": "equity_-20"}),
    ("goal_probability", {"shock_pct": -5.0}), ("backtest_share", {}), ("ledger_total", {}),
])
def test_every_kind_explains_itself_and_recomputes(kind, kw):
    cid, aid = setup_client()
    ledger.load_sample(cid, "balanced")
    r = provenance.explain(cid, kind, aid, **kw)
    assert r["ok"] and r["matches"] is True and r["formula"] and r["inputs"] and r["display"]


def test_profile_scores_are_the_sum_of_their_listed_contributions():
    cid, _ = setup_client()
    for kind in ("tolerance", "capacity"):
        r = provenance.explain(cid, kind)
        rows = [i for i in r["inputs"] if "contribution" in i]
        assert sum(i["contribution"] for i in rows) == pytest.approx(r["value"], abs=0.11)


def test_expected_return_matches_a_hand_calculation():
    cid, aid = setup_client()
    alloc, prods = store.load_allocation(aid), load_products()
    by_hand = round(sum(l.weight * (prods[l.product_id].expected_return - prods[l.product_id].annual_fee_pct / 100) for l in alloc.lines), 4)
    r = provenance.explain(cid, "expected_return", aid)
    assert r["value"] == by_hand == r["recomputed"]
    assert any(i.get("sha256") for i in r["inputs"])


def test_historical_stress_is_recomputed_independently_from_the_raw_csv_and_lists_hashed_datasets():
    cid, aid = setup_client()
    r = provenance.explain(cid, "stress_loss", aid, scenario="crash_2008")
    assert r["independent_recomputation"] is True and r["matches"] is True
    files = {d["file"]: d for d in r["datasets"]}
    assert set(files) == {"returns_annual.csv", "shiller_monthly.csv"}
    for name, d in files.items():
        assert d["sha256"] == hashlib.sha256(open(os.path.join(REAL, name), "rb").read()).hexdigest() and d["license"]
    assert any("Real 2008 market returns" in str(i["value"]) for i in r["inputs"])


def test_hypothetical_scenarios_are_labelled_and_have_no_dataset():
    cid, aid = setup_client()
    r = provenance.explain(cid, "stress_loss", aid, scenario="equity_-20")
    assert r["datasets"] == [] and r["independent_recomputation"] is False and "hypothetical" in r["formula"]


def test_goal_probability_documents_its_method_and_the_shock():
    cid, aid = setup_client()
    r = provenance.explain(cid, "goal_probability", aid, shock_pct=-20.0)
    names = {i["name"]: i for i in r["inputs"]}
    assert "5,000 lognormal paths, seed 42" in names["Method"]["value"] and "after a -20.0% shock" in names["Start amount"]["source"]


def test_ledger_total_counts_only_bought_items():
    cid, _ = setup_client()
    ledger.add_entry(cid, "Coat", 1000, "shopping", "bought")
    ledger.add_entry(cid, "Laptop", 6000, "shopping", "planned")
    ledger.add_entry(cid, "Tablet", 3000, "shopping", "cancelled")
    r = provenance.explain(cid, "ledger_total")
    assert r["value"] == 1000 and [i["name"] for i in r["inputs"]] == ["Coat"] and r["matches"]


def test_capacity_explanation_includes_the_behaviour_penalty():
    cid = redteam._probe("persona_chen")[0]
    ledger.load_sample(cid, "heavy")
    service.sync_profile_with_behaviour(cid)
    from app.agent.tools import Ctx
    from app.security import tiers
    tiers.execute("compute_risk_profile", {}, Ctx(cid))
    r = provenance.explain(cid, "capacity")
    assert any(i["name"] == "Behaviour penalty" and i["value"] == -10 for i in r["inputs"]) and r["matches"]


def test_a_wrong_displayed_number_is_caught_by_the_recomputation():
    cid, _ = setup_client()
    d = store.load_client(cid)
    d["profile"]["risk_capacity_score"] = 99.0
    store.save_client(cid, d)
    r = provenance.explain(cid, "capacity")
    assert r["matches"] is False and r["value"] == 99.0 and r["recomputed"] != 99.0


def test_errors_are_explicit():
    cid, aid = setup_client()
    assert provenance.explain(cid, "nope")["ok"] is False and provenance.explain("x", "bucket")["ok"] is False
    fresh = c.post("/api/session", json={"persona_id": "persona_li"}).json()["client_id"]
    assert provenance.explain(fresh, "bucket")["ok"] is False
    assert provenance.explain(cid, "stress_loss", aid, scenario="mars")["ok"] is False


def test_another_clients_allocation_cannot_be_explained():
    cid, _ = setup_client()
    other, other_aid = setup_client("persona_chen")
    assert provenance.explain(cid, "expected_return", other_aid)["ok"] is False


def test_api_returns_the_explanation_and_audits_it():
    cid, aid = setup_client()
    r = c.get("/api/provenance", params={"client_id": cid, "kind": "stress_loss", "allocation_id": aid, "scenario": "rate_+2"})
    assert r.status_code == 200 and r.json()["matches"] is True
    e = [x for x in c.get("/api/audit", params={"client_id": cid}).json() if x["action"] == "provenance_viewed"]
    assert e and e[-1]["tier"] == "T0" and c.get("/api/audit/verify").json()["valid"]


@pytest.mark.parametrize("params,code", [
    ({"client_id": "nope", "kind": "bucket"}, 404), ({"kind": "bucket"}, 422), ({"client_id": "x"}, 422),
])
def test_api_validation(params, code):
    assert c.get("/api/provenance", params=params).status_code == code


def test_api_error_codes():
    cid, aid = setup_client()
    assert c.get("/api/provenance", params={"client_id": cid, "kind": "nope"}).status_code == 422
    assert c.get("/api/provenance", params={"client_id": cid, "kind": "stress_loss", "allocation_id": aid, "scenario": "mars"}).status_code == 422
    assert c.get("/api/provenance", params={"client_id": cid, "kind": "goal_probability", "allocation_id": aid, "shock_pct": 500}).status_code == 422
    fresh = c.post("/api/session", json={"persona_id": "persona_li"}).json()["client_id"]
    assert c.get("/api/provenance", params={"client_id": fresh, "kind": "bucket"}).status_code == 409


def test_ui_makes_numbers_clickable():
    js, html = c.get("/static/app.js").text, c.get("/").text
    assert "provShow" in js and 'class="prov"' in js and 'id="provBox"' in html and 'id="provRow"' in html
    for kind in ("tolerance", "capacity", "bucket", "expected_return", "volatility", "stress_loss", "goal_probability", "backtest_share", "ledger_total"):
        assert f'"{kind}"' in js
    assert "这个数字是怎么算的？" in c.get("/static/i18n.js").text
