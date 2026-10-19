"""Chinese, English and Bangla in the money assistant, and language/jurisdiction as independent settings."""
import uuid
from datetime import timedelta

import pytest

from app.finance import assistant, books, money, rules, settings

U = "alice"


def say(text, user=U, **kw):
    return assistant.turn(user, text, uuid.uuid4().hex, **kw)


@pytest.mark.parametrize("zh,n", [("三百五十", 350), ("两千", 2000), ("一万二", 12000), ("十五", 15), ("八千", 8000), ("三百五", 350)])
def test_chinese_numerals(zh, n):
    assert rules.zh_to_int(zh) == n


def test_bengali_digits_and_chinese_numerals_normalise_to_the_same_value():
    from datetime import date
    a = rules.extract("আজ ৮৫০ টাকা বাজার করলাম", date.today())["transaction"]["amount"]
    b = rules.extract("今天买菜花了八百五十元", date.today())["transaction"]["amount"]
    c = rules.extract("I spent 850 taka on groceries", date.today())["transaction"]["amount"]
    assert a == b == c == "850"


def test_chinese_payment_and_type_words():
    from datetime import date
    t = rules.extract("今天在超市花了三百五十元买菜，用支付宝", date.today())["transaction"]
    assert (t["type"], t["amount"], t["payment_method"]) == ("expense", "350", "alipay")
    assert rules.extract("收到工资 8000 元", date.today())["transaction"]["type"] == "income"
    assert rules.extract("午饭花了 28.5 元，微信支付", date.today())["transaction"]["payment_method"] == "wechat_pay"


@pytest.mark.parametrize("word", ["是", "好的", "确认", "保存"])
def test_chinese_confirmations(word):
    assert rules.YES.match(word)
    assert rules.NO.match("没有") and rules.CANCEL.match("取消")


def test_chinese_conversation_end_to_end_in_cny():
    settings.update(U, {"ui_lang": "zh", "jurisdiction": "CN"})
    books.create_account(U, "支付宝", "wallet", "1000", opening_date=(money.today() - timedelta(days=30)).isoformat())
    r = say("今天在超市花了三百五十元买菜，用支付宝")
    assert r["language"] == "zh" and "¥350.00" in r["reply"] and "我将记录" in r["reply"]
    assert books.list_transactions(U)["total"] == 0                       # nothing saved before confirming
    r = say("是")
    assert r["state"] == "completed" and r["reply"].startswith("已保存") and books.list_transactions(U)["total"] == 1
    t = books.list_transactions(U)["items"][0]
    assert t["currency"] == "CNY" and t["final_amount"] == "350.00"


def test_request_override_beats_saved_preference():
    settings.update(U, {"ui_lang": "zh"})
    r = say("help", lang="en")
    assert r["language"] == "en" and r["reply"].startswith("I can record")
    r = say("help", lang="bn")
    assert r["language"] == "bn"


def test_saved_interface_language_is_the_default_for_ambiguous_text():
    settings.update(U, {"ui_lang": "bn"})
    assert say("help")["language"] == "bn"
    settings.update(U, {"assistant_lang": "zh"})
    assert say("help")["language"] == "zh"


def test_choosing_a_country_sets_its_currency_immediately_and_usd_stays_selectable():
    s = settings.update(U, {"jurisdiction": "CN"})
    assert s["base_currency"] == "CNY" and s["currency_chosen"] and s["currency_changed_to"] == "CNY"
    assert settings.update(U, {"jurisdiction": "BD"})["base_currency"] == "BDT"
    assert settings.update(U, {"base_currency": "USD"})["base_currency"] == "USD"           # a manual pick still works
    assert settings.update(U, {"ui_lang": "zh"})["base_currency"] == "USD"                  # unrelated changes do not touch it
    assert settings.update(U, {"jurisdiction": "CN"})["base_currency"] == "CNY"             # but choosing a country sets it again
    assert settings.update(U, {"jurisdiction": "CN"})["base_currency"] == "CNY"             # re-selecting the same country is a no-op
    with pytest.raises(Exception):
        settings.update(U, {"base_currency": "EUR"})


