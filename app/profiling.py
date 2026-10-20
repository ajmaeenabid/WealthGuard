"""Adaptive questionnaire and risk scoring. Final bucket = LOWER of tolerance and capacity."""
import re
from typing import Optional

from app.config import BUCKET_ORDER, lower_bucket
from app.schemas import ClientProfile

QUESTIONS = [
    {"id": "age", "text": "How old are you?", "type": "number", "dim": "capacity", "w": 0.20},
    {"id": "horizon_years", "text": "In how many years do you need this money?", "type": "number",
     "dim": "capacity", "w": 0.30},
    {"id": "monthly_income_cny", "text": "What is your monthly income in CNY?", "type": "number",
     "dim": "capacity", "w": 0.10},
    {"id": "income_stability", "text": "How stable is your income?", "type": "choice", "dim": "capacity", "w": 0.20,
     "options": {"stable": ("Stable (salary or pension)", 80), "variable": ("Variable", 50),
                 "unstable": ("Unstable", 20)}},
    {"id": "liquidity_need_pct", "text": "What share of this money might you need on short notice?",
     "type": "choice", "dim": "capacity", "w": 0.20,
     "options": {0: ("None (0%)", 100), 10: ("About 10%", 80), 25: ("About 25%", 50), 40: ("40% or more", 20)}},
    {"id": "goal", "text": "What is the main goal for this money?", "type": "choice", "dim": "tolerance", "w": 0.20,
     "options": {"preservation": ("Preserve capital", 10), "income": ("Steady income", 30),
                 "education": ("Education fund", 40), "retirement": ("Retirement", 50),
                 "growth": ("Long-term growth", 90)}},
    {"id": "loss_reaction", "text": "If your portfolio fell 20% in a year, what would you do?", "type": "choice",
     "dim": "tolerance", "w": 0.50,
     "options": {"sell_all": ("Sell everything", 5), "sell_some": ("Sell some", 25),
                 "hold": ("Hold and wait", 60), "buy_more": ("Buy more", 90)}},
    {"id": "experience", "text": "What is your investing experience?", "type": "choice", "dim": "tolerance",
     "w": 0.30, "options": {"none": ("None", 10), "basic": ("Basic (funds, bonds)", 40),
                            "advanced": ("Advanced (derivatives, notes)", 90)}},
]
QBY = {q["id"]: q for q in QUESTIONS}


def infer(answers: dict) -> dict:
    out = {k: v for k, v in answers.items() if k != "_inferred"}
    inferred = {}
    h = out.get("horizon_years")
    if h is not None and float(h) < 2 and "liquidity_need_pct" not in out:
        inferred["liquidity_need_pct"] = 40
    if out.get("goal") == "preservation" and "loss_reaction" not in out:
        inferred["loss_reaction"] = "sell_some"
    out.update(inferred)
    out["_inferred"] = sorted(inferred)
    return out


def public_question(q: dict) -> dict:
    d = {"id": q["id"], "text": q["text"], "type": q["type"]}
    if q["type"] == "choice":
        d["options"] = [{"value": v, "label": lab} for v, (lab, _) in q["options"].items()]
    return d


def next_question(answers: dict) -> Optional[dict]:
    known = infer(answers)
    for q in QUESTIONS:
        if q["id"] not in known:
            return public_question(q)
    return None


def missing(answers: dict) -> list[str]:
    known = infer(answers)
    return [q["id"] for q in QUESTIONS if q["id"] not in known]


