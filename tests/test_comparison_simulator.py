import pytest

from app import allocation as al
from app import comparison, simulator
from tests.helpers import PRODUCTS, persona_profile


def test_why_not_is_specific_for_novayield():
    pr = persona_profile("persona_li")
    txt = comparison.why_not(PRODUCTS["P13"], pr, PRODUCTS)
    assert "R1" in txt and "R3" in txt and "NovaYield" in txt and "12%" in txt


def test_why_not_worse_profile():
    pr = persona_profile("persona_chen")
    a = al.build(pr, PRODUCTS)
    txt = comparison.why_not(PRODUCTS["P12"], pr, PRODUCTS, a)  # allowed (risk 5? Growth max 4) -> blocked
    assert "R1" in txt
    txt2 = comparison.why_not(PRODUCTS["P10"], pr, PRODUCTS, al.build(pr, PRODUCTS, exclude_ids=["P10"]))
    assert "better risk/fee" in txt2 or "diversification" in txt2


def test_compare_rows():
    out = comparison.compare(["P01", "P11", "ZZZ"], PRODUCTS)
    assert len(out["rows"]) == 2 and out["unknown_ids"] == ["ZZZ"]


def test_stress_equity_shock_arithmetic():
    pr = persona_profile("persona_chen")
    a = al.build(pr, PRODUCTS)
    r = simulator.stress(a, PRODUCTS, "equity_-20")
    expected = sum(l.weight * simulator.SCENARIOS["equity_-20"]["shocks"][PRODUCTS[l.product_id].asset_class]
                   for l in a.lines)
    assert r["loss_pct"] == pytest.approx(expected, abs=0.01)
    assert r["loss_pct"] < 0


def test_stress_unknown_scenario():
    a = al.build(persona_profile("persona_li"), PRODUCTS)
    with pytest.raises(ValueError):
        simulator.stress(a, PRODUCTS, "nope")


def test_goal_projection_deterministic_and_shock_lowers_probability():
    pr = persona_profile("persona_li")
    a = al.build(pr, PRODUCTS)
    g1, g2 = simulator.goal_projection(a, pr), simulator.goal_projection(a, pr)
    assert g1 == g2 and 0 <= g1["probability"] <= 1 and g1["paths"] == 5000
    g3 = simulator.goal_projection(a, pr, shock_pct=-20)
    assert g3["probability"] <= g1["probability"]