def test_language_and_jurisdiction_are_independent():
    for lang in ("en", "bn", "zh"):
        for jur in ("BD", "CN"):
            s = settings.update(U, {"ui_lang": lang, "jurisdiction": jur})
            assert s["ui_lang"] == lang and s["jurisdiction"] == jur


def test_each_account_has_its_own_currency_and_totals_follow_the_chosen_one():
    settings.update(U, {"base_currency": "USD"})
    books.create_account(U, "Dollar cash", "cash", "100", currency="USD")
    books.create_account(U, "Yuan wallet", "wallet", "700", currency="CNY")
    books.create_account(U, "Taka bKash", "wallet", "5000", currency="BDT")
    pos = books.position(U)
    assert pos["currency"] == "USD" and pos["liquid"] == "100.00" and sorted(pos["excluded_other_currency"]) == ["Taka bKash", "Yuan wallet"]
    settings.update(U, {"base_currency": "CNY"})
    pos = books.position(U)
    assert pos["currency"] == "CNY" and pos["liquid"] == "700.00"                       # nothing was converted, only the view changed
    with pytest.raises(Exception):
        books.create_account(U, "Euro", "cash", "1", currency="EUR")


def test_the_first_account_sets_the_currency_when_none_was_chosen():
    assert not settings.get(U)["currency_chosen"]
    books.create_account(U, "Alipay", "wallet", "10", currency="CNY")
    s = settings.get(U)
    assert s["currency_chosen"] and s["base_currency"] == "CNY"


def test_ui_offers_the_three_currencies_and_no_default_symbol():
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "static" / "finance.js").read_text(encoding="utf-8")
    assert 'id="stCur"' in js and 'id="afCur"' in js and "Choose your currency" in js
    assert 'currency: "BDT"' not in js and "taka at the grocery" not in js
    assert settings.get(U)["currencies"] == [{"code": "USD", "symbol": "$", "name": "US dollar"}, {"code": "CNY", "symbol": "¥", "name": "Chinese yuan (RMB)"}, {"code": "BDT", "symbol": "৳", "name": "Bangladeshi taka"}]


def test_relabel_all_accounts_changes_the_label_not_the_amounts():
    books.create_account(U, "Cash", "cash", "1000", currency="BDT")
    books.create_account(U, "Bank", "bank", "500", currency="BDT")
    cash = books.list_accounts(U)[0]
    books.create_transaction(U, {"type": "expense", "ts": money.today().isoformat(), "account_id": cash["id"], "amount": "100", "merchant": "x", "category": "food"}, source="manual")
    out = books.relabel_currency(U, "USD")
    assert out["accounts"] == 2 and out["transactions"] >= 1
    assert {a["currency"] for a in books.list_accounts(U)} == {"USD"}
    assert books.list_accounts(U)[0]["opening_balance"] in ("1000.00", "500.00")          # same numbers, new label
    assert books.list_transactions(U)["items"][0]["currency"] == "USD"


def test_one_account_can_be_relabelled_unless_a_transfer_ties_it_to_another_currency():
    y = books.create_account(U, "Yuan", "cash", "100", currency="CNY")
    assert books.update_account(U, y["id"], {"currency": "USD"})["currency"] == "USD"
    a = books.create_account(U, "Dollar bank", "bank", "500", currency="USD")
    b = books.create_account(U, "Dollar savings", "savings", "0", currency="USD")
    books.create_transaction(U, {"type": "transfer", "account_id": a["id"], "to_account_id": b["id"], "amount": "50"})
    with pytest.raises(Exception) as e:
        books.update_account(U, a["id"], {"currency": "CNY"})                    # its transfer partner is still USD
    assert "transfers" in str(e.value)
    assert books.relabel_currency(U, "CNY")["accounts"] == 3                      # together it is fine
    with pytest.raises(Exception):
        books.update_account(U, a["id"], {"currency": "EUR"})
