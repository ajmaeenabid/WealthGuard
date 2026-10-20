"""Versioned financial-jurisdiction configuration (Bangladesh, mainland China). One place for every country-specific convention, so no `if country == ...` is scattered through the code. Language is a separate setting: any."""
from typing import Optional

VERSION = "2026.10.1"
DEFAULT = "BD"

COMMON_ACCOUNT_TYPES = ["cash", "bank", "savings", "wallet", "credit_card", "investment", "loan"]

CONFIGS = {
    "BD": {
        "code": "BD", "version": VERSION, "name": {"en": "Bangladesh", "zh": "孟加拉国", "bn": "বাংলাদেশ"},
        "currency": "BDT", "currency_name": {"en": "Bangladeshi taka", "zh": "孟加拉塔卡", "bn": "বাংলাদেশি টাকা"}, "symbol": "৳", "subunit": "poisha", "precision": 2,
        "supported_currencies": ["BDT"],
        "number_locale": {"en": "en-BD", "bn": "bn-BD", "zh": "zh-CN"}, "date_format": "dd/mm/yyyy (displayed per language locale)", "timezone": "Asia/Dhaka",
        "account_types": COMMON_ACCOUNT_TYPES,
        "payment_methods": [
            {"id": "cash", "kind": "cash"}, {"id": "bank", "kind": "bank"}, {"id": "card", "kind": "card"},
            {"id": "bkash", "kind": "mobile_financial_service", "label": "bKash", "wallet": True, "official_list_verified": False},
            {"id": "nagad", "kind": "mobile_financial_service", "label": "Nagad", "wallet": True, "official_list_verified": False},
            {"id": "rocket", "kind": "mobile_financial_service", "label": "Rocket", "wallet": True, "official_list_verified": False},
            {"id": "other", "kind": "other"}],
        "wallet_suggestions": ["bKash", "Nagad", "Rocket"],
        "tax_fields": ["vat", "service_charge"],
        "terms": {"vat": {"en": "VAT", "zh": "增值税", "bn": "ভ্যাট"}, "service_charge": {"en": "service charge", "zh": "服务费", "bn": "সার্ভিস চার্জ"}},
        "integrations": {"bank_sync": False, "wallet_sync": False, "note": "Manual entry and CSV import only. No bank or wallet login, PIN or OTP is ever requested; a sync would need an authorised provider API."},
        "import_formats": ["csv"],
        "sources": [
            {"name": "Bangladesh Bank", "url": "https://www.bb.org.bd/", "checked": "2026-10-19", "confirmed": ["Taka (BDT) exchange reference rates are published", "a Payment Systems section exists"],
             "not_found": ["a list of licensed mobile financial service providers on the home page"]},
            {"name": "National Board of Revenue", "url": "https://nbr.gov.bd/", "checked": "2026-10-19", "confirmed": ["VAT Act/Rules and Income Tax Act/Rules are published as documents"],
             "not_found": ["any tax rate stated on the home page"]},
            {"name": "Bangladesh Financial Intelligence Unit", "url": "https://www.bfiu.org.bd/", "checked": "2026-10-19", "confirmed": ["it is the central agency against money laundering and terrorist financing"],
             "not_found": ["customer-due-diligence or reporting thresholds on the home page"]}],
        "unverified": ["That bKash, Nagad and Rocket are offered is a common convention; no official provider list was found on the page checked.",
                       "No VAT, income-tax or transaction-limit figures are included, because none were verified from an official page."],
    },
    "CN": {
        "code": "CN", "version": VERSION, "name": {"en": "China (mainland)", "zh": "中国大陆", "bn": "চীন (মূল ভূখণ্ড)"},
        "currency": "CNY", "currency_name": {"en": "Chinese yuan (renminbi)", "zh": "人民币", "bn": "চীনা ইউয়ান (রেনমিনবি)"}, "symbol": "¥", "subunit": "fen", "precision": 2,
        "supported_currencies": ["CNY"],
        "number_locale": {"en": "en-CN", "bn": "bn-BD", "zh": "zh-CN"}, "date_format": "yyyy-mm-dd (displayed per language locale)", "timezone": "Asia/Shanghai",
        "account_types": COMMON_ACCOUNT_TYPES,
        "payment_methods": [
            {"id": "cash", "kind": "cash"}, {"id": "bank", "kind": "bank"}, {"id": "card", "kind": "card"},
            {"id": "alipay", "kind": "mobile_payment", "label": "Alipay", "wallet": True, "official_list_verified": False},
            {"id": "wechat_pay", "kind": "mobile_payment", "label": "WeChat Pay", "wallet": True, "official_list_verified": False},
            {"id": "other", "kind": "other"}],
        "wallet_suggestions": ["Alipay", "WeChat Pay"],
        "tax_fields": ["vat", "service_charge"],
        "terms": {"vat": {"en": "VAT", "zh": "增值税", "bn": "ভ্যাট"}, "service_charge": {"en": "service charge", "zh": "服务费", "bn": "সার্ভিস চার্জ"}},
        "integrations": {"bank_sync": False, "wallet_sync": False, "note": "Manual entry and CSV import only. No bank or wallet login, PIN or OTP is ever requested; a sync would need an authorised provider API."},
        "import_formats": ["csv"],
        "sources": [
            {"name": "People's Bank of China", "url": "http://www.pbc.gov.cn/en/3688006/index.html", "checked": "2026-10-19", "confirmed": ["RMB exchange-rate pages and a 'Mobile Payment and IC Card' section exist"],
             "not_found": ["any mention of Alipay or WeChat Pay on the page", "licence or limit figures for payment institutions"]},
            {"name": "State Taxation Administration", "url": "https://www.chinatax.gov.cn/", "checked": "2026-10-19", "confirmed": ["VAT and individual income tax are covered by notices"],
             "not_found": ["any VAT or income-tax rate on the home page"]},
            {"name": "National Bureau of Statistics of China", "url": "https://www.stats.gov.cn/english/", "checked": "2026-10-19", "confirmed": ["Consumer Price Index releases (September 2026 released 15 Oct 2026)"],
             "not_found": ["household expenditure figures on the home page"]}],
        "unverified": ["That Alipay and WeChat Pay are offered is a common convention; no official page checked lists them.",
                       "No VAT, income-tax or payment-limit figures are included, because none were verified from an official page."],
    },
}
LABELS = {"cash": {"en": "Cash", "zh": "现金", "bn": "নগদ টাকা"}, "bank": {"en": "Bank", "zh": "银行", "bn": "ব্যাংক"}, "card": {"en": "Card", "zh": "银行卡", "bn": "কার্ড"},
          "other": {"en": "Other", "zh": "其他", "bn": "অন্যান্য"}, "bkash": {"en": "bKash", "zh": "bKash", "bn": "বিকাশ"}, "nagad": {"en": "Nagad", "zh": "Nagad", "bn": "নগদ"},
          "rocket": {"en": "Rocket", "zh": "Rocket", "bn": "রকেট"}, "alipay": {"en": "Alipay", "zh": "支付宝", "bn": "Alipay"}, "wechat_pay": {"en": "WeChat Pay", "zh": "微信支付", "bn": "WeChat Pay"}}


class JurisdictionError(ValueError):
    pass


def codes() -> list[str]:
    return list(CONFIGS)


def get(code: Optional[str]) -> dict:
    c = (code or DEFAULT).upper()
    if c not in CONFIGS:
        raise JurisdictionError(f"Unknown jurisdiction '{code}'. Choose one of: {', '.join(CONFIGS)}.")
    return CONFIGS[c]


def validate(code: str) -> str:
    return get(code)["code"]


def currency(code: Optional[str]) -> str:
    return get(code)["currency"]


def payment_method_ids(code: Optional[str]) -> list[str]:
    return [m["id"] for m in get(code)["payment_methods"]]


def summary(code: Optional[str]) -> dict:
    c = get(code)
    return {k: c[k] for k in ("code", "version", "name", "currency", "currency_name", "symbol", "subunit", "precision", "supported_currencies", "number_locale", "date_format",
                              "timezone", "account_types", "payment_methods", "wallet_suggestions", "tax_fields", "terms", "integrations", "import_formats")}


def details(code: Optional[str]) -> dict:
    c = get(code)
    return dict(summary(code), sources=c["sources"], unverified=c["unverified"])
