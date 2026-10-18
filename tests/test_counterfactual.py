"""Counterfactual compliance: what would have to be true for a blocked product to be allowed."""
import itertools

import pytest
from fastapi.testclient import TestClient

from app import allocation as al
from app import counterfactual, profiling, redteam, store
from app.agent.tools import Ctx
from app.compliance import banned_phrases
from app.main import app
from app.products import load_personas, load_products
from app.security import tiers

c = TestClient(app)
PRODUCTS = load_products()
PERSONAS = ["persona_li", "persona_chen", "persona_wang"]


def probe(persona="persona_li"):
    return redteam._probe(persona)[0]


def test_ms_li_and_novayield_is_impossible_with_a_specific_reason():
    r = counterfactual.explain(probe("persona_li"), "P13")
    assert not r["allowed_now"] and not r["reachable_by_answers"] and r["paths"] == []
    assert {x["rule"] for x in r["rules"] if not x["passed"]} == {"R1", "R3"}
    assert "most favourable truthful answers" in r["impossible_because"] and "Aggressive" in r["impossible_because"]
    assert r["max_reachable"]["bucket"] == "Growth" and r["combinations_checked"] == 720


def test_a_single_different_answer_can_be_enough():
    r = counterfactual.explain(probe("persona_li"), "P11")           # risk 4, needs the Growth bucket
    assert not r["allowed_now"] and r["reachable_by_answers"]
    ch = r["paths"][0]["changes"]
    assert [(x["fact"], x["to"]) for x in ch] == [("loss_reaction", "buy_more")] and r["paths"][0]["bucket"] == "Growth"


def test_allowed_products_need_no_change():
    r = counterfactual.explain(probe("persona_li"), "P01")
    assert r["allowed_now"] and r["paths"][0]["changes"] == []


def test_vulnerable_client_is_told_the_cap_cannot_be_changed_by_answers():
    r = counterfactual.explain(probe("persona_wang"), "P11")
    assert not r["reachable_by_answers"] and "vulnerable client" in r["impossible_because"]
    assert any(x["rule"] == "R5" and not x["passed"] for x in r["rules"])


def test_every_rule_row_cites_the_regulation_when_a_basis_exists():
    r = counterfactual.explain(probe("persona_li"), "P13")
    by = {x["rule"]: x for x in r["rules"]}
    assert by["R3"]["article"]["ref"] == "第十六条" and by["R1"]["article"]["ref"] == "第十八条"
    assert by["R3"]["needs"] == "advanced investing experience"


@pytest.mark.parametrize("persona", PERSONAS)
def test_every_returned_path_really_makes_the_product_eligible_in_the_real_engine(persona):
    cid = probe(persona)
    facts = dict(store.load_client(cid)["facts"])
    per = load_personas()[persona]
    for pid, p in PRODUCTS.items():
        r = counterfactual.explain(cid, pid)
        for path in r["paths"]:
            cand = {**facts, **{ch["fact"]: ch["to"] for ch in path["changes"]}}
            prof = profiling.build_profile("x", cand, per["name"], per)
            assert al.eligible(p, prof, al.limits_for(prof)[0]), (persona, pid, path)
            assert prof.bucket == path["bucket"]


@pytest.mark.parametrize("persona", PERSONAS)
def test_paths_are_minimal_and_never_touch_facts_that_cannot_change(persona):
    cid = probe(persona)
    facts = dict(store.load_client(cid)["facts"])
    names = [q for q in counterfactual.MUTABLE if q in facts]
    for pid in PRODUCTS:
        r = counterfactual.explain(cid, pid)
        if not r["paths"]:
            continue
        n = [len(p["changes"]) for p in r["paths"]]
        assert n == sorted(n)
        brute = []
        for combo in itertools.product(*[counterfactual._options(q) for q in names]):
            cand = {**facts, **dict(zip(names, combo))}
            if counterfactual._eligible(PRODUCTS[pid], cand, counterfactual._bucket(*counterfactual._scores(cand, 0.0))):
                brute.append(sum(1 for q, v in zip(names, combo) if v != facts[q]))
        assert n[0] == min(brute), (persona, pid)
        assert all(ch["fact"] in counterfactual.MUTABLE for p in r["paths"] for ch in p["changes"])


