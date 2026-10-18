"""R9 plain language (CSRC Suitability Measures Art. 24): pass and fail cases in English and Chinese."""
import pytest

from app import allocation as al
from app import compliance as cp
from app import knowledge
from tests.helpers import PRODUCTS, persona_profile


def good(pid="persona_li"):
    pr = persona_profile(pid)
    return pr, al.build(pr, PRODUCTS)


def r9(a, pr):
    return {c.rule_id: c for c in cp.check(a, pr, PRODUCTS, use_llm=False).checks}["R9"]


def with_text(a, summary=None, text=None):
    b = a.model_copy(deep=True)
    if summary is not None:
        b.summary = summary
    if text is not None:
        b.client_text = text
    return b


@pytest.mark.parametrize("persona", ["persona_li", "persona_chen", "persona_wang"])
def test_generated_advice_is_plain_for_every_persona(persona):
    pr, a = good(persona)
    assert r9(a, pr).passed
    assert cp.flesch_reading_ease(a.client_text) >= cp.MIN_FLESCH


def test_r9_is_part_of_every_check_and_can_block_the_allocation():
    pr, a = good()
    res = cp.check(a, pr, PRODUCTS, use_llm=False)
    assert "R9" in [c.rule_id for c in res.checks] and res.passed
    bad = with_text(a, summary="This allocation targets alpha through convexity.")
    res = cp.check(bad, pr, PRODUCTS, use_llm=False)
    assert not res.passed and [c.rule_id for c in res.checks if not c.passed] == ["R9"]


def test_very_long_sentence_fails():
    pr, a = good()
    long_s = " ".join(["The portfolio holds a mix of bonds and cash"] * 7) + "."
    c = r9(with_text(a, summary=long_s), pr)
    assert not c.passed and "too long" in c.detail and "words" in c.detail


def test_unexplained_jargon_fails_but_an_explanation_in_brackets_passes():
    pr, a = good()
    assert not r9(with_text(a, summary="The fund aims for alpha over time."), pr).passed
    assert not r9(with_text(a, summary="Its Sharpe ratio is high."), pr).passed
    assert r9(with_text(a, summary="The fund aims for alpha (the return above the market) over time."), pr).passed
    assert "unexplained jargon: alpha" in r9(with_text(a, summary="Alpha is the goal."), pr).detail


def test_dense_text_fails_the_flesch_score():
    pr, a = good()
    dense = ("Notwithstanding diversification characteristics, institutional counterparties' creditworthiness "
             "deterioration necessitates comprehensive reconsideration regarding portfolio rebalancing methodologies. "
             "Simultaneously, macroeconomic uncertainties substantially complicate expectation formulation, "
             "particularly concerning intermediate-maturity instruments' sensitivities. "
             "Consequently, administrators' supplementary documentation requirements considerably intensify "
             "operational responsibilities throughout implementation. Furthermore, interdependencies necessitate reconsideration.")
    assert cp.flesch_reading_ease(dense) < cp.MIN_FLESCH
    c = r9(with_text(a, text=dense), pr)
    assert not c.passed and "Flesch" in c.detail


def test_flesch_orders_simple_above_dense():
    simple = "You pay a small fee. The fund holds bonds. It can lose value. Past results do not repeat."
    assert cp.flesch_reading_ease(simple) > 70 > 20 > cp.flesch_reading_ease(
        "Notwithstanding administrative considerations, counterparties' creditworthiness necessitates reconsideration.")


def test_chinese_short_sentences_pass_and_long_or_jargon_fail():
    pr, a = good()
    ok = "您的资金主要放在债券和现金里。费用较低。投资有风险，可能亏损本金。过往业绩不代表未来表现。"
    assert r9(with_text(a, summary=ok, text=ok), pr).passed
    long_zh = "您的投资组合包含" + "债券基金和货币基金以及黄金产品" * 12 + "。"
    assert not r9(with_text(a, summary=long_zh), pr).passed
    assert not r9(with_text(a, summary="该产品的久期较长，夏普比率较高。"), pr).passed
    assert r9(with_text(a, summary="该产品的久期（对利率变化的敏感度）较长。费用较低。"), pr).passed


def test_r9_has_a_regulatory_basis_in_article_24():
    assert knowledge.basis_for_rule("R9")["article_no"] == 24


def test_ui_names_r9():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert 'R9: "Plain language"' in c.get("/static/app.js").text and 'R9: "通俗易懂"' in c.get("/static/i18n.js").text
