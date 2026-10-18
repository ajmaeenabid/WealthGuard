"""Knowledge base for retrieval: the real CSRC regulation text, the real-data sources and episodes, and our own rules.

Sources (all indexed in app/vectorstore.py):
  csrc_suitability  43 articles of the Suitability Management Measures (Chinese original, real, public)
  data_sources      where each real dataset comes from, its license and what it is used for (MANIFEST.json)
  market_episodes   the real historical episodes behind the stress scenarios
  wealthguard_rules our compliance rules R1-R8 in plain English, with the regulatory articles they relate to
  history_cards     real yearly US returns, China macro data and decade averages, as short text cards
"""
import hashlib
import json
import os
import re
import threading

from app import realdata, simulator, vectorstore

REAL = realdata.DIR
GAZETTE = "https://www.gov.cn/gongbao/content/2023/content_5742209.htm"
_LOCK = threading.RLock()

# English phrase -> Chinese terms used in the regulation, so English questions can reach Chinese text.
GLOSSARY = {
    "suitab": "适当性 适当性匹配", "risk tolerance": "风险承受能力", "risk capacity": "风险承受能力",
    "risk level": "产品或者服务风险等级 划分风险等级", "risk rating": "产品或者服务风险等级 划分风险等级",
    "classified": "划分风险等级", "risk grade": "划分风险等级", "high risk": "高风险", "high-risk": "高风险",
    "complex": "结构复杂性 复杂性", "complexity": "结构复杂性 复杂性", "structured": "结构复杂性",
    "professional investor": "专业投资者", "ordinary investor": "普通投资者", "retail investor": "普通投资者",
    "retail client": "普通投资者", "disclos": "告知 警示 风险揭示", "risk warning": "风险警示 告知",
    "inform": "告知", "warn": "警示", "guarantee": "保证 确定性的判断", "promise": "保证 确定性的判断",
    "certain": "确定性的判断", "misleading": "误导性陈述 虚假记载", "liquidity": "流动性", "lock": "到期时限",
    "maturity": "到期时限", "leverage": "杠杆情况", "principal": "本金亏损", "lose": "本金亏损 损失",
    "loss": "本金亏损 损失", "elderly": "年龄 特别保护", "age": "年龄", "old": "年龄", "vulnerable": "特别保护 年龄",
    "protect": "特别保护 合法权益", "income": "收入来源", "debt": "债务", "experience": "投资知识和经验",
    "knowledge": "投资知识和经验", "investment goal": "投资期限 投资品种 预期收益", "horizon": "投资期限",
    "recommend": "适当性匹配意见", "advice": "适当性匹配意见", "match": "适当性匹配", "dispute": "纠纷 调解",
    "complaint": "纠纷 调解", "mediat": "调解", "record": "保存 录音 录像", "penalt": "责令改正 警告 罚款",
    "fine": "罚款", "sanction": "责令改正 警告 罚款", "supervis": "监督管理 中国证监会", "bear the": "独立承担投资风险", "bears": "独立承担投资风险", "investor responsib": "独立承担投资风险",
    "fund": "基金", "futures": "期货", "security": "证券", "securities": "证券", "sell": "销售", "sale": "销售",
    "internal": "内部管理制度", "self-inspection": "自查", "audit": "自查 检查", "refus": "不适合 不得",
    "prohibit": "禁止", "forbid": "禁止", "not suitable": "不适合", "unsuitable": "不适合 不符合准入要求",
    "insist": "主动要求购买", "customer asks": "主动要求购买", "insists": "主动要求购买", "client asks": "主动要求购买",
    "update": "信息发生重要变化", "change": "信息发生重要变化", "classif": "投资者分类", "categor": "投资者分类",
    "convert": "互相转化", "agent": "代销", "distribut": "代销 委托销售",
}

RULE_QUERIES = {  # fixed Chinese retrieval queries; the best-matching article is shown as the regulatory basis
    "R1": "根据产品或者服务的不同风险等级 对其适合销售产品的投资者类型作出判断 适当性匹配",
    "R3": "划分产品或者服务风险等级时应当综合考虑 结构复杂性 杠杆情况",
    "R4": "产品风险等级 流动性 到期时限 投资期限",
    "R5": "普通投资者 特别保护 年龄 风险承受能力 高风险产品 特别的注意义务",
    "R6": "销售产品或者提供服务前 应当告知下列信息 可能直接导致本金亏损的事项",
    "R7": "禁止 向投资者就不确定事项提供确定性的判断 误导性陈述",
}
BASIS_MIN_SCORE = 0.10

