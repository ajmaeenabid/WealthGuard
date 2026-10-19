"""Ledger rules: decimal-safe money, accounts and balances, transfers, refunds, idempotency, validation, filters."""
import sqlite3

import pytest

from app import db
from app.finance import books, money
from app.finance.books import FinanceError

U = "alice"


def acct(name="Cash", type="cash", opening="1000", **kw):
    return books.create_account(U, name, type, opening, **kw)


def spend(account, amount, **kw):
    return books.create_transaction(U, dict({"type": "expense", "account_id": account["id"], "amount": amount, "category": "food"}, **kw))


# ------------------------------------------------------------------------------------------ money
def test_money_is_exact_and_rejects_floats_and_junk():
    assert money.to_minor("0.1") + money.to_minor("0.2") == money.to_minor("0.3") == 30
    assert money.to_minor("1,250.505") == 125051 and money.s(125051) == "1250.51"
    for bad in [0.1, "abc", "NaN", "Infinity", -5, None, True, "9" * 20]:
        with pytest.raises(money.MoneyError):
            money.to_minor(bad)
    assert money.fmt(85000, "BDT") == "৳850.00" and money.fmt(-5, "USD") == "-$0.05"


# ------------------------------------------------------------------------------------------ amounts
def test_gross_discount_tax_and_final_stay_distinct_and_add_up():
    a = acct()
    t = spend(a, "800", gross_amount="850", discount="50")
    assert (t["gross_amount"], t["discount"], t["final_amount"]) == ("850.00", "50.00", "800.00")
    t2 = books.create_transaction(U, {"type": "expense", "account_id": a["id"], "gross_amount": "1000", "discount": "100", "tax": "75",
                                      "service_charge": "25", "category": "food"})
    assert t2["final_amount"] == "1000.00" and t2["tax"] == "75.00"
    t3 = spend(a, "900", discount="100")                   # final given, gross derived
    assert t3["gross_amount"] == "1000.00"
    with pytest.raises(FinanceError, match="do not add up"):
        spend(a, "700", gross_amount="850", discount="50")
    with pytest.raises(FinanceError, match="larger than"):
        books.create_transaction(U, {"type": "expense", "account_id": a["id"], "gross_amount": "100", "discount": "150"})
    with pytest.raises(FinanceError, match="greater than zero"):
        spend(a, "0")
    with pytest.raises(FinanceError, match="expenses and refunds only"):
        books.create_transaction(U, {"type": "income", "account_id": a["id"], "amount": "10", "discount": "1"})


def test_the_database_itself_refuses_negative_amounts():
    a = acct()
    c = db.connect()
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO fin_transactions (id,username,type,ts,account_id,gross_minor,final_minor,currency,source,created,updated) "
                  "VALUES ('x','alice','expense','2026-01-01T00:00:00',?,-5,-5,'BDT','manual','n','n')", (a["id"],))
    c.close()


# ------------------------------------------------------------------------------------------ balances and the accounting rules
def test_balances_follow_the_accounting_rules_and_nothing_is_double_counted():
    cash, bank = acct("Cash", "cash", "1000"), acct("City Bank", "bank", "5000")
    sav, card = acct("Savings", "savings", "0"), acct("Visa", "credit_card", "0")
    books.create_transaction(U, {"type": "income", "account_id": bank["id"], "amount": "20000", "category": "salary"})
    spend(cash, "300")
    books.create_transaction(U, {"type": "transfer", "account_id": bank["id"], "to_account_id": sav["id"], "amount": "3000"})
    spend(card, "2000", category="shopping")                                          # card purchase: liability grows
    books.create_transaction(U, {"type": "transfer", "account_id": bank["id"], "to_account_id": card["id"], "amount": "2000"})   # paying the card
    b = {a["name"]: a["balance"] for a in books.list_accounts(U)}
    assert b == {"Cash": "700.00", "City Bank": "20000.00", "Savings": "3000.00", "Visa": "0.00"}
    pos = books.position(U)
    assert pos["liquid"] == "23700.00" and pos["net_worth"] == "23700.00" and pos["liabilities"] == "0.00"
    spend(card, "500", category="shopping")
    pos = books.position(U)
    assert pos["liabilities"] == "500.00" and pos["net_worth"] == "23200.00" and pos["liquid"] == "23700.00"


