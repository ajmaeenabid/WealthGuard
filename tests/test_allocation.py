import pytest

from app import allocation as al
from app.config import BUCKETS, EQUITY_LIKE
from tests.helpers import PRODUCTS, make_profile, persona_profile


@pytest.mark.parametrize("bucket", list(BUCKETS))
def test_weights_sum_and_caps_for_every_bucket(bucket):
    pr = make_profile(bucket=bucket, experience="advanced", age=40, horizon_years=10)
    a = al.build(pr, PRODUCTS)
    lim = BUCKETS[bucket]
    assert sum(l.weight for l in a.lines) == pytest.approx(1.0, abs=1e-6)
    for l in a.lines:
        pd = PRODUCTS[l.product_id]
        assert pd.risk_level <= lim["max_risk"]
        assert l.weight <= lim["max_single_pct"] / 100 + 1e-6
        assert l.rationale
    eq = sum(l.weight for l in a.lines if PRODUCTS[l.product_id].asset_class in EQUITY_LIKE)
    assert eq <= lim["max_equity_pct"] / 100 + 1e-6


def test_deterministic():
    pr = persona_profile("persona_li")
    a, b = al.build(pr, PRODUCTS), al.build(pr, PRODUCTS)
    assert [(l.product_id, l.weight) for l in a.lines] == [(l.product_id, l.weight) for l in b.lines]


def test_basic_experience_excludes_complex():
    a = al.build(persona_profile("persona_li"), PRODUCTS)
    assert not any(PRODUCTS[l.product_id].complex for l in a.lines)


def test_vulnerable_client_capped_at_moderate():
    pr = persona_profile("persona_wang")
    assert pr.bucket == "Balanced"
    a = al.build(pr, PRODUCTS)
    assert all(PRODUCTS[l.product_id].risk_level <= 3 for l in a.lines)
    assert "vulnerable" in a.summary


def test_liquidity_floor():
    pr = make_profile(bucket="Moderate", liquidity_need_pct=95, horizon_years=10)
    a = al.build(pr, PRODUCTS)
    liquid = sum(l.weight for l in a.lines if PRODUCTS[l.product_id].lockup_days == 0)
    assert liquid >= 0.95 - 1e-3


def test_preferred_injected_and_excludable():
    pr = persona_profile("persona_li")
    a = al.build(pr, PRODUCTS, preferred_ids=["P13"])
    assert any(l.product_id == "P13" for l in a.lines)
    b = al.build(pr, PRODUCTS, preferred_ids=["P13"], exclude_ids=["P13"])
    assert not any(l.product_id == "P13" for l in b.lines)


def test_client_text_has_disclosures():
    a = al.build(persona_profile("persona_li"), PRODUCTS)
    t = a.client_text.lower()
    assert "can lose" in t and "annual fees" in t and "past performance" in t
    assert "not real financial advice" in t
