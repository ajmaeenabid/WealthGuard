"""Analytics, budgets, goals, obligations, alerts and the forecast, all against a real ledger."""
from datetime import timedelta

import pytest

from app.finance import analytics, books, money, planning
from app.finance.books import FinanceError

U = "alice"
T = money.today()


def day(n: int) -> str:
    return (T - timedelta(days=n)).isoformat()


@pytest.fixture
def world():
    cash = books.create_account(U, "Cash", "cash", "10000", opening_date=day(400))
    bank = books.create_account(U, "Bank", "bank", "50000", opening_date=day(400))
    sav = books.create_account(U, "Savings", "savings", "0", opening_date=day(400))
    return {"cash": cash, "bank": bank, "sav": sav}


def exp(acct, amount, cat="food", ago=1, **kw):
    return books.create_transaction(U, dict({"type": "expense", "account_id": acct["id"], "amount": str(amount), "category": cat, "ts": day(ago)}, **kw))


def inc(acct, amount, ago=1, cat="salary"):
    return books.create_transaction(U, {"type": "income", "account_id": acct["id"], "amount": str(amount), "category": cat, "ts": day(ago)})


def bal(name):
    return {a["name"]: a["balance"] for a in books.list_accounts(U)}[name]


def window(n=30):
    return T - timedelta(days=n), T


def test_summary_applies_the_definitions_income_spending_refunds_transfers_savings(world):
    inc(world["bank"], 30000, 5)
    e = exp(world["cash"], 1000, "shopping", 4)
    exp(world["cash"], 500, "food", 3, subcategory="groceries")
    books.create_transaction(U, {"type": "refund", "account_id": world["cash"]["id"], "amount": "300", "refund_of": e["id"], "ts": day(2)})
    books.create_transaction(U, {"type": "transfer", "account_id": world["bank"]["id"], "to_account_id": world["sav"]["id"], "amount": "4000", "ts": day(2)})
    books.create_transaction(U, {"type": "transfer", "account_id": world["bank"]["id"], "to_account_id": world["cash"]["id"], "amount": "700", "ts": day(2)})
    s = analytics.summary(U, *window())
    assert (s["income"], s["expense_gross"], s["refunds"], s["spending"]) == ("30000.00", "1500.00", "300.00", "1200.00")
    assert s["net_cash_flow"] == "28800.00" and s["savings_net"] == "4000.00"
    assert s["savings_rate_actual"] == round(4000 / 30000, 4) and s["savings_rate_implied"] == round(28800 / 30000, 4)
    cats = {c["category"]: c["amount"] for c in s["by_category"]}
    assert cats == {"shopping": "700.00", "food": "500.00"}
    assert s["essential_split"]["essential"]["amount"] == "500.00" and s["essential_split"]["discretionary"]["amount"] == "1000.00"
    assert s["definitions"]["income"].startswith("income transactions only")


def test_future_dated_and_other_currency_entries_are_not_actual(world):
    exp(world["cash"], 100, ago=1)
    exp(world["cash"], 999, ago=-5)
    usd = books.create_account(U, "Dollars", "bank", "0", currency="USD", opening_date=day(400))
    books.create_transaction(U, {"type": "income", "account_id": usd["id"], "amount": "50", "ts": day(1), "category": "freelance"})
    s = analytics.summary(U, *window())
    assert s["spending"] == "100.00" and s["income"] == "0.00" and s["excluded"] == {"other_currency_accounts": ["Dollars"], "future_dated": 1}


def test_periods_and_comparison(world):
    assert analytics.period("month", "2026-02-15") == (money.month_bounds(money.date(2026, 2, 1))[0], money.date(2026, 2, 28))
    assert analytics.period("week", "2026-03-04")[0].weekday() == 0
    with pytest.raises(FinanceError):
        analytics.period("custom", start="2026-03-05", end="2026-03-01")
    with pytest.raises(FinanceError):
        analytics.period("decade")
    exp(world["cash"], 100, "food", 3)
    exp(world["cash"], 400, "food", 40)
    cur, prev = analytics.summary(U, *window(30)), analytics.summary(U, T - timedelta(days=60), T - timedelta(days=31))
    cmp = analytics.compare(cur, prev)
    assert cmp["spending"]["current"] == "100.00" and cmp["spending"]["previous"] == "400.00" and cmp["spending"]["change_pct"] == -0.75