ZH_ALIASES = {
    "income_stability": [("unstable", ["不稳定", "不太稳定", "不固定", "无保障", "没保障"]),
                         ("variable", ["变动", "浮动", "自由职业", "项目", "不一定"]),
                         ("stable", ["稳定", "固定", "工资", "养老金", "退休金"])],
    "goal": [("preservation", ["保本", "保值", "保全", "保住本金", "资本保全"]),
             ("education", ["教育", "子女", "孩子", "学费", "留学"]),
             ("retirement", ["退休", "养老"]),
             ("growth", ["增长", "增值", "长期增长", "资产增值"]),
             ("income", ["收入", "现金流", "分红", "利息"])],
    "loss_reaction": [("sell_some", ["卖出一部分", "卖一部分", "部分卖出", "卖掉一些", "卖一些", "减仓"]),
                      ("sell_all", ["全部卖出", "全卖", "清仓", "全部抛售", "都卖"]),
                      ("buy_more", ["加仓", "买入更多", "再买", "多买", "补仓"]),
                      ("hold", ["持有", "等待", "不动", "拿着", "观望", "继续"])],
    "experience": [("none", ["没有经验", "无经验", "没经验", "新手", "零基础", "没有"]),
                   ("advanced", ["高级", "丰富", "专业", "衍生品", "结构性"]),
                   ("basic", ["基础", "基本", "一些", "有一点", "基金", "债券"])],
}
ZH_ZERO = ["不需要", "无需", "没有", "不用", "零"]


def _parse_zh(q: dict, text: str):
    if q["id"] == "liquidity_need_pct":
        m = re.search(r"\d+(\.\d+)?", text)
        if m:
            n = float(m.group())
            return min(q["options"], key=lambda v: abs(v - n))
        return 0 if any(w in text for w in ZH_ZERO) else None
    for value, words in ZH_ALIASES.get(q["id"], []):
        if any(w in text for w in words):
            return value
    return None


def parse_answer(qid: str, text: str):
    q = QBY.get(qid)
    if not q:
        return None
    t = str(text).strip().lower()
    if q["type"] == "number":
        m = re.search(r"\d+(\.\d+)?", t.replace(",", ""))
        return float(m.group()) if m else None
    for v, (lab, _) in q["options"].items():
        if t == str(v).lower() or t == lab.lower():
            return v
    if q["id"] == "liquidity_need_pct":
        m = re.search(r"\d+(\.\d+)?", t)
        if m:
            return min(q["options"], key=lambda v: abs(v - float(m.group())))
    for v, (lab, _) in q["options"].items():
        if str(v).lower() in t.replace(" ", "_") or lab.lower().split(" (")[0] in t:
            return v
    return _parse_zh(q, t)


def _score(q: dict, value) -> float:
    if q["id"] == "age":
        return max(0.0, min(100.0, 100 - (float(value) - 20) * 1.5))
    if q["id"] == "horizon_years":
        return max(0.0, min(100.0, float(value) * 5))
    if q["id"] == "monthly_income_cny":
        return max(0.0, min(100.0, float(value) / 300))
    key = int(float(value)) if q["id"] == "liquidity_need_pct" else value
    return float(q["options"][key][1])


def score_to_bucket(score: float) -> str:
    for limit, b in zip([20, 40, 60, 80], BUCKET_ORDER):
        if score < limit:
            return b
    return BUCKET_ORDER[-1]


def compute_scores(answers: dict) -> tuple[float, float]:
    a = infer(answers)
    res = {}
    for dim in ("tolerance", "capacity"):
        qs = [q for q in QUESTIONS if q["dim"] == dim]
        res[dim] = round(sum(_score(q, a[q["id"]]) * q["w"] for q in qs), 1)
    return res["tolerance"], res["capacity"]


def build_profile(client_id: str, answers: dict, name: str = "Client", extra: Optional[dict] = None) -> ClientProfile:
    miss = missing(answers)
    if miss:
        raise ValueError(f"missing answers: {miss}")
    a = infer(answers)
    tol, cap = compute_scores(answers)
    extra = extra or {}
    cap = round(max(0.0, cap - max(0.0, float(extra.get("behaviour_penalty", 0) or 0))), 1)
    bucket = lower_bucket(score_to_bucket(tol), score_to_bucket(cap))
    return ClientProfile(
        id=client_id, name=name, age=int(float(a["age"])), horizon_years=float(a["horizon_years"]),
        goal=str(a["goal"]), monthly_income_cny=float(a["monthly_income_cny"]),
        liquidity_need_pct=float(a["liquidity_need_pct"]), experience=a["experience"],
        risk_tolerance_score=tol, risk_capacity_score=cap, bucket=bucket,
        investable_amount_cny=float(extra.get("investable_amount_cny", 100000)),
        goal_target_cny=extra.get("goal_target_cny"),
    )