RULE_DOCS = [
    ("R1", "Suitability", "Every product's risk level must not exceed the client's final risk bucket (the lower of risk "
     "tolerance and capacity).", ["第十八条", "第三条"]),
    ("R2", "Concentration", "No single product may exceed the bucket's single-product cap.", []),
    ("R3", "Complexity", "Complex products such as structured notes require advanced investing experience, "
     "otherwise they are blocked.", ["第十六条", "第十七条"]),
    ("R4", "Liquidity", "Products locked up beyond the client's horizon are not allowed, and liquid assets must cover the "
     "client's short-notice need.", ["第十六条"]),
    ("R5", "Vulnerable client", "Clients aged 65 or older, or with a horizon under 2 years, are capped at the Moderate "
     "bucket regardless of their score.", ["第七条", "第二十条"]),
    ("R6", "Disclosures", "Client-facing allocation text must include a risk warning, a fee summary and a past-performance "
     "disclaimer.", ["第二十三条", "第二十四条"]),
    ("R7", "Language", "Guaranteed, risk-free or can't-lose wording, in English or Chinese, is rejected in any "
     "client-facing text.", ["第二十二条", "第二十四条"]),
    ("R8", "Minimums", "Every allocation line must meet the product's minimum investment amount.", []),
]


def expand(query: str) -> str:
    """Append Chinese regulation terms for the English key phrases found in the query."""
    q = query.lower()
    extra = [zh for en, zh in GLOSSARY.items() if en in q]
    return query + (" " + " ".join(extra) if extra else "")


SERIES = [("sp500", "S&P 500 (with dividends)"), ("small_cap", "US small caps"), ("tbill_3m", "3-month T-bills"),
          ("tbond_10y", "10-year T-bonds"), ("baa_corp", "Baa corporate bonds"), ("real_estate", "US real estate"),
          ("gold", "gold")]
US_KEYWORDS = "美国 标普500 小盘股 国库券 国债 公司债 房地产 黄金 通胀 利率 历史 年度回报"
CN_KEYWORDS = "中国 通货膨胀 通胀 存款利率 贷款利率 GDP 经济增长 实际存款回报 历史"
DAMODARAN_PAGE = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histretSP.html"
WORLD_BANK_PAGE = "https://data.worldbank.org/country/china"


def _p(x: float) -> str:
    return f"{x * 100:+.1f}%"


