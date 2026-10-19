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


def test_language_and_jurisdiction_are_independent_and_base_currency_follows_jurisdiction():
    for lang in ("en", "bn", "zh"):
        for jur, cur in (("BD", "BDT"), ("CN", "CNY")):
            s = settings.update(U, {"ui_lang": lang, "jurisdiction": jur})
            assert s["ui_lang"] == lang and s["jurisdiction"] == jur and s["base_currency"] == cur


def test_other_currency_accounts_are_kept_but_not_mixed_into_totals():
    books.create_account(U, "Cash", "cash", "1000")                       # BDT
    settings.update(U, {"jurisdiction": "CN"})
    books.create_account(U, "Alipay", "wallet", "200")                    # CNY
    pos = books.position(U)
    assert pos["excluded_other_currency"] == ["Cash"] and pos["liquid"] == "200.00"
    settings.update(U, {"jurisdiction": "BD"})
    pos = books.position(U)
    assert pos["excluded_other_currency"] == ["Alipay"] and pos["liquid"] == "1000.00"


def test_chinese_answers_use_the_same_figures():
    settings.update(U, {"ui_lang": "zh", "jurisdiction": "CN"})
    books.create_account(U, "支付宝", "wallet", "1000", opening_date=(money.today() - timedelta(days=30)).isoformat())
    say("今天在超市花了三百五十元买菜，用支付宝")
    say("是")
    r = say("我的余额是多少")
    assert r["language"] == "zh" and "¥650.00" in r["reply"] and "流动资金" in r["reply"]
    r = say("这个月我花了多少")
    assert "¥350.00" in r["reply"] and "本月" in r["reply"]
