"""Adaptive questionnaire and risk scoring. Final bucket = LOWER of tolerance and capacity."""
import re
from typing import Optional

from app.config import BUCKET_ORDER, lower_bucket
from app.schemas import ClientProfile

# Each question: id, text, dimension, weight within its dimension, options {value: (label, score)}.
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
    """Adaptive skipping: answers implied by earlier ones are filled in (and listed in _inferred)."""
    out = {k: v for k, v in answers.items() if k != "_inferred"}
    inferred = {}
    h = out.get("horizon_years")
    if h is not None and float(h) < 2 and "liquidity_need_pct" not in out:
        inferred["liquidity_need_pct"] = 40  # short horizon: assume high short-notice need
    if out.get("goal") == "preservation" and "loss_reaction" not in out:
        inferred["loss_reaction"] = "sell_some"  # capital-preservation goal implies low loss appetite
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


def parse_answer(qid: str, text: str):
    """Deterministic mapping of free text / clicked option to a canonical answer; None if unclear."""
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
    for v, (lab, _) in q["options"].items():
        if str(v).lower() in t.replace(" ", "_") or lab.lower().split(" (")[0] in t:
            return v
    return None


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
    bucket = lower_bucket(score_to_bucket(tol), score_to_bucket(cap))
    extra = extra or {}
    return ClientProfile(
        id=client_id, name=name, age=int(float(a["age"])), horizon_years=float(a["horizon_years"]),
        goal=str(a["goal"]), monthly_income_cny=float(a["monthly_income_cny"]),
        liquidity_need_pct=float(a["liquidity_need_pct"]), experience=a["experience"],
        risk_tolerance_score=tol, risk_capacity_score=cap, bucket=bucket,
        investable_amount_cny=float(extra.get("investable_amount_cny", 100000)),
        goal_target_cny=extra.get("goal_target_cny"),
    )