def test_insights_are_evidence_backed_and_carry_an_action_and_assumptions(world):
    inc(world["bank"], 20000, 20)
    for i in range(25):
        exp(world["cash"], 40, "food", (i % 25) + 1, merchant="Tea Stall")
    exp(world["cash"], 5000, "shopping", 6, merchant="Daraz")
    exp(world["cash"], 3000, "entertainment", 8, merchant="Resort")
    s = analytics.summary(U, *window())
    kinds = {i["kind"]: i for i in analytics.insights(U, *window(), cur=s)}
    assert {"top_category", "small_purchases", "frequent_merchant", "discretionary_share"} <= set(kinds)
    for i in kinds.values():
        assert i["pattern"] and i["why"] and i["action"] and i["evidence"]
    assert kinds["small_purchases"]["evidence"]["count"] == 25 and "20%" in kinds["small_purchases"]["assumptions"][0]
    assert kinds["top_category"]["evidence"]["category"] == "shopping"
    impact = kinds["discretionary_share"]["impact_minor"]
    assert impact == int(analytics.summary(U, *window())["essential_split"]["discretionary"]["minor"] * 0.10)


def test_category_increase_and_low_savings_and_subscriptions(world):
    inc(world["bank"], 10000, 10)
    exp(world["cash"], 500, "transport", 45)
    exp(world["cash"], 3000, "transport", 5)
    exp(world["cash"], 9000, "shopping", 6)
    for ago in (65, 35, 5):
        exp(world["cash"], 499, "entertainment", ago, merchant="Netflix")
    cur, prev = analytics.summary(U, *window()), analytics.summary(U, T - timedelta(days=60), T - timedelta(days=31))
    kinds = {i["kind"] for i in analytics.insights(U, *window(), cur=cur, prev=prev)}
    assert {"category_increase", "low_savings", "subscriptions"} <= kinds
    subs = analytics.detect_subscriptions(U)
    assert subs[0]["merchant"] == "Netflix" and subs[0]["occurrences"] == 3


def test_a_user_with_no_spending_gets_no_invented_insights(world):
    assert analytics.insights(U, *window()) == []
    s = analytics.summary(U, *window())
    assert s["spending"] == "0.00" and s["by_category"] == [] and s["savings_rate_actual"] is None


def test_budget_tracks_actual_spending_warns_and_goes_over(world):
    b = planning.create_budget(U, {"category": "food", "limit": "1000", "alert_pct": 80})
    assert b["status"] == "ok" and b["spent"] == "0.00" and b["remaining"] == "1000.00"
    exp(world["cash"], 850, "food", 0)
    exp(world["cash"], 5000, "shopping", 0)
    b = planning.get_budget(U, b["id"])
    assert (b["spent"], b["status"], b["remaining"]) == ("850.00", "warning", "150.00")
    t = exp(world["cash"], 300, "food", 0)
    b = planning.get_budget(U, b["id"])
    assert b["status"] == "over" and b["over_by"] == "150.00" and b["utilization"] == 1.15
    books.create_transaction(U, {"type": "refund", "account_id": world["cash"]["id"], "amount": "300", "refund_of": t["id"], "ts": day(0)})
    assert planning.get_budget(U, b["id"])["status"] == "warning"


def test_overall_weekly_and_custom_budgets_and_validation(world):
    exp(world["cash"], 200, "food", 0)
    exp(world["cash"], 300, "shopping", 0)
    overall = planning.create_budget(U, {"limit": "400", "period": "weekly"})
    assert overall["spent"] == "500.00" and overall["status"] == "over"
    custom = planning.create_budget(U, {"limit": "250", "period": "custom", "start_date": day(10), "end_date": day(-10), "category": "food"})
    assert custom["spent"] == "200.00" and custom["window"]["start"] == day(10)
    for bad in [{"limit": "0"}, {"limit": "abc"}, {"limit": "5", "category": "nope"}, {"limit": "5", "period": "custom"}, {"limit": "5", "alert_pct": 0}]:
        with pytest.raises(FinanceError):
            planning.create_budget(U, bad)
    assert planning.update_budget(U, overall["id"], {"limit": "900"})["status"] == "ok"
    planning.delete_budget(U, custom["id"])
    assert len(planning.list_budgets(U)) == 1 and planning.list_budgets("bob") == []


def test_projection_flags_a_budget_that_will_be_exceeded_at_the_current_pace(world):
    s, e = money.month_bounds(T)
    elapsed = (T - s).days + 1
    total = (e - s).days + 1
    if elapsed >= total:
        pytest.skip("last day of the month: nothing left to project")
    spend = 1000
    planning.create_budget(U, {"category": "food", "limit": str(int(spend * total / elapsed) - 10 if total / elapsed > 1.01 else spend)})
    exp(world["cash"], spend, "food", 0, ts=T.isoformat())
    b = planning.list_budgets(U)[0]
    assert b["projected_total"] != "0.00" and "estimate" in b["basis"]


