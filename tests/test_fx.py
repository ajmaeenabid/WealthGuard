"""Exchange rates: real-source provenance, caching, cross-checking, staleness, decimal-safe conversion, and never inventing a rate."""
from decimal import Decimal

import pytest

from app import store
from app.finance import fx, money


def test_usd_pivot_gives_the_cross_rates(fx_live):
    r = fx.rate("BDT", "CNY")
    expected = Decimal("6.69274") / Decimal("123.400189")
    assert abs(Decimal(r["rate"]) - expected) < Decimal("1e-9")
    assert r["source"] == "er-api" and r["provider_date"] == "2026-10-19" and not r["stale"]
    assert fx.rate("USD", "USD")["rate"] == "1"
    back = Decimal(fx.rate("CNY", "BDT")["rate"]) * Decimal(r["rate"])
    assert abs(back - 1) < Decimal("1e-8")


def test_ten_taka_is_about_fifty_four_fen_not_ten_yuan(fx_live):
    out = fx.convert_amount("10", "BDT", "CNY")
    assert out["converted"] == "0.54" and out["amount"] == "10.00" and out["quote"]["source_name"].startswith("ExchangeRate-API")
    assert fx.convert_amount("100", "CNY", "BDT")["converted"] == "1843.79"
    assert fx.convert_amount("1", "USD", "BDT")["converted"] == "123.40"


def test_rounding_is_half_up_in_whole_minor_units(fx_live):
    minor, _ = fx.convert_minor(1, "USD", "CNY")
    assert minor == 7 and isinstance(minor, int)
    assert fx.convert_minor(500, "BDT", "BDT") == (500, None)


def test_rates_are_cached_in_the_database_and_reused(fx_live):
    fx.rate("BDT", "CNY")
    fx.rate("CNY", "BDT")
    fx.convert_amount("5", "USD", "CNY")
    assert fx_live["n"] == 1
    from app.finance import books
    row = books._one("SELECT * FROM fin_fx_rates")
    assert row["source"] == "er-api" and row["agree"] == 1 and "fawaz" in row["cross_check"]


def test_a_new_fetch_happens_when_the_cache_is_old(fx_live, monkeypatch):
    fx.rate("BDT", "CNY")
    monkeypatch.setenv("FX_CACHE_HOURS", "0")
    fx.rate("BDT", "CNY")
    assert fx_live["n"] == 2


def test_if_the_network_fails_a_recent_rate_is_used_and_flagged_stale(fx_live, monkeypatch):
    fx.rate("BDT", "CNY")
    monkeypatch.setenv("FX_CACHE_HOURS", "0")
    fx_live["data"] = None
    r = fx.rate("BDT", "CNY")
    assert r["stale"] is True and r["age_hours"] >= 0


def test_too_old_a_rate_is_never_used(fx_live, monkeypatch):
    fx.rate("BDT", "CNY")
    monkeypatch.setenv("FX_CACHE_HOURS", "0")
    monkeypatch.setenv("FX_MAX_STALE_HOURS", "0")
    fx_live["data"] = None
    with pytest.raises(fx.FxUnavailable):
        fx.rate("BDT", "CNY")


def test_with_no_rate_ever_fetched_there_is_no_conversion_and_no_invented_number(fx_live):
    fx_live["data"] = None
    with pytest.raises(fx.FxUnavailable):
        fx.convert_amount("10", "BDT", "CNY")


def test_sources_that_disagree_by_more_than_three_percent_refuse_conversion(fx_live):
    fx_live["data"][1]["rates"]["BDT"] = 140.0
    with pytest.raises(fx.FxError) as e:
        fx.rate("BDT", "CNY")
    assert e.value.kind == "disagree"


def test_one_provider_alone_is_enough(fx_live):
    fx_live["data"] = fx_live["data"][:1]
    assert fx.rate("USD", "CNY")["source"] == "er-api"


def test_unsupported_currency_and_switched_off(fx_live, monkeypatch):
    with pytest.raises(fx.FxError) as e:
        fx.rate("USD", "EUR")
    assert e.value.kind == "unsupported"
    monkeypatch.setenv("FX_PROVIDER", "off")
    with pytest.raises(fx.FxUnavailable):
        fx.refresh()


def test_summary_shows_provenance_and_never_a_fake_table(fx_live):
    s = fx.summary()
    assert s["available"] and s["per_usd"]["BDT"].startswith("123.4") and s["attribution"] and "Indicative" in s["note"]
    fx_live["data"] = None
    store._write("DELETE FROM fin_fx_rates", ())
    assert fx.summary()["available"] is False


def test_no_rate_in_the_source_code_is_hardcoded():
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "app" / "finance" / "fx.py").read_text(encoding="utf-8")
    assert not re.search(r"\b(123\.\d|6\.6\d)", src)