def test_refunds_return_money_to_the_account_and_cannot_exceed_the_purchase():
    cash = acct("Cash", "cash", "1000")
    t = spend(cash, "400", category="shopping")
    r = books.create_transaction(U, {"type": "refund", "account_id": cash["id"], "amount": "150", "refund_of": t["id"]})
    assert r["category"] == "shopping" and books.list_accounts(U)[0]["balance"] == "750.00"
    with pytest.raises(FinanceError, match="exceed the original"):
        books.create_transaction(U, {"type": "refund", "account_id": cash["id"], "amount": "300", "refund_of": t["id"]})
    with pytest.raises(FinanceError, match="refunds of this expense"):
        books.void_transaction(U, t["id"])


def test_transfers_validate_their_accounts_and_currencies():
    a, b = acct("A", "cash", "100"), acct("B", "bank", "0")
    usd = books.create_account(U, "Dollar", "bank", "0", currency="USD")
    for bad, msg in [({"to_account_id": a["id"]}, "two different"), ({"to_account_id": usd["id"]}, "currency conversion"), ({}, "No such account")]:
        with pytest.raises(FinanceError, match=msg):
            books.create_transaction(U, dict({"type": "transfer", "account_id": a["id"], "amount": "10"}, **bad))
    with pytest.raises(FinanceError, match="Only a transfer"):
        books.create_transaction(U, {"type": "expense", "account_id": a["id"], "to_account_id": b["id"], "amount": "5", "category": "food"})
    with pytest.raises(FinanceError, match="uses BDT"):
        spend(a, "5", currency="USD")


def test_balances_can_be_read_as_of_a_past_date_and_future_entries_are_not_actual():
    a = acct("Cash", "cash", "1000", opening_date="2026-01-01")
    spend(a, "100", ts="2026-02-10")
    spend(a, "50", ts="2026-03-10")
    spend(a, "999", ts="2999-01-01")                                                # planned, not actual
    assert books.balances(U, "2026-02-28T23:59:59")[a["id"]] == 90000
    assert books.balances(U, "2026-03-31T23:59:59")[a["id"]] == 85000
    assert books.list_accounts(U)[0]["balance"] == "850.00"                          # now: future one excluded
    assert books.balances(U, "2025-12-31T00:00:00")[a["id"]] == 0                    # before the account existed


def test_reconcile_reports_the_gap_and_posts_one_adjustment_that_changes_no_totals():
    a = acct("Cash", "cash", "1000")
    spend(a, "250")
    r = books.reconcile(U, a["id"], "700")
    assert r["ledger"] == "750.00" and r["difference"] == "-50.00" and not r["applied"]
    r = books.reconcile(U, a["id"], "700", apply=True)
    assert r["applied"] and books.list_accounts(U)[0]["balance"] == "700.00"
    assert books.reconcile(U, a["id"], "700", apply=True)["applied"] is False       # nothing left to adjust


def test_only_liabilities_can_start_negative_and_owing_is_stored_as_negative():
    with pytest.raises(FinanceError):
        acct("Bad", "cash", "-5")
    loan = books.create_account(U, "Loan", "loan", "5000")
    assert loan["balance"] == "-5000.00" and books.position(U)["liabilities"] == "5000.00"


def test_accounts_are_unique_per_user_archived_not_deleted_and_isolated_between_users():
    a = acct("Cash")
    with pytest.raises(FinanceError, match="already have"):
        acct("Cash")
    books.update_account(U, a["id"], {"archived": True})
    with pytest.raises(FinanceError, match="archived"):
        spend(a, "5")
    assert books.list_accounts(U) == [] and len(books.list_accounts(U, include_archived=True)) == 1
    with pytest.raises(FinanceError) as e:
        books.get_account("bob", a["id"])
    assert e.value.status == 404
    assert books.list_accounts("bob") == []


