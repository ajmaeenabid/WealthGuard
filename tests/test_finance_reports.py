"""Reports (deterministic sections + grounded AI explanation), CSV export/import."""
import json
from datetime import timedelta

import pytest

from app.finance import ai, analytics, books, exchange, money, planning, reports
from app.finance.ai import AIError, AIResult

U = "alice"
T = money.today()


def day(n):
    return (T - timedelta(days=n)).isoformat()


@pytest.fixture
def world():
    cash = books.create_account(U, "Cash", "cash", "5000", opening_date=day(200))
    bank = books.create_account(U, "Bank", "bank", "40000", opening_date=day(200))
    sav = books.create_account(U, "Savings", "savings", "0", opening_date=day(200))
    return cash, bank, sav


def exp(a, amount, cat="food", ago=1, **kw):
    return books.create_transaction(U, dict({"type": "expense", "account_id": a["id"], "amount": str(amount), "category": cat, "ts": day(ago)}, **kw))


def populate(world):
    cash, bank, sav = world
    for m in range(0, 4):
        books.create_transaction(U, {"type": "income", "account_id": bank["id"], "amount": "30000", "category": "salary", "ts": day(m * 30 + 2)})
        exp(cash, 2000, "food", m * 30 + 3, merchant="Shwapno", subcategory="groceries")
        exp(cash, 1500, "entertainment", m * 30 + 4, merchant="Cineplex")
        exp(cash, 1000, "transport", m * 30 + 5)
        books.create_transaction(U, {"type": "transfer", "account_id": bank["id"], "to_account_id": sav["id"], "amount": "3000", "ts": day(m * 30 + 6)})
    for i in range(10):
        exp(cash, 60, "food", i + 1, merchant="Tea Stall")


def test_report_has_every_section_and_its_numbers_come_from_the_ledger(world):
    populate(world)
    planning.create_obligation(U, {"name": "Rent", "amount": "8000", "next_due": day(-5), "account_id": world[1]["id"], "category": "housing"})
    planning.create_goal(U, {"name": "Laptop", "target": "60000", "saved": "3000", "monthly_target": "5000", "target_date": day(-300)})
    r = reports.build(U, "month")
    assert set(r) >= {"overview", "spending", "savings", "obligations", "behaviour", "recommendations", "forecast", "scenario", "data_quality", "period"}
    s = analytics.summary(U, *analytics.period("month"))
    assert r["overview"]["income"] == s["income"] and r["overview"]["spending"] == s["spending"] and r["overview"]["net_cash_flow"] == s["net_cash_flow"]
    o = r["overview"]
    assert money.to_minor(o["closing_liquid"]) - money.to_minor(o["opening_liquid"]) == money.to_minor(o["change_in_liquid"])
    assert {a["name"] for a in o["accounts"]} == {"Cash", "Bank", "Savings"} and "opening balances you entered" in o["basis"]["actual"]
    assert r["savings"]["goals"][0]["name"] == "Laptop" and r["savings"]["planned_monthly_total"] == "5000.00"
    assert r["obligations"]["upcoming_total"] == "8000.00" and r["obligations"]["upcoming_30_days"][0]["name"] == "Rent"
    assert r["savings"]["definitions"]["actual"] and r["savings"]["definitions"]["implied"]


def test_all_period_kinds_and_custom_ranges_work_and_previous_period_comparison_is_included(world):
    populate(world)
    for kind in ("day", "week", "month", "year"):
        assert reports.build(U, kind)["period"]["start"] <= reports.build(U, kind)["period"]["end"]
    r = reports.build(U, "custom", start=day(60), end=day(0))
    assert r["period"]["days"] == 61 and r["spending"]["comparison"]["previous_period"]["end"] == day(61)
    with pytest.raises(books.FinanceError):
        reports.build(U, "custom", start=day(0), end=day(5))


