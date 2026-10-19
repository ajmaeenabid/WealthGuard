"""Recording money in a currency other than the account's: converted at a real, stored rate, original kept, balances correct."""
import pytest

from app.finance import books, fx, money, settings
from app.finance.books import FinanceError

U = "alice"


def acct(name, cur, opening="1000", typ="cash"):
    return books.create_account(U, name, typ, opening, currency=cur, opening_date=(money.today() - __import__("datetime").timedelta(days=30)).isoformat())


def test_without_conversion_a_foreign_currency_amount_is_refused_not_silently_relabelled():
    yuan = acct("Yuan wallet", "CNY")
    with pytest.raises(FinanceError, match="unless it is converted"):
        books.create_transaction(U, {"type": "expense", "account_id": yuan["id"], "amount": "10", "currency": "BDT", "category": "food"})


def test_ten_taka_into_a_yuan_account_is_about_54_fen_with_the_original_kept(fx_live):
    yuan = acct("Yuan wallet", "CNY")
    t = books.create_transaction(U, {"type": "expense", "account_id": yuan["id"], "amount": "10", "currency": "BDT", "convert": True, "category": "food", "merchant": "tea"})
    assert t["final_amount"] == "0.54" and t["currency"] == "CNY"
    o = t["original"]
    assert (o["currency"], o["amount"], o["converted_to"]) == ("BDT", "10.00", "CNY") and o["source"].startswith("er-api@2026-10-19") and float(o["rate"]) == pytest.approx(0.0542, abs=1e-4)
    assert books.list_accounts(U)[0]["balance"] == "999.46"                    # the account moved by 0.54 yuan, not 10


def test_discount_tax_and_gross_are_converted_with_one_rate_and_still_add_up(fx_live):
    cny = acct("Yuan", "CNY")
    t = books.create_transaction(U, {"type": "expense", "account_id": cny["id"], "gross_amount": "1000", "discount": "100", "tax": "50", "currency": "BDT", "convert": True, "category": "shopping"})
    g, d, x, f = (money.to_minor(t[k]) for k in ("gross_amount", "discount", "tax", "final_amount"))
    assert g - d + x == f and t["original"]["amount"] == "950.00"             # 1000 - 100 + 50 spent in taka


def test_income_and_refund_conversions_use_the_same_path(fx_live):
    usd = acct("Dollar", "USD")
    t = books.create_transaction(U, {"type": "income", "account_id": usd["id"], "amount": "12340", "currency": "BDT", "convert": True, "category": "salary"})
    assert t["final_amount"] == "100.00" and t["original"]["currency"] == "BDT"


def test_a_confirmed_quote_is_applied_exactly_even_if_the_market_moved(fx_live):
    cny = acct("Yuan", "CNY")
    pinned = fx.rate("BDT", "CNY")
    fx_live["data"][0]["rates"]["CNY"] = 9.0                                    # the market moves after the person saw the summary
    import app.finance.fx as fxm
    from app import store
    store._write("DELETE FROM fin_fx_rates", ())
    t = books.create_transaction(U, {"type": "expense", "account_id": cny["id"], "amount": "100", "currency": "BDT", "convert": True, "fx_quote": pinned, "category": "food"})
    assert t["final_amount"] == money.s(fx.convert_minor(10000, "BDT", "CNY", quote=pinned)[0])
    assert t["original"]["rate"] == pinned["rate"]


def test_no_rate_means_no_conversion_and_a_readable_error_not_a_guess():
    cny = acct("Yuan", "CNY")
    with pytest.raises(FinanceError) as e:
        books.create_transaction(U, {"type": "expense", "account_id": cny["id"], "amount": "10", "currency": "BDT", "convert": True, "category": "food"})
    assert "cannot convert BDT to CNY" in e.value.message and "Enter the amount in CNY" in e.value.message and e.value.status == 503
    assert books.list_transactions(U)["total"] == 0


def test_editing_the_amount_by_hand_clears_the_old_conversion_record(fx_live):
    cny = acct("Yuan", "CNY")
    t = books.create_transaction(U, {"type": "expense", "account_id": cny["id"], "amount": "10", "currency": "BDT", "convert": True, "category": "food"})
    kept = books.update_transaction(U, t["id"], {"note": "tea"})
    assert kept["original"] is not None
    edited = books.update_transaction(U, t["id"], {"final_amount": "2.00"})
    assert edited["original"] is None and edited["final_amount"] == "2.00"


def test_cross_currency_transfer_debits_one_account_and_credits_the_other_converted(fx_live):
    bdt, cny = acct("bKash", "BDT", "5000", "wallet"), acct("Alipay", "CNY", "0", "wallet")
    with pytest.raises(FinanceError, match="currency conversion"):
        books.create_transaction(U, {"type": "transfer", "account_id": bdt["id"], "to_account_id": cny["id"], "amount": "1000"})
    t = books.create_transaction(U, {"type": "transfer", "account_id": bdt["id"], "to_account_id": cny["id"], "amount": "1000", "convert": True})
    assert t["final_amount"] == "1000.00" and t["to_amount"] == "54.24"
    bal = {a["name"]: a["balance"] for a in books.list_accounts(U)}
    assert bal == {"bKash": "4000.00", "Alipay": "54.24"}


def test_converted_figures_do_not_get_mixed_into_other_currency_totals(fx_live):
    settings.update(U, {"base_currency": "CNY"})
    cny, bdt = acct("Yuan", "CNY", "500"), acct("Taka", "BDT", "1000")
    books.create_transaction(U, {"type": "expense", "account_id": cny["id"], "amount": "50", "currency": "BDT", "convert": True, "category": "food"})
    pos = books.position(U)
    assert pos["liquid"] == "497.29" and pos["excluded_other_currency"] == ["Taka"]       # 500 - 2.71 yuan; the taka account is not silently added
