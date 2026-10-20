import pytest

from app import allocation as al
from app import compliance as cp
from app.schemas import AllocationLine
from tests.helpers import PRODUCTS, make_profile, persona_profile


def good(pid="persona_li"):
    pr = persona_profile(pid)
    return pr, al.build(pr, PRODUCTS)


def run(a, pr, rule):
    return {c.rule_id: c for c in cp.check(a, pr, PRODUCTS, use_llm=False).checks}[rule]


def with_lines(a, pairs):
    b = a.model_copy(deep=True)
    b.lines = [AllocationLine(product_id=p, weight=w, rationale="test rationale") for p, w in pairs]
    b.client_text = al.make_client_text(b.summary, b.lines, PRODUCTS)
    return b


def test_clean_allocation_passes_everything():
    pr, a = good()
    res = cp.check(a, pr, PRODUCTS)
    assert res.passed and {c.rule_id for c in res.checks} >= {f"R{i}" for i in range(1, 9)}
    assert len(res.required_disclosures) == 3


def test_r1_fail_and_pass():
    pr, a = good()
    assert run(a, pr, "R1").passed
    bad = with_lines(a, [("P12", 0.2), ("P03", 0.4), ("P01", 0.4)])
    assert not run(bad, pr, "R1").passed


def test_r1_equity_limit():
    pr = make_profile(bucket="Moderate")
    a = al.build(pr, PRODUCTS)
    bad = with_lines(a, [("P08", 0.35), ("P03", 0.35), ("P01", 0.3)])
    assert not run(bad, pr, "R1").passed


def test_r2_fail_and_pass():
    pr, a = good()
    assert run(a, pr, "R2").passed
    bad = with_lines(a, [("P03", 0.6), ("P01", 0.4)])
    assert not run(bad, pr, "R2").passed
    assert not run(with_lines(a, [("P03", 0.3), ("P01", 0.3)]), pr, "R2").passed


def test_r3_fail_and_pass():
    pr = make_profile(bucket="Aggressive", experience="basic")
    a = al.build(pr, PRODUCTS)
    assert run(a, pr, "R3").passed
    bad = with_lines(a, [("P13", 0.3), ("P03", 0.35), ("P01", 0.35)])
    assert not run(bad, pr, "R3").passed
    adv = make_profile(bucket="Aggressive", experience="advanced")
    assert run(bad, adv, "R3").passed


def test_r4_fail_and_pass():
    pr, a = good()
    assert run(a, pr, "R4").passed
    short = make_profile(bucket="Aggressive", horizon_years=2, experience="advanced")
    bad = with_lines(a, [("P13", 0.15), ("P03", 0.45), ("P01", 0.4)])
    assert not run(bad, short, "R4").passed
    locked = with_lines(a, [("P05", 0.35), ("P06", 0.35), ("P01", 0.3)])
    assert not run(locked, make_profile(bucket="Moderate", liquidity_need_pct=70), "R4").passed


def test_r5_fail_and_pass():
    pr = persona_profile("persona_wang")
    a = al.build(pr, PRODUCTS)
    assert run(a, pr, "R5").passed
    bad = with_lines(a, [("P09", 0.3), ("P08", 0.3), ("P03", 0.2), ("P01", 0.2)])
    assert not run(bad, pr, "R5").passed
    assert run(bad, make_profile(bucket="Balanced", age=40), "R5").passed


def test_r5_short_horizon():
    pr = make_profile(bucket="Growth", horizon_years=1, age=40, experience="advanced")
    bad = with_lines(al.build(pr, PRODUCTS), [("P11", 0.3), ("P10", 0.3), ("P03", 0.2), ("P01", 0.2)])
    assert not run(bad, pr, "R5").passed


def test_r6_fail_and_pass():
    pr, a = good()
    assert run(a, pr, "R6").passed
    b = a.model_copy()
    b.client_text = "Here is your allocation."
    assert not run(b, pr, "R6").passed
    b.client_text = a.client_text.replace("Past performance", "Previous results")
    assert not run(b, pr, "R6").passed


@pytest.mark.parametrize("phrase", ["This fund is guaranteed to grow", "completely risk-free", "you can't lose",
                                    "returns are guaranteed", "no risk at all", "100% safe"])
def test_r7_fail(phrase):
    pr, a = good()
    b = a.model_copy(deep=True)
    b.lines[0].rationale = phrase
    assert not run(b, pr, "R7").passed


def test_r7_pass_and_negated_guarantee_allowed():
    pr, a = good()
    assert run(a, pr, "R7").passed
    b = a.model_copy(deep=True)
    b.summary = "Returns are not guaranteed."
    assert run(b, pr, "R7").passed


def test_r8_fail_and_pass():
    pr, a = good()
    assert run(a, pr, "R8").passed
    poor = make_profile(bucket="Aggressive", experience="advanced", investable_amount_cny=60000)
    bad = with_lines(a, [("P13", 0.15), ("P03", 0.85)])
    assert not run(bad, poor, "R8").passed


def test_unknown_product_fails_r1():
    pr, a = good()
    bad = a.model_copy(deep=True)
    bad.lines[0].product_id = "P99"
    assert not run(bad, pr, "R1").passed


def test_llm_reviewer_can_only_tighten():
    pr, a = good()
    b = a.model_copy(deep=True)
    b.client_text += " Act now!! Limited time."
    res = cp.check(b, pr, PRODUCTS)
    assert not res.passed and not [c for c in res.checks if c.rule_id == "LLM"][0].passed
    bad = with_lines(a, [("P12", 0.2), ("P03", 0.4), ("P01", 0.4)])
    assert not cp.check(bad, pr, PRODUCTS).passed


def test_violating_products():
    pr, a = good()
    bad = with_lines(a, [("P13", 0.15), ("P03", 0.45), ("P01", 0.4)])
    assert cp.violating_products(bad, pr, PRODUCTS) == ["P13"]