def test_recommendations_carry_evidence_impact_and_assumptions_and_budgets_come_from_history(world):
    populate(world)
    r = reports.build(U, "month")
    acts = r["recommendations"]["actions"]
    assert acts and all(a["pattern"] and a["why"] and a["action"] and a["evidence"] for a in acts)
    sug = {s["category"]: s for s in r["recommendations"]["suggested_budgets"]}
    assert "entertainment" in sug and sug["entertainment"]["type"] == "flexible" and "minus 10%" in sug["entertainment"]["basis"]
    assert sug["transport"]["type"] == "essential" and "last" in sug["transport"]["basis"]
    planning.create_budget(U, {"category": "entertainment", "limit": "1500"})
    assert "entertainment" not in {s["category"] for s in reports.build(U, "month")["recommendations"]["suggested_budgets"]}
    assert r["scenario"]["is_estimate"] and r["scenario"]["scenario"]["reductions_pct"]


def test_data_gaps_are_stated_not_hidden():
    r = reports.build("nobody", "month")
    q = " ".join(r["data_quality"])
    assert "No accounts" in q and "No income" in q and "Very few transactions" in q
    assert r["overview"]["opening_liquid"] == "0.00" and r["recommendations"]["suggested_budgets"] == [] and r["forecast"]["is_estimate"]


def test_zero_opening_balance_is_called_out_as_possibly_wrong():
    books.create_account(U, "Bank", "bank", "0")
    assert any("opening balance of Bank is zero" in q for q in reports.build(U, "month")["data_quality"])


def good(**over):
    base = {"headline": "A steady month with room to save.", "summary": "You spent a little less than you earned.",
            "findings": [{"title": "Entertainment is your flexible lever", "what_we_saw": "Entertainment was 1,500 this month.", "why_it_matters": "It is optional spending.",
                          "suggested_action": "Set a monthly cap.", "estimated_impact": None, "assumptions": []}],
            "caveats": []}
    base.update(over)
    return base


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(ai, "enabled", lambda: True)
    seen = []

    def install(obj=None, error=None):
        def fake(messages, **kw):
            seen.append((messages, kw))
            if error:
                raise error
            return AIResult(content="{}", parsed=kw["validate"](obj), correlation_id="c9", usage={"prompt_tokens": 800, "completion_tokens": 300}, est_cost_usd=0.0001)
        monkeypatch.setattr(ai, "call", fake)
        return seen
    return install


def test_the_model_sees_only_computed_figures_and_the_schema_is_strict(world, live):
    populate(world)
    seen = live(good())
    r = reports.generate(U, "month")
    messages, kw = seen[0]
    payload = json.loads(messages[1]["content"])
    assert "transactions" not in payload and payload["overview"]["income"] == r["overview"]["income"] and "insights" in payload
    assert kw["schema"] is reports.EXPLAIN_SCHEMA and kw["purpose"] == "report_explain" and kw["prompt_version"] == "report-explain-v1"
    assert r["narrative"]["mode"] == "ai" and r["narrative"]["headline"].startswith("A steady month")
    assert reports.EXPLAIN_SCHEMA["properties"]["findings"]["items"]["additionalProperties"] is False


def test_invented_figures_are_removed_from_the_ai_explanation(world, live):
    populate(world)
    bad = good()
    bad["findings"].append({"title": "Made up", "what_we_saw": "You spent 987,654 on gadgets.", "why_it_matters": "x", "suggested_action": "y", "estimated_impact": None, "assumptions": []})
    live(bad)
    n = reports.generate(U, "month")["narrative"]
    assert [f["title"] for f in n["findings"]] == ["Entertainment is your flexible lever"] and any("removed" in c for c in n["caveats"])
    live(good(summary="Your savings hit 1,234,567 this month."))
    n = reports.generate(U, "month")["narrative"]
    assert "1,234,567" not in n["summary"] and "removed" in " ".join(n["caveats"])


def test_when_the_ai_is_down_the_report_is_still_complete_and_says_so(world, live):
    populate(world)
    live(error=AIError("rate_limited", "busy", retry_after=600))
    r = reports.generate(U, "month")
    n = r["narrative"]
    assert n["mode"] == "fallback" and n["findings"] and n["headline"] and any("without the AI service" in c for c in n["caveats"])
    assert r["overview"]["income"] != "0.00"