# ------------------------------------------------------------------------------------------ idempotency, edit, delete
def test_the_same_idempotency_key_never_creates_a_second_record():
    a = acct()
    body = {"type": "expense", "account_id": a["id"], "amount": "100", "category": "food"}
    first = books.create_transaction(U, body, idempotency_key="k1")
    again = books.create_transaction(U, body, idempotency_key="k1")
    assert again["id"] == first["id"] and again["duplicate"] is True
    assert books.list_transactions(U)["total"] == 1 and books.list_accounts(U)[0]["balance"] == "900.00"
    other = books.create_account("bob2", "C", "cash")
    assert books.create_transaction("bob2", {"type": "income", "account_id": other["id"], "amount": "5"}, idempotency_key="k1")["id"] != first["id"]


def test_edit_recomputes_and_keeps_the_ledger_consistent_and_delete_is_soft():
    a = acct()
    t = spend(a, "100")
    u = books.update_transaction(U, t["id"], {"amount": "250", "merchant": "Shwapno", "note": "weekly shop"})
    assert u["final_amount"] == "250.00" and u["merchant"] == "Shwapno" and books.list_accounts(U)[0]["balance"] == "750.00"
    u = books.update_transaction(U, t["id"], {"discount": "20"})                          # final = gross - discount
    assert u["gross_amount"] == "250.00" and u["final_amount"] == "230.00"
    with pytest.raises(FinanceError, match="type of a recorded"):
        books.update_transaction(U, t["id"], {"type": "income"})
    books.void_transaction(U, t["id"])
    assert books.list_accounts(U)[0]["balance"] == "1000.00" and books.list_transactions(U)["total"] == 0
    with pytest.raises(FinanceError):
        books.update_transaction(U, t["id"], {"amount": "5"})
    assert books.get_transaction(U, t["id"], include_void=True)["id"] == t["id"]       # kept for the audit trail


def test_search_filter_sort_and_pagination():
    a, b = acct("Cash"), acct("Bkash", "wallet", "500")
    spend(a, "100", merchant="Shwapno", ts="2026-03-01", category="food")
    spend(a, "300", merchant="Daraz", ts="2026-03-05", category="shopping", tags=["gift"])
    spend(b, "50", merchant="Pathao", ts="2026-03-09", category="transport", payment_method="bkash")
    books.create_transaction(U, {"type": "income", "account_id": a["id"], "amount": "9000", "ts": "2026-03-02", "category": "salary"})
    L = lambda **kw: books.list_transactions(U, **kw)
    assert L()["total"] == 4
    assert [t["merchant"] for t in L(type="expense", sort="amount", direction="desc")["items"]] == ["Daraz", "Shwapno", "Pathao"]
    assert L(category="shopping")["total"] == 1 and L(merchant="path")["total"] == 1 and L(account_id=b["id"])["total"] == 1
    assert L(start="2026-03-02", end="2026-03-06")["total"] == 2 and L(q="gift")["total"] == 1 and L(payment_method="bkash")["total"] == 1
    assert L(min_amount="200", max_amount="500")["total"] == 1
    p = L(size=2, page=2)
    assert len(p["items"]) == 2 and p["pages"] == 2 and L(size=9999)["size"] == books.MAX_PAGE


def test_unknown_categories_are_rejected_and_essential_defaults_apply():
    a = acct()
    with pytest.raises(FinanceError, match="Unknown category"):
        spend(a, "5", category="spaceships")
    assert spend(a, "5", category="housing")["essential"] is True and spend(a, "5", category="entertainment")["essential"] is False
    assert spend(a, "5", category="food", subcategory="groceries")["essential"] is True
    assert spend(a, "5", category="food", subcategory="dining out", essential=True)["essential"] is True   # the user's word wins
