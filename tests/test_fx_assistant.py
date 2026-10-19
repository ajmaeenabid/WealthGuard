"""The money assistant and currencies: what is said in one currency is converted into the account's currency at a real rate, never relabelled."""
import uuid
from datetime import timedelta

import pytest

from app.finance import assistant, books, fx, money, settings

U = "alice"


def say(text, lang=None):
    return assistant.turn(U, text, uuid.uuid4().hex, lang=lang)


def acct(name, cur, opening="1000", typ="cash"):
    return books.create_account(U, name, typ, opening, currency=cur, opening_date=(money.today() - timedelta(days=30)).isoformat())


def test_ten_taka_into_a_yuan_account_is_converted_and_shown_with_the_rate(fx_live):
    acct("Yuan wallet", "CNY")
    r = say("I spent 10 taka on tea today")
    assert r["state"] == "awaiting_confirmation" and "¥0.54" in r["reply"] and "৳10.00" in r["reply"]
    assert "1 BDT = 0.05424 CNY" in r["reply"] and "ExchangeRate-API" in r["reply"] and "2026-10-19" in r["reply"] and "indicative" in r["reply"]
    assert books.list_transactions(U)["total"] == 0                          # nothing saved before the yes
    r = say("yes")
    assert r["state"] == "completed" and "converted at 1 BDT" in r["reply"]
    t = books.list_transactions(U)["items"][0]
    assert t["currency"] == "CNY" and t["final_amount"] == "0.54" and t["original"]["amount"] == "10.00" and t["original"]["currency"] == "BDT"
    assert books.list_accounts(U)[0]["balance"] == "999.46"


def test_a_number_without_a_currency_is_the_accounts_own_currency_no_conversion(fx_live):
    acct("Yuan wallet", "CNY")
    r = say("I spent 10 on tea today")
    assert "¥10.00" in r["reply"] and "converted" not in r["reply"] and "indicative" not in r["reply"]
    say("yes")
    assert books.list_transactions(U)["items"][0]["final_amount"] == "10.00" and books.list_transactions(U)["items"][0]["original"] is None


def test_same_currency_is_not_converted(fx_live):
    acct("Cash", "BDT")
    r = say("I spent 10 taka on tea today")
    assert "৳10.00" in r["reply"] and "converted" not in r["reply"]


def test_chinese_and_bangla_currency_words_and_replies(fx_live):
    acct("Taka wallet", "BDT", typ="wallet")
    r = say("今天午饭花了10元", lang="zh")
    assert "৳" in r["reply"] and "换算" in r["reply"] and "参考汇率" in r["reply"]
    say("取消", lang="zh")
    r = say("আজ ১০ ডলার বাজার খরচ", lang="bn")
    assert "রূপান্তর" in r["reply"] and "আনুমানিক" in r["reply"]


def test_with_two_accounts_the_one_in_the_spoken_currency_is_chosen_without_converting(fx_live):
    acct("Yuan wallet", "CNY")
    acct("Taka bKash", "BDT", typ="wallet")
    r = say("I spent 10 taka on tea today")
    assert "Taka bKash" in r["reply"] and "converted" not in r["reply"] and "৳10.00" in r["reply"]


def test_no_exchange_rate_means_no_guess_the_assistant_asks_for_the_amount_in_the_account_currency():
    acct("Yuan wallet", "CNY")
    r = say("I spent 10 taka on tea today")                                   # FX is off in tests, like a dead network
    assert r["awaiting"] == "amount" and "can't get a current exchange rate" in r["reply"] and "¥0.54" not in r["reply"]
    assert books.list_transactions(U)["total"] == 0
    r = say("2")
    assert "¥2.00" in r["reply"] and "converted" not in r["reply"]            # now it is simply 2 yuan, as the person said


def test_a_message_naming_two_currencies_asks_which_one(fx_live):
    acct("Yuan wallet", "CNY")
    r = say("I paid 100 yuan which is 1800 taka for shoes today")
    assert r["awaiting"] == "currency" and "CNY / BDT" in r["reply"]
    r = say("yuan")
    assert "¥100.00" in r["reply"] and "converted" not in r["reply"]


def test_a_first_account_created_by_chat_uses_the_currency_said(fx_live):
    r = say("I paid 500 taka using bKash for lunch today")
    assert "৳500.00" in r["reply"]
    say("yes")
    a = books.list_accounts(U)[0]
    assert a["currency"] == "BDT" and "bkash" in a["name"].lower()


