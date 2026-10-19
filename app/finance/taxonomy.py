"""Categories, essential/discretionary defaults and a keyword guesser (English, Bangla and Banglish)."""
from typing import Optional

# category -> (essential default, subcategories, keywords)
EXPENSE = {
    "food": (None, ["groceries", "dining out", "snacks", "drinks"],
             ["grocery", "groceries", "rice", "oil", "vegetable", "fish", "meat", "egg", "milk", "bazar", "bazaar", "market",
              "restaurant", "lunch", "dinner", "breakfast", "biryani", "tea", "coffee", "snack", "cafe", "pizza", "burger",
              "চাল", "তেল", "সবজি", "বাজার", "মাছ", "মাংস", "ডিম", "দুধ", "খাবার", "চা", "দোকান", "মুদি",
              "shwapno", "agora", "meena bazar", "unimart", "kfc", "foodpanda", "pizza hut"]),
    "transport": (True, ["fuel", "ride share", "public transport", "vehicle upkeep"],
                  ["uber", "pathao", "rickshaw", "bus", "cng", "fuel", "petrol", "octane", "train", "taxi", "fare", "ticket",
                   "রিকশা", "বাস", "ভাড়া", "পেট্রোল", "ট্রেন", "উবার"]),
    "housing": (True, ["rent", "maintenance", "furniture"], ["rent", "house rent", "flat", "landlord", "ভাড়া", "বাসা", "বাড়ি"]),
    "utilities": (True, ["electricity", "gas", "water", "internet", "phone"],
                  ["electricity", "current bill", "gas bill", "water bill", "internet", "wifi", "broadband", "recharge", "mobile bill",
                   "বিদ্যুৎ", "গ্যাস", "ইন্টারনেট", "রিচার্জ", "বিল"]),
    "health": (True, ["medicine", "doctor", "tests", "fitness"],
               ["medicine", "pharmacy", "doctor", "hospital", "clinic", "test", "gym", "ওষুধ", "ঔষধ", "ডাক্তার", "হাসপাতাল"]),
    "education": (True, ["tuition", "books", "courses", "exam fees"],
                  ["tuition", "school", "college", "university", "course", "book", "exam", "fee", "coaching", "টিউশন", "স্কুল", "বই", "কোচিং"]),
    "shopping": (False, ["clothing", "electronics", "household", "gifts"],
                 ["clothes", "shirt", "shoes", "phone", "laptop", "headphone", "gadget", "shopping", "mall", "daraz", "gift",
                  "জামা", "জুতা", "মোবাইল", "শপিং", "উপহার"]),
    "entertainment": (False, ["movies", "games", "subscriptions", "travel"],
                      ["movie", "cinema", "netflix", "spotify", "youtube", "game", "concert", "trip", "tour", "hotel", "resort",
                       "সিনেমা", "ঘুরতে", "ট্যুর", "হোটেল"]),
    "personal care": (None, ["salon", "toiletries"], ["salon", "haircut", "barber", "parlour", "soap", "shampoo", "সেলুন", "পার্লার"]),
    "family": (None, ["support", "children", "events"], ["family", "parents", "mother", "father", "wedding", "eid", "পরিবার", "মা", "বাবা", "ঈদ"]),
    "debt": (True, ["loan installment", "card payment", "interest"], ["loan", "installment", "emi", "interest", "ঋণ", "কিস্তি"]),
    "charity": (None, ["donation", "zakat"], ["donation", "zakat", "sadaqah", "charity", "দান", "যাকাত"]),
    "other": (None, [], []),
}
INCOME = {
    "salary": ["salary", "payroll", "wage", "বেতন"],
    "freelance": ["freelance", "client payment", "project", "gig"],
    "business": ["sales", "business", "shop income", "ব্যবসা"],
    "gift": ["gift", "eidi", "bonus", "উপহার", "ঈদি"],
    "interest": ["interest", "dividend", "profit", "মুনাফা"],
    "other income": [],
}
ACCOUNT_TYPES = ["cash", "bank", "savings", "wallet", "credit_card", "investment", "loan"]
LIABILITY_TYPES = {"credit_card", "loan"}
LIQUID_TYPES = {"cash", "bank", "wallet", "savings"}
PAYMENT_METHODS = ["cash", "bank", "card", "bkash", "nagad", "rocket", "mobile wallet", "other"]
PAYMENT_WORDS = {"cash": ["cash", "নগদ টাকা"], "bkash": ["bkash", "bKash", "বিকাশ"], "nagad": ["nagad", "নগদ"],
                 "rocket": ["rocket", "রকেট"], "card": ["card", "visa", "mastercard", "কার্ড"],
                 "bank": ["bank", "transfer", "ব্যাংক", "ব্যাঙ্ক"]}


for _cat, (_e, _subs, _words) in EXPENSE.items():          # the category's own name is a keyword too ("how much on food?")
    if _cat != "other" and _cat not in _words:
        _words.append(_cat)


def categories(kind: str = "expense") -> list[str]:
    return list(EXPENSE) if kind != "income" else list(INCOME)


def subcategories(category: str) -> list[str]:
    return list(EXPENSE.get(category, (None, [], []))[1])


_BN_SUFFIX = {"", "র", "য়", "ে", "কে", "ের", "গুলো", "গুলি", "টা", "টি", "ও", "ই", "য়ে", "েই", "দের"}


def _bn_hit(word: str, text: str) -> bool:
    """A Bangla word matches a whole token, optionally with an inflection suffix (so বাস does not match বাসা)."""
    import re
    for tok in re.findall(r"[ঀ-৿]+", text):
        if tok == word or (tok.startswith(word) and tok[len(word):] in _BN_SUFFIX):
            return True
    return False


def guess(text: str) -> tuple[str, Optional[str], float]:
    """(category, subcategory, confidence). Whole-word match for Latin keywords, whole-token match for Bangla."""
    import re
    t = (text or "").lower()
    best, hits = "other", 0
    for cat, (_, _, words) in EXPENSE.items():
        n = 0
        for w in words:
            if w.isascii():
                if re.search(r"\b" + re.escape(w.lower()) + r"s?\b", t):
                    n += 1
            elif _bn_hit(w, t):
                n += 1
        if n > hits:
            best, hits = cat, n
    if hits == 0:
        return "other", None, 0.0
    sub = None
    if best == "food":
        sub = "groceries" if re.search(r"grocer|rice|oil|vegetable|bazar|bazaar|চাল|তেল|সবজি|বাজার|মুদি|market|fish|meat|egg|milk", t) else "dining out"
    elif best == "utilities":
        for k in ("electricity", "gas", "water", "internet", "phone"):
            if re.search(k if k != "phone" else r"recharge|mobile bill|phone", t):
                sub = k
                break
    return best, sub, min(0.95, 0.5 + 0.2 * hits)


def guess_income(text: str) -> str:
    t = (text or "").lower()
    for cat, words in INCOME.items():
        if any(w in t for w in words):
            return cat
    return "other income"


def default_essential(category: Optional[str], subcategory: Optional[str] = None) -> Optional[bool]:
    if category == "food":
        return True if subcategory == "groceries" else (False if subcategory in ("dining out", "snacks", "drinks") else None)
    return EXPENSE.get(category or "", (None,))[0]


def payment_method_from(text: str) -> Optional[str]:
    t = (text or "").lower()
    for method, words in PAYMENT_WORDS.items():
        for w in words:
            if (w.isascii() and w.lower() in t.split()) or (not w.isascii() and w in text):
                return method
    return None
