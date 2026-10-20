"""Bangla wording for answers, insights, report text and data-quality notes. Numbers stay in ASCII digits with the taka sign so they match the ledger."""
from typing import Optional

from app.finance import money

CATEGORY = {"food": "খাবার", "transport": "যাতায়াত", "housing": "বাসা ভাড়া", "utilities": "ইউটিলিটি বিল", "health": "স্বাস্থ্য", "education": "শিক্ষা",
            "shopping": "কেনাকাটা", "entertainment": "বিনোদন", "personal care": "ব্যক্তিগত যত্ন", "family": "পরিবার", "debt": "ঋণ", "charity": "দান",
            "other": "অন্যান্য", "salary": "বেতন", "freelance": "ফ্রিল্যান্স", "business": "ব্যবসা", "gift": "উপহার", "interest": "সুদ/মুনাফা",
            "other income": "অন্যান্য আয়"}
PERIOD = {"today": "আজ", "this week": "এই সপ্তাহে", "this month": "এই মাসে", "this year": "এই বছরে", "that period": "ওই সময়ে"}
STATUS = {"ok": "ঠিক আছে", "warning": "সতর্কতা", "over": "সীমা ছাড়িয়েছে", "paid": "পরিশোধিত", "due": "শিগগির", "planned": "পরিকল্পিত", "overdue": "বকেয়া"}
ASSUMPTIONS = {
    "Assumes a 10% reduction is realistic for this category.": "এই খাতে ১০% কমানো সম্ভব ধরা হয়েছে।",
    "Assumes about half of the increase could be avoided.": "বৃদ্ধির প্রায় অর্ধেক এড়ানো সম্ভব ধরা হয়েছে।",
    "Assumes a 20% cut in small purchases.": "ছোট কেনাকাটা ২০% কমানো সম্ভব ধরা হয়েছে।",
    "Assumes a 10% saving from planning.": "পরিকল্পনা করলে ১০% সাশ্রয় ধরা হয়েছে।",
    "Assumes a 10% reduction in discretionary spending.": "ঐচ্ছিক খরচ ১০% কমানো সম্ভব ধরা হয়েছে।",
    "Detected from repeated payments of the same amount to the same merchant.": "একই দোকানে একই অঙ্কের বারবার পেমেন্ট থেকে শনাক্ত করা হয়েছে।",
}


def cat(c: Optional[str]) -> str:
    return CATEGORY.get(c or "", c or "")


def fm(s: str, cur: str = "BDT") -> str:
    return money.fmt(money.to_minor(s, allow_negative=True), cur)


def pct(x) -> str:
    return f"{round(float(x) * 100)}%"


def insight(i: dict, cur: str) -> dict:
    e, k = i["evidence"], i["kind"]
    t = dict(i)
    try:
        if k == "top_category":
            t.update(title=f"{cat(e['category'])} আপনার সবচেয়ে বড় খরচের খাত",
                     pattern=f"{cat(e['category'])} খাতে খরচ {fm(e['amount'], cur)}, যা মোট খরচের {pct(e['share'])}।",
                     why="একটি খাত মোট খরচের ৩০%-এর বেশি হলে সেখানে ছোট পরিবর্তনেই মোট খরচ সবচেয়ে বেশি কমে।",
                     action=f"{cat(e['category'])} খাতের {e['count']}টি লেনদেন দেখে ঠিক করুন কোনগুলো বাধ্যতামূলক আর কোনগুলো পছন্দের।")
        elif k == "category_increase":
            t.update(title=f"{cat(e['category'])} খাতে খরচ বেড়েছে",
                     pattern=f"আগের সময়ে {fm(e['previous'], cur)} থেকে এখন {fm(e['current'], cur)} হয়েছে (বৃদ্ধি {fm(e['increase'], cur)})।",
                     why="হঠাৎ বড় বৃদ্ধি একবারের খরচ নাকি নতুন অভ্যাস, সেটা যাচাই করা ভালো।",
                     action=f"এই সময়ের {cat(e['category'])} খরচগুলো দেখে একবারের খরচগুলো আলাদা করে চিহ্নিত করুন।")
        elif k == "small_purchases":
            t.update(title="ছোট ছোট কেনাকাটা জমে যাচ্ছে",
                     pattern=f"{e['count']}টি ছোট কেনাকাটা মিলে {fm(e['total'], cur)} হয়েছে, যা মোট খরচের {pct(e['share'])}।",
                     why="ছোট অঙ্ক চোখে পড়ে না, কিন্তু মাস শেষে তা উল্লেখযোগ্য হতে পারে।",
                     action="সবচেয়ে কম দরকারি এক-দুটি অভ্যাসের জন্য সাপ্তাহিক একটি সীমা ঠিক করুন।")
        elif k == "frequent_merchant":
            t.update(title=f"{e['merchant']}-এ ঘনঘন খরচ",
                     pattern=f"{e['merchant']}-এ {e['count']}বার কেনাকাটায় মোট {fm(e['total'], cur)} খরচ হয়েছে।",
                     why="একই জায়গায় বারবার গেলে আগে থেকে পরিকল্পনা করে খরচ কমানো যায়।",
                     action=f"{e['merchant']}-এ সাপ্তাহিক পরিকল্পনা বা একসাথে কেনা কম খরচের হয় কি না দেখুন।")
        elif k == "unusual_day":
            t.update(title="একটি দিন আলাদাভাবে চোখে পড়ে",
                     pattern=f"{e['date']} তারিখে খরচ {fm(e['amount'], cur)}, যেখানে সাধারণ দিনে প্রায় {fm(e['typical_day'], cur)}।",
                     why="অস্বাভাবিক বড় দিন একবারের ঘটনা বা অপরিকল্পিত কেনাকাটা হতে পারে।",
                     action="ওই দিন কী হয়েছিল দেখুন; আর না হলে একবারের খরচ হিসেবে চিহ্নিত করুন।")
        elif k == "discretionary_share":
            t.update(title="খরচের বড় অংশ ঐচ্ছিক",
                     pattern=f"শ্রেণিবদ্ধ খরচের মধ্যে ঐচ্ছিক খরচ {fm(e['discretionary'], cur)}, আর দরকারি খরচ {fm(e['essential'], cur)}।",
                     why="বিল ও খাবারে হাত না দিয়ে যে অংশটুকু বদলানো যায়, সেটা ঐচ্ছিক খরচ।",
                     action="আগামী মাসে একটি ঐচ্ছিক খাতে সীমা বসান।")
        elif k == "low_savings":
            t.update(title="সঞ্চয়ের মতো টাকা কম থাকছে" if float(e["net_cash_flow"]) >= 0 else "খরচ আয়ের চেয়ে বেশি হয়েছে",
                     pattern=f"আয় {fm(e['income'], cur)}, খরচ {fm(e['spending'], cur)}, বাকি {fm(e['net_cash_flow'], cur)}।",
                     why="আয়ের প্রায় ১০%-এর কম সঞ্চয় করলে হঠাৎ প্রয়োজনের জন্য সামান্যই থাকে।",
                     action="বেতনের দিনই সঞ্চয় অ্যাকাউন্টে একটি নির্দিষ্ট অঙ্ক পাঠানোর ব্যবস্থা করুন, ছোট হলেও।")
        elif k == "subscriptions":
            t.update(title="নিয়মিত পেমেন্ট শনাক্ত হয়েছে",
                     pattern=f"{e['count']}টি নিয়মিত পেমেন্টে মাসে প্রায় {fm(e['monthly_total'], cur)} যাচ্ছে।",
                     why="সাবস্ক্রিপশন প্রতিবার সিদ্ধান্ত ছাড়াই নবায়ন হয়।",
                     action="প্রতিটি দেখে যেগুলো আর ব্যবহার করেন না সেগুলো বাতিল করুন।")
    except (KeyError, ValueError, TypeError):
        return i
    t["assumptions"] = [ASSUMPTIONS.get(a, a) for a in i.get("assumptions", [])]
    return t


