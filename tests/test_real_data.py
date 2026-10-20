"""Real-world datasets: provenance (hashes, licenses) and sanity of what was extracted."""
import csv
import hashlib
import json
import os

import pytest

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "data", "real")


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def rows(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def manifest():
    return json.load(open(os.path.join(ROOT, "MANIFEST.json"), encoding="utf-8"))


def test_manifest_hashes_match_every_raw_and_processed_file():
    m = manifest()
    assert len(m["datasets"]) == 4
    for d in m["datasets"]:
        assert sha(os.path.join(ROOT, d["file"])) == d["sha256"], d["file"]
        assert d["raw_files"]
        for rel, h in d["raw_files"].items():
            assert sha(os.path.join(ROOT, rel)) == h, rel


def test_every_dataset_declares_source_license_and_use():
    for d in manifest()["datasets"]:
        for k in ("title", "author", "url", "license", "used_for"):
            assert d.get(k), (d["file"], k)
        assert d["url"].startswith("https://")


def test_annual_returns_cover_1928_to_2025_with_known_values():
    r = rows("returns_annual.csv")
    years = [int(x["year"]) for x in r]
    assert years == list(range(1928, 2026))
    by = {int(x["year"]): x for x in r}
    assert float(by[2008]["sp500"]) == pytest.approx(-0.3655, abs=1e-3)
    assert float(by[1931]["sp500"]) == pytest.approx(-0.4384, abs=1e-3)
    assert float(by[2022]["tbond_10y"]) < -0.15
    assert float(by[1979]["gold"]) > 1.2
    for x in r:
        assert all(-0.8 < float(x[c]) < 1.5 for c in ("sp500", "tbill_3m", "tbond_10y", "baa_corp", "gold"))


def test_shiller_monthly_is_ordered_and_complete():
    r = rows("shiller_monthly.csv")
    months = [x["month"] for x in r]
    assert months[0] == "1871-01" and months == sorted(months) and len(set(months)) == len(months)
    assert all(float(x["cpi"]) > 0 and float(x["long_rate"]) > 0 for x in r)
    peak = max(r, key=lambda x: float(x["long_rate"]))
    assert peak["month"].startswith("198") and float(peak["long_rate"]) > 13


def test_china_macro_has_the_expected_columns_and_recent_years():
    r = rows("china_macro.csv")
    assert list(r[0].keys()) == ["year", "cpi_inflation_pct", "deposit_rate_pct", "lending_rate_pct", "gdp_growth_pct"]
    years = [int(x["year"]) for x in r]
    assert years[0] == 1985 and years[-1] >= 2024
    assert any(x["cpi_inflation_pct"] for x in r) and any(x["deposit_rate_pct"] for x in r)


def test_suitability_measures_are_the_full_43_articles_without_page_boilerplate():
    d = json.load(open(os.path.join(ROOT, "suitability_zh.json"), encoding="utf-8"))
    a = d["articles"]
    assert len(a) == 43 and a[0]["article"] == "第一条" and a[-1]["article"] == "第四十三条"
    assert "独立承担投资风险" in a[3]["text"]
    assert "不表明其对产品或者服务的风险和收益做出实质性判断或者保证" in a[3]["text"]
    blob = json.dumps(d, ensure_ascii=False)
    assert "京ICP备" not in blob and "中国政府网" not in blob


def test_rebuild_is_deterministic():
    pytest.importorskip("xlrd")
    import importlib.util
    before = {d["file"]: d["sha256"] for d in manifest()["datasets"]}
    spec = importlib.util.spec_from_file_location("build_real_data", os.path.join(os.path.dirname(ROOT), "..", "..", "scripts", "build_real_data.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()
    assert {d["file"]: d["sha256"] for d in manifest()["datasets"]} == before