def test_offline_mode_uses_the_same_evidence(world):
    populate(world)
    n = reports.generate(U, "month")["narrative"]
    assert n["mode"] == "rules" and n["findings"][0]["what_we_saw"] and n["findings"][0]["suggested_action"]


def test_reports_are_stored_listed_isolated_and_exportable(world):
    populate(world)
    r = reports.generate(U, "month")
    assert reports.get(U, r["id"])["id"] == r["id"] and reports.list_reports(U)[0]["id"] == r["id"]
    with pytest.raises(books.FinanceError):
        reports.get("bob", r["id"])
    assert reports.list_reports("bob") == []
    md = reports.to_markdown(r)
    assert md.startswith("# Financial report:") and "Forecast (estimate)" in md and "Assumption:" in md


def test_export_then_import_round_trips_without_duplicates(world):
    cash, bank, sav = world
    exp(cash, 800, "food", 3, merchant="Shwapno", discount="50", note="weekly shop", tags=["home"])
    books.create_transaction(U, {"type": "transfer", "account_id": bank["id"], "to_account_id": sav["id"], "amount": "1000", "ts": day(2)})
    text = exchange.export_csv(U)
    assert text.splitlines()[0].startswith("date,type,amount") and "Shwapno" in text and "weekly shop" in text
    other = "carol"
    for n, t in (("Cash", "cash"), ("Bank", "bank"), ("Savings", "savings")):
        books.create_account(other, n, t, "0", opening_date=day(200))
    res = exchange.import_csv(other, text)
    assert res["created"] == 2 and res["errors"] == []
    again = exchange.import_csv(other, text)
    assert again["created"] == 0 and again["skipped_duplicates"] == 2
    got = books.list_transactions(other, type="expense")["items"][0]
    assert (got["merchant"], got["gross_amount"], got["discount"], got["final_amount"], got["source"], got["tags"]) == ("Shwapno", "850.00", "50.00", "800.00", "import", ["home"])


def test_import_reports_row_errors_and_rejects_bad_files(world):
    good_row = f"{day(1)},expense,100,,,,,food,,Shop,,Cash,,,,,,,BDT,"
    bad_row = f"{day(1)},expense,abc,,,,,food,,Shop,,Cash,,,,,,,BDT,"
    missing_acc = f"{day(1)},expense,100,,,,,food,,Shop,,Nowhere,,,,,,,BDT,"
    text = ",".join(exchange.COLUMNS) + "\n" + "\n".join([good_row, bad_row, missing_acc]) + "\n"
    res = exchange.import_csv(U, text)
    assert res["created"] == 1 and res["error_count"] == 2 and {e["row"] for e in res["errors"]} == {3, 4}
    with pytest.raises(books.FinanceError, match="columns"):
        exchange.import_csv(U, "a,b\n1,2\n")
    with pytest.raises(books.FinanceError, match="no rows"):
        exchange.import_csv(U, "date,type,amount\n")
    with pytest.raises(books.FinanceError, match="too large"):
        exchange.import_csv(U, "date,type,amount\n" + "x" * 1_100_000)


def test_export_neutralises_spreadsheet_formulas(world):
    cash = world[0]
    exp(cash, 10, "food", 1, merchant="=HYPERLINK(\"http://evil\")", note="+cmd|' /C calc'!A0")
    text = exchange.export_csv(U)
    assert "'=HYPERLINK" in text and "'+cmd" in text and ",=HYPERLINK" not in text


def test_a_month_where_spending_beat_income_still_produces_a_report_and_export(world):
    cash, bank, _ = world
    books.create_transaction(U, {"type": "income", "account_id": bank["id"], "amount": "1000", "category": "salary", "ts": day(2)})
    exp(cash, 4000, "shopping", 1, merchant="Daraz")
    r = reports.generate(U, "month")
    assert r["overview"]["net_cash_flow"] == "-3000.00" and r["narrative"]["headline"]
    assert "-৳3,000.00" in reports.to_markdown(r)