def test_discount_and_tax_are_converted_with_the_same_rate(fx_live):
    acct("Yuan wallet", "CNY")
    r = say("I spent 1000 taka on clothes today, 100 taka discount, 50 taka tax, amount before discount")
    for _ in range(4):
        if r.get("awaiting") != "confirm":
            r = say("final amount paid" if r.get("awaiting") == "amount_basis" else "no")
        else:
            break
    say("yes")
    t = books.list_transactions(U)["items"][0]
    g, d, x, f = (money.to_minor(t[k]) for k in ("gross_amount", "discount", "tax", "final_amount"))
    assert g - d + x == f and t["original"]["currency"] == "BDT"


def test_confirming_much_later_rechecks_the_rate_and_asks_again_if_it_moved(fx_live, monkeypatch):
    acct("Yuan wallet", "CNY")
    say("I spent 1000 taka on tea today")
    from app import store
    row = books._one("SELECT id, draft FROM fin_sessions WHERE username=? ORDER BY updated DESC LIMIT 1", (U,))
    import json
    draft = json.loads(row["draft"])
    draft["fx_quote"]["fetched"] = "2020-01-01T00:00:00Z"                    # the quote is hours old
    store._write("UPDATE fin_sessions SET draft=? WHERE id=?", (json.dumps(draft), row["id"]))
    fx_live["data"][0]["rates"]["CNY"] = 7.2                                  # and the market moved (both sources agree)
    fx_live["data"][1]["rates"]["CNY"] = 7.19
    monkeypatch.setenv("FX_CACHE_HOURS", "-1")                                # treat every cached rate as expired
    r = say("yes")
    assert r["state"] == "awaiting_confirmation" and "exchange rate changed" in r["reply"]
    assert books.list_transactions(U)["total"] == 0
    r = say("yes")
    assert r["state"] == "completed" and books.list_transactions(U)["items"][0]["final_amount"] == "58.35"      # 1000 BDT at the NEW rate, as shown


def test_the_model_cannot_invent_a_currency():
    from app.finance import rules
    assert rules.detect_currency("I spent 10 on tea") == (None, [])
    assert rules.detect_currency("spent 10 块") == ("CNY", [])               # 块 right after a digit is yuan
    assert rules.detect_currency("一块蛋糕")[0] is None                       # but not "a piece of cake"


def test_convert_questions_in_three_languages_use_the_real_rate(fx_live):
    r = say("How much is 100 yuan in taka?")
    assert "1,843.79" in r["reply"] or "৳1,843.79" in r["reply"]
    assert "ExchangeRate-API" in r["reply"] and "Indicative" in r["reply"]
    assert "৳1,843.79" in say("100元是多少塔卡", lang="zh")["reply"] and "参考汇率" in say("100元是多少塔卡", lang="zh")["reply"]
    assert "আনুমানিক" in say("১০০ টাকা কত ইউয়ান", lang="bn")["reply"]
    assert books.list_transactions(U)["total"] == 0                           # a question never records anything


def test_convert_question_without_a_rate_says_so():
    r = say("How much is 100 yuan in taka?")
    assert "can't get a current exchange rate" in r["reply"]


def test_ai_path_keeps_a_currency_only_when_the_message_wrote_it(fx_live, monkeypatch):
    """The live model may return a currency; it is kept only if the person's own words contain it, and it must pass the schema."""
    from app.finance import ai
    from app.finance.ai import AIResult
    acct("Yuan wallet", "CNY")
    monkeypatch.setattr(ai, "enabled", lambda: True)

    def fake(currency):
        def call(messages, **kw):
            parsed = {"intent": "create_transaction", "transaction": {k: None for k in assistant.TRANSACTION_FIELDS}, "query": {k: None for k in assistant.QUERY_FIELDS},
                      "missing_fields": [], "next_question": None, "proposed_action": "ask"}
            parsed["transaction"].update(type="expense", amount="10", date=money.today().isoformat(), category="food", currency=currency)
            return AIResult(content="{}", parsed=assistant.validate_turn(parsed))
        return call
    monkeypatch.setattr(ai, "call", fake("BDT"))
    r = say("I spent 10 taka on a long lunch with colleagues downtown today")
    assert "converted" in r["reply"] or "换算" in r["reply"] or "1 BDT" in r["reply"]
    say("cancel")
    monkeypatch.setattr(ai, "call", fake("BDT"))
    r = say("I spent 10 on a long lunch with colleagues downtown today")             # the model says BDT, the person never did
    assert "¥10.00" in r["reply"] and "1 BDT" not in r["reply"]