def history_items() -> list[dict]:
    """Short text cards generated from the real CSVs: one per US year, one per China year, one per decade."""
    out = []
    rets = realdata.annual_returns()
    for y in realdata.years():
        r = rets[y]
        parts = ", ".join(f"{label} {_p(r[k])}" for k, label in SERIES)
        best = max(SERIES, key=lambda kv: r[kv[0]])[1]
        worst = min(SERIES, key=lambda kv: r[kv[0]])[1]
        infl, rate = realdata.inflation_pct(y), realdata.year_end_rate(y)
        extra = (f" US CPI inflation (Dec to Dec) was {infl:.1f}%." if infl is not None else "") + \
                (f" The 10-year rate ended the year at {rate:.2f}%." if rate is not None else "")
        out.append({"id": f"history:US-{y}", "source": "history_cards", "ref": f"US-{y}", "lang": "en",
                    "title": f"{y} US market returns", "url": DAMODARAN_PAGE,
                    "text": f"In {y} (US) annual returns were: {parts}. Best: {best}. Worst: {worst}.{extra} {US_KEYWORDS}"})
    for y, m in sorted(realdata.china_macro().items()):
        bits = []
        if m["cpi_inflation_pct"] is not None:
            bits.append(f"CPI inflation {m['cpi_inflation_pct']:.1f}%")
        if m["deposit_rate_pct"] is not None:
            bits.append(f"deposit rate {m['deposit_rate_pct']:.2f}%")
        if m["lending_rate_pct"] is not None:
            bits.append(f"lending rate {m['lending_rate_pct']:.2f}%")
        if m["gdp_growth_pct"] is not None:
            bits.append(f"GDP growth {m['gdp_growth_pct']:.1f}%")
        real = ""
        if m["deposit_rate_pct"] is not None and m["cpi_inflation_pct"] is not None:
            d = m["deposit_rate_pct"] - m["cpi_inflation_pct"]
            real = f" Real deposit return (deposit rate minus inflation) was about {d:+.1f} points."
        out.append({"id": f"history:CN-{y}", "source": "history_cards", "ref": f"CN-{y}", "lang": "en",
                    "title": f"{y} China macro data", "url": WORLD_BANK_PAGE,
                    "text": f"In {y} (China): {', '.join(bits)}.{real} {CN_KEYWORDS}"})
    decades = sorted({y // 10 * 10 for y in realdata.years()})
    for d in decades:
        ys = [y for y in realdata.years() if d <= y < d + 10]
        avg = lambda k: sum(rets[y][k] for y in ys) / len(ys)
        worst_y = min(ys, key=lambda y: rets[y]["sp500"])
        infls = [x for x in (realdata.inflation_pct(y) for y in ys) if x is not None]
        inf = f" Average US CPI inflation {sum(infls) / len(infls):.1f}% a year." if infls else ""
        span = f"{ys[0]}-{ys[-1]}"
        parts = ", ".join(f"{label} {_p(avg(k))}" for k, label in SERIES)
        out.append({"id": f"history:DECADE-{d}s", "source": "history_cards", "ref": f"DECADE-{d}s", "lang": "en",
                    "title": f"{d}s US market averages", "url": DAMODARAN_PAGE,
                    "text": f"The {d}s decade ({span}, US) average annual returns: {parts}. The worst S&P 500 year was {worst_y} "
                            f"({_p(rets[worst_y]['sp500'])}).{inf} {US_KEYWORDS}"})
    return out


def _read(name: str):
    with open(os.path.join(REAL, name), encoding="utf-8") as f:
        return json.load(f)


def items() -> list[dict]:
    doc = _read("suitability_zh.json")
    out = []
    for a in doc["articles"]:
        n = a["article"]
        out.append({"id": f"csrc:{n}", "source": "csrc_suitability", "ref": n, "lang": "zh",
                    "title": f"证券期货投资者适当性管理办法 {n}", "text": a["text"], "url": doc["source_url"]})
    for d in _read("MANIFEST.json")["datasets"]:
        out.append({"id": f"data:{d['file']}", "source": "data_sources", "ref": d["file"], "lang": "en",
                    "title": d["title"], "url": d["page"],
                    "text": f"{d['title']}. Author: {d['author']}. License: {d['license']}. Used for: {d['used_for']}."})
    for k, v in simulator.SCENARIOS.items():
        b = v["basis"]
        out.append({"id": f"episode:{k}", "source": "market_episodes", "ref": k, "lang": "en", "title": v["label"],
                    "url": "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histretSP.html",
                    "text": f"{v['label']} ({b['type']}). {b['note']}"})
    for rid, name, text, arts in RULE_DOCS:
        basis = f" Related regulation: {', '.join(arts)} of the CSRC Suitability Measures." if arts else ""
        out.append({"id": f"rule:{rid}", "source": "wealthguard_rules", "ref": rid, "lang": "en",
                    "title": f"{rid} {name}", "text": text + basis, "url": ""})
    return out + history_items()


def _fingerprint(its: list[dict]) -> str:
    h = hashlib.sha256()
    h.update(f"v1|{vectorstore.DIM}".encode())
    for it in its:
        h.update(json.dumps(it, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()


def ensure_index() -> int:
    """Build the index if missing or stale (data or code changed). Cheap: about 60 chunks."""
    its = items()
    fp = _fingerprint(its)
    with _LOCK:
        if vectorstore.fingerprint() != fp:
            vectorstore.build(its, fp)
        else:
            vectorstore.ensure_remote(fp)
    return len(its)


def search(query: str, k: int = 3, source: str | None = None, min_score: float = 0.0) -> list[dict]:
    ensure_index()
    return vectorstore.search(expand(query), k=k, source=source, min_score=min_score)


def search_ex(query: str, k: int = 3, source: str | None = None, min_score: float = 0.0):
    """Like search, but also returns which backend answered ('qdrant' or 'local')."""
    ensure_index()
    return vectorstore.search_ex(expand(query), k=k, source=source, min_score=min_score)


def basis_for_rule(rule_id: str) -> dict | None:
    """The CSRC article that best supports a compliance rule, or None when no article is a close match."""
    q = RULE_QUERIES.get(rule_id)
    if not q:
        return None
    ensure_index()
    hits = vectorstore.search(q, k=1, source="csrc_suitability", min_score=BASIS_MIN_SCORE)
    if not hits:
        return None
    h = hits[0]
    snippet = h["text"][:70] + ("…" if len(h["text"]) > 70 else "")
    return {"rule_id": rule_id, "article": h["ref"], "article_no": article_number(h["ref"]), "text": h["text"],
            "snippet": snippet, "score": h["score"], "url": h["url"],
            "source": "CSRC Suitability Management Measures"}


def article_number(ref: str) -> int:
    """第十六条 -> 16"""
    digits = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    s = re.sub(r"[第条]", "", ref)
    if "百" in s:
        raise ValueError(ref)
    if "十" in s:
        a, _, b = s.partition("十")
        return (digits[a] if a else 1) * 10 + (digits[b] if b else 0)
    return digits[s]