def quality(q: str) -> str:
    if q.startswith("No accounts have been added"):
        return "কোনো অ্যাকাউন্ট যোগ করা হয়নি, তাই ব্যালান্স দেখানো যাচ্ছে না।"
    if q.startswith("The opening balance of "):
        name = q[len("The opening balance of "):].split(" is zero")[0]
        return f"{name}-এর শুরুর ব্যালান্স শূন্য। এর আগে টাকা থাকলে ব্যালান্স কম দেখাবে।"
    if q.startswith("No income was recorded"):
        return "এই সময়ে কোনো আয় লেখা হয়নি, তাই সঞ্চয়ের হার ও নিট নগদ প্রবাহ অর্থপূর্ণ নয়।"
    if q.startswith("Very few transactions"):
        return "এই সময়ে খুব কম লেনদেন লেখা হয়েছে, তাই প্যাটার্ন নির্ভরযোগ্য নাও হতে পারে।"
    if q.startswith("Accounts in another currency"):
        return "অন্য মুদ্রার অ্যাকাউন্ট মোটের বাইরে রাখা হয়েছে: " + q.split(": ", 1)[-1]
    if "future-dated" in q:
        return q.split(" ")[0] + "টি ভবিষ্যতের তারিখের লেনদেন পরিকল্পিত হিসেবে ধরা হয়েছে, বাস্তব নয়।"
    return q


def fallback_narrative(report: dict, acts: list, cur: str) -> dict:
    o = report["overview"]
    f = lambda v: fm(v, cur)
    quiet = o["income"] == "0.00" and o["spending"] == "0.00"
    return {"headline": "এই সময়ে এখনো যথেষ্ট লেনদেন লেখা হয়নি।" if quiet else f"{report['period']['label']}: আয় {f(o['income'])}, খরচ {f(o['spending'])}, নিট {f(o['net_cash_flow'])}।",
            "summary": " ".join(a["pattern"] for a in acts[:2]) or "এই সময়ে বিশেষ কোনো অস্বাভাবিক প্যাটার্ন পাওয়া যায়নি।",
            "findings": [{"title": a["title"], "what_we_saw": a["pattern"], "why_it_matters": a["why"], "suggested_action": a["action"],
                          "estimated_impact": a["estimated_impact"], "assumptions": a["assumptions"]} for a in acts],
            "caveats": [quality(q) for q in report["data_quality"]] + ["এই ব্যাখ্যা এআই সেবা ছাড়াই একই তথ্য থেকে তৈরি।"]}


def query_texts(cur: str) -> dict:
    return {"no_accounts": "আপনি এখনো কোনো অ্যাকাউন্ট যোগ করেননি, তাই ব্যালান্স দেখাতে পারছি না। অ্যাকাউন্টস পাতায় শুরুর ব্যালান্সসহ একটি যোগ করুন।",
            "no_budgets": "আপনার এখনো কোনো বাজেট নেই। প্ল্যান পাতায় বানাতে পারেন, অথবা আমাকে খাত আর সীমা বলুন।",
            "no_goals": "আপনার এখনো কোনো লক্ষ্য নেই। প্ল্যান পাতায় যোগ করতে পারেন।"}