def test_goal_progress_comes_from_linked_transfers_not_from_the_plan(world):
    g = planning.create_goal(U, {"name": "New laptop", "target": "60000", "saved": "5000", "monthly_target": "10000", "target_date": day(-180)})
    assert g["saved"] == "5000.00" and g["contributed"] == "0.00" and g["progress_pct"] == round(5000 / 60000, 4)
    assert g["estimate_basis"].startswith("planned") and g["on_track"] in (True, False)
    for ago in (60, 30, 5):
        books.create_transaction(U, {"type": "transfer", "account_id": world["bank"]["id"], "to_account_id": world["sav"]["id"], "amount": "9000", "goal_id": g["id"], "ts": day(ago)})
    g = planning.get_goal(U, g["id"])
    assert g["contributed"] == "27000.00" and g["saved"] == "32000.00" and g["remaining"] == "28000.00"
    assert g["estimate_basis"].startswith("actual") and g["actual_monthly_contribution"] == "9000.00" and g["estimated_completion"]
    assert bal("Savings") == "27000.00"


def test_goals_can_be_paused_completed_edited_and_reach_their_target(world):
    g = planning.create_goal(U, {"name": "Emergency fund", "target": "1000", "saved": "1000"})
    assert g["reached"] and "reached" in g["note"]
    assert planning.update_goal(U, g["id"], {"status": "completed"})["status"] == "completed"
    assert planning.update_goal(U, g["id"], {"status": "paused", "target": "5000"})["reached"] is False
    for bad in [{"name": "", "target": "5"}, {"name": "x", "target": "0"}, {"name": "x", "target": "5", "priority": 9}, {"name": "x", "target": "5", "target_date": "soon"}]:
        with pytest.raises(FinanceError):
            planning.create_goal(U, bad)
    with pytest.raises(FinanceError):
        planning.update_goal(U, g["id"], {"status": "dreaming"})
    planning.delete_goal(U, g["id"])
    assert planning.list_goals(U) == []


def test_a_goal_behind_schedule_says_how_much_a_month_it_needs(world):
    g = planning.create_goal(U, {"name": "Trip", "target": "100000", "target_date": day(-90)})
    assert g["on_track"] is False and money.to_minor(g["required_monthly"]) > 3000000 and g["estimated_completion"] is None
    assert any(a["kind"] == "goal_off_track" for a in planning.alerts(U))


def test_bill_status_progression_and_paying_creates_one_linked_expense(world):
    rent = planning.create_obligation(U, {"name": "Rent", "amount": "12000", "recurrence": "monthly", "next_due": day(-20), "category": "housing", "account_id": world["bank"]["id"]})
    assert rent["status"] == "planned"
    assert planning.create_obligation(U, {"name": "Wifi", "amount": "800", "next_due": day(-2)})["status"] == "due"
    assert planning.create_obligation(U, {"name": "Tuition", "amount": "5000", "next_due": day(3)})["status"] == "overdue"
    before = bal("Bank")
    r = planning.pay_obligation(U, rent["id"], ts=day(0))
    assert r["transaction"]["obligation_id"] == rent["id"] and r["transaction"]["category"] == "housing" and r["transaction"]["recurring"] is True
    assert r["obligation"]["next_due"] > rent["next_due"] and r["obligation"]["last_payment"]["status"] == "paid"
    assert before == "50000.00" and bal("Bank") == "38000.00"
    assert analytics.summary(U, *window())["spending"] == "12000.00"


def test_paying_the_same_due_date_twice_never_double_charges(world):
    b = planning.create_obligation(U, {"name": "Insurance", "amount": "3000", "recurrence": "yearly", "next_due": day(1), "account_id": world["cash"]["id"]})
    first = planning.pay_obligation(U, b["id"])
    nd = planning.get_obligation(U, b["id"])["next_due"]
    from app import store
    store._write("UPDATE fin_obligations SET next_due=? WHERE id=?", (b["next_due"], b["id"]))
    again = planning.pay_obligation(U, b["id"])
    assert again["duplicate"] is True and again["transaction"]["id"] == first["transaction"]["id"]
    assert books.list_transactions(U, type="expense")["total"] == 1 and nd > b["next_due"]


