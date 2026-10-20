from app import profiling as p
from tests.helpers import persona_profile


def full(**over):
    a = dict(age=40, horizon_years=10, goal="growth", monthly_income_cny=20000, experience="advanced",
             loss_reaction="buy_more", income_stability="stable", liquidity_need_pct=0)
    a.update(over)
    return a


def test_final_bucket_is_lower_of_tolerance_and_capacity():
    pr = p.build_profile("x", full(age=70, horizon_years=3, income_stability="unstable", liquidity_need_pct=40,
                                   monthly_income_cny=3000))
    assert pr.risk_tolerance_score > pr.risk_capacity_score
    assert pr.bucket == p.score_to_bucket(pr.risk_capacity_score)
    pr2 = p.build_profile("y", full(goal="preservation", loss_reaction="sell_all", experience="none"))
    assert pr2.risk_capacity_score > pr2.risk_tolerance_score
    assert pr2.bucket == p.score_to_bucket(pr2.risk_tolerance_score)


def test_adaptive_skipping_known_answers():
    q = p.next_question({"age": 40, "horizon_years": 5})
    assert q["id"] not in ("age", "horizon_years")
    assert p.next_question(full()) is None


def test_adaptive_inference():
    assert "liquidity_need_pct" in p.infer({"horizon_years": 1})["_inferred"]
    assert "loss_reaction" in p.infer({"goal": "preservation"})["_inferred"]
    ids = [p.next_question({"horizon_years": 1})["id"]]
    assert "liquidity_need_pct" not in ids
    assert "liquidity_need_pct" in p.missing({"horizon_years": 5})


def test_missing_answers_rejected():
    import pytest
    with pytest.raises(ValueError):
        p.build_profile("x", {"age": 30})


def test_parse_answer():
    assert p.parse_answer("loss_reaction", "hold") == "hold"
    assert p.parse_answer("loss_reaction", "Sell some") == "sell_some"
    assert p.parse_answer("age", "I am 45 years old") == 45
    assert p.parse_answer("loss_reaction", "banana") is None


def test_personas_buckets():
    assert persona_profile("persona_li").bucket == "Moderate"
    assert persona_profile("persona_chen").bucket == "Growth"
    assert persona_profile("persona_wang").bucket == "Balanced"