def test_explaining_never_changes_the_clients_profile_or_answers():
    cid = probe("persona_li")
    before = store.load_client(cid)
    counterfactual.explain(cid, "P13")
    assert store.load_client(cid) == before


def test_behaviour_penalty_is_part_of_the_current_capacity():
    cid = probe("persona_chen")
    d = store.load_client(cid)
    d.setdefault("extra", {})["behaviour_penalty_applied"] = 10
    store.save_client(cid, d)
    r = counterfactual.explain(cid, "P12")
    clean = counterfactual.explain(probe("persona_chen"), "P12")
    assert r["current"]["capacity"] == pytest.approx(clean["current"]["capacity"] - 10)


def test_the_note_says_this_is_not_advice_to_change_answers():
    r = counterfactual.explain(probe(), "P13")
    assert "not a suggestion to change your answers" in r["note"] and banned_phrases(r["note"]) == []


def test_errors_are_explicit():
    cid = c.post("/api/session", json={"persona_id": "persona_li"}).json()["client_id"]     # profile still incomplete
    assert "profile incomplete" in counterfactual.explain(cid, "P13")["error"]
    assert counterfactual.explain(probe(), "ZZ99")["ok"] is False and counterfactual.explain("nope", "P13")["ok"] is False


# ------------------------------------------------------------------------------------------ API, tool, chat, UI
def test_api_returns_the_explanation_and_audits_it_as_t1():
    cid = probe()
    r = c.get("/api/counterfactual", params={"client_id": cid, "product_id": "P13"})
    assert r.status_code == 200 and r.json()["product"]["name"] == "NovaYield Note"
    e = [x for x in c.get("/api/audit", params={"client_id": cid}).json() if x["action"] == "tool:explain_counterfactual"]
    assert e and e[-1]["tier"] == "T1" and c.get("/api/audit/verify").json()["valid"]


@pytest.mark.parametrize("params,code", [({"client_id": "nope", "product_id": "P13"}, 404), ({"product_id": "P13"}, 422),
                                         ({"client_id": "x"}, 422)])
def test_api_validation(params, code):
    assert c.get("/api/counterfactual", params=params).status_code == code


def test_api_unknown_product_404_and_incomplete_profile_409():
    cid = probe()
    assert c.get("/api/counterfactual", params={"client_id": cid, "product_id": "ZZ99"}).status_code == 404
    fresh = c.post("/api/session", json={"persona_id": "persona_li"}).json()["client_id"]
    assert c.get("/api/counterfactual", params={"client_id": fresh, "product_id": "P13"}).status_code == 409


def test_tool_rejects_extra_fields():
    out = tiers.execute("explain_counterfactual", {"product_id": "P13", "admin": True}, Ctx(probe()))
    assert out.get("refused") is True


def test_chat_explains_what_it_would_take_without_urging_changes():
    cid = c.post("/api/session", json={"persona_id": "persona_li"}).json()["client_id"]
    chat = lambda m: c.post("/api/chat", json={"client_id": cid, "message": m}).json()
    for m in ["hi", "Stable", "About 10%", "Sell some"]:
        chat(m)
    out = chat("What would it take for NovaYield to be allowed?")
    assert "NovaYield Note cannot be allowed for you" in out["reply"] and "not a suggestion to change your answers" in out["reply"]
    out = chat("what would need to change for P11?")
    assert "would have to be" in out["reply"] and any(t["tool"] == "explain_counterfactual" for t in out["trace"])


def test_ui_has_the_button_and_renderer():
    js = c.get("/static/app.js").text
    assert "cfShow" in js and "What would it take?" in js and "需要满足什么条件？" in c.get("/static/i18n.js").text