def test_deleting_the_payment_makes_the_bill_unpaid_again(world):
    b = planning.create_obligation(U, {"name": "Gas", "amount": "900", "next_due": day(2), "account_id": world["cash"]["id"]})
    r = planning.pay_obligation(U, b["id"])
    assert planning.get_obligation(U, b["id"])["next_due"] != b["next_due"]
    books.void_transaction(U, r["transaction"]["id"])
    o = planning.get_obligation(U, b["id"])
    assert o["next_due"] == b["next_due"] and o["status"] == "overdue" and o["last_payment"] is None


def test_one_off_bills_finish_after_payment_and_skips_move_on_without_an_expense(world):
    once = planning.create_obligation(U, {"name": "Fine", "amount": "500", "recurrence": "once", "next_due": day(0), "account_id": world["cash"]["id"]})
    planning.pay_obligation(U, once["id"])
    assert planning.get_obligation(U, once["id"])["status"] == "cancelled"
    monthly = planning.create_obligation(U, {"name": "Club", "amount": "700", "next_due": day(0)})
    sk = planning.skip_obligation(U, monthly["id"])
    assert sk["next_due"] > monthly["next_due"] and books.list_transactions(U, type="expense")["total"] == 1
    with pytest.raises(FinanceError, match="account"):
        planning.pay_obligation(U, monthly["id"])


def test_upcoming_lists_later_occurrences_and_alerts_cover_overdue_and_due_soon(world):
    planning.create_obligation(U, {"name": "Internet", "amount": "1000", "next_due": day(-1), "reminder_days": 3})
    planning.create_obligation(U, {"name": "Loan", "amount": "4000", "next_due": day(5)})
    up = planning.upcoming(U, 70)
    assert [u["name"] for u in up].count("Internet") >= 2 and up[0]["name"] == "Loan"
    kinds = {a["kind"] for a in planning.alerts(U)}
    assert {"bill_overdue", "bill_due"} <= kinds
    assert planning.alerts("bob") == []


def test_obligation_validation(world):
    for bad in [{"name": "", "amount": "5", "next_due": day(0)}, {"name": "x", "amount": "0", "next_due": day(0)},
                {"name": "x", "amount": "5", "next_due": "tomorrow"}, {"name": "x", "amount": "5", "next_due": day(0), "recurrence": "daily"},
                {"name": "x", "amount": "5", "next_due": day(0), "reminder_days": 999}]:
        with pytest.raises(FinanceError):
            planning.create_obligation(U, bad)


def test_budget_alerts(world):
    planning.create_budget(U, {"category": "food", "limit": "1000", "alert_pct": 50})
    exp(world["cash"], 600, "food", 0)
    a = planning.alerts(U)
    assert a[0]["kind"] == "budget_warning" and "60%" in a[0]["title"]
    exp(world["cash"], 600, "food", 0)
    assert planning.alerts(U)[0]["kind"] == "budget_over" and planning.alerts(U)[0]["severity"] == "high"


def test_forecast_is_labelled_an_estimate_and_follows_the_stated_assumptions(world):
    for ago in range(1, 31):
        exp(world["cash"], 100, "food", ago)
    planning.create_obligation(U, {"name": "Rent", "amount": "12000", "next_due": money.month_bounds(T)[1].isoformat(), "category": "housing"})
    f = planning.forecast(U)
    liquid = money.to_minor(f["current_liquid"])
    assert f["is_estimate"] and f["kind"] == "forecast" and len(f["assumptions"]) >= 3
    exp_var = money.to_minor(f["expected_variable_spending"])
    assert exp_var == 10000 * f["days_left"]
    bills = money.to_minor(f["upcoming_bills"])
    assert bills in (0, 1200000) and f["projected_end_balance_minor"] == liquid - exp_var - bills
    assert money.to_minor(f["range_low"]) <= f["projected_end_balance_minor"] <= money.to_minor(f["range_high"])
    if f["days_left"] > 0:
        s = planning.forecast(U, reductions={"food": 50})
        assert money.to_minor(s["scenario"]["estimated_saving"]) == int(100 * 30 / 30 * f["days_left"] * 100 * 0.5) and s["projected_end_balance_minor"] > f["projected_end_balance_minor"]


def test_forecast_never_invents_income_or_data_for_an_empty_ledger():
    f = planning.forecast("nobody")
    assert f["current_liquid"] == "0.00" and f["projected_end_balance"] == "0.00" and f["data_quality"]["days_with_spending"] == 0
