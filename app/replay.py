"""Revealed-risk replay: live through a real market episode with your own money and see what you actually do.

The client's compliance-approved allocation (or a 100% stock portfolio) is replayed month by month through a real episode using the
real data (S&P 500 monthly price index from Shiller; annual Damodaran returns spread evenly over the months for bonds, cash and gold).
At each first-time drawdown of 10%, 20% and 30% from the peak the client chooses to hold, sell some, sell all or buy more. At the end
we compare the choice made at the -20% point with the answer given to the questionnaire ("if your portfolio fell 20%..."): if the client
behaved more cautiously than they said, they may apply it to the profile. Behaviour can only make the profile *more* cautious: a bolder
reaction never changes it. Nothing is applied without an explicit click.
"""
from collections import OrderedDict

from app import realdata, store
from app.products import load_products
from app.security import audit

EPISODES = {
    "crash_2008": ("2007-10", "2009-12", "2008 financial crisis"),
    "dotcom_bust": ("2000-03", "2002-12", "Dot-com bust"),
    "rate_+2": ("2021-12", "2022-12", "2022 rate shock"),
    "great_depression": ("1929-09", "1932-06", "Great Depression"),
    "inflation_spike": ("1973-01", "1974-12", "1970s inflation and oil shock"),
}
CHOICES = ["hold", "sell_some", "sell_all", "buy_more"]
LABELS = {"hold": "Hold and wait", "sell_some": "Sell some (25% to cash)", "sell_all": "Sell everything to cash",
          "buy_more": "Buy more (add 10% of the starting amount)"}
THRESHOLDS = [-0.10, -0.20, -0.30]
REACTION_ORDER = ["sell_all", "sell_some", "hold", "buy_more"]   # most cautious first (same keys as the questionnaire)
SESSIONS: "OrderedDict[str, dict]" = OrderedDict()
MAX_SESSIONS = 200
NOTE = ("Replay of real market history using the S&P 500 monthly price index (dividends omitted) and annual bond, cash and gold returns "
        "spread over the months; past performance is not a reliable indicator of future results.")


def _shiller_prices() -> dict:
    return {m: float(r["sp500"]) for m, r in realdata._shiller().items()}


def months(episode: str) -> list[str]:
    a, b, _ = EPISODES[episode]
    return [m for m in sorted(realdata._shiller()) if a <= m <= b]


def _annual_monthly(col: str, year: int) -> float:
    return (1 + realdata.annual_returns()[year][col]) ** (1 / 12) - 1


def month_return(weights: dict, fee_annual: float, prices: dict, prev: str, cur: str) -> float:
    eq = prices[cur] / prices[prev] - 1
    year = int(cur[:4])
    cache = {"sp500": eq}
    r = 0.0
    for cls, w in weights.items():
        part = 0.0
        for col, cw in realdata.ASSET_MIX[cls].items():
            part += cw * (cache["sp500"] if col == "sp500" else _annual_monthly(col, year))
        r += w * part
    return r - fee_annual / 12


def _weights(alloc, portfolio: str) -> tuple[dict, float]:
    if portfolio == "equity":
        return {"equity_fund": 1.0}, 0.0
    products, w, fee = load_products(), {}, 0.0
    for l in alloc.lines:
        p = products[l.product_id]
        w[p.asset_class] = w.get(p.asset_class, 0.0) + l.weight
        fee += l.weight * p.annual_fee_pct / 100
    return w, fee


def start(client_id: str, episode: str, portfolio: str = "mine") -> dict:
    if episode not in EPISODES:
        return {"ok": False, "error": f"unknown episode; choose from {sorted(EPISODES)}"}
    if portfolio not in ("mine", "equity"):
        return {"ok": False, "error": "portfolio must be 'mine' or 'equity'"}
    d, prof, alloc = store.load_client(client_id), store.load_profile(client_id), store.latest_allocation(client_id)
    if not d or not prof or not alloc:
        return {"ok": False, "error": "needs a profile and a compliance-approved allocation first"}
    weights, fee = _weights(alloc, portfolio)
    ms = months(episode)
    prices = _shiller_prices()
    sid = store.new_id("rpl")
    s = {"id": sid, "client_id": client_id, "episode": episode, "label": EPISODES[episode][2], "portfolio": portfolio,
         "weights": weights, "fee": fee, "months": ms, "i": 0, "start": prof.investable_amount_cny,
         "risky": prof.investable_amount_cny, "cash": 0.0, "added": 0.0, "peak": prof.investable_amount_cny,
         "held": prof.investable_amount_cny, "history": [], "decisions": [], "triggered": [], "state": "running",
         "prompt": None, "result": None, "stated": d["facts"].get("loss_reaction"), "applied": False}
    s["history"].append({"month": ms[0], "value": round(prof.investable_amount_cny, 2)})
    SESSIONS[sid] = s
    while len(SESSIONS) > MAX_SESSIONS:
        SESSIONS.popitem(last=False)
    audit.append("client", "replay_started", "T1", {"episode": episode, "portfolio": portfolio, "session": sid}, client_id)
    _advance(s, prices)
    return _view(s)


def _value(s) -> float:
    return s["risky"] + s["cash"]


def _advance(s: dict, prices: dict) -> None:
    ms = s["months"]
    while s["i"] < len(ms) - 1:
        prev, cur = ms[s["i"]], ms[s["i"] + 1]
        s["i"] += 1
        r = month_return(s["weights"], s["fee"], prices, prev, cur)
        s["risky"] *= 1 + r
        s["held"] *= 1 + r
        s["cash"] *= 1 + _annual_monthly("tbill_3m", int(cur[:4]))
        v = _value(s)
        s["peak"] = max(s["peak"], v)
        s["history"].append({"month": cur, "value": round(v, 2)})
        dd = v / s["peak"] - 1
        hit = [t for t in THRESHOLDS if dd <= t and t not in s["triggered"]]
        if hit:
            t = min(hit)
            s["triggered"] += [x for x in THRESHOLDS if x >= t and x not in s["triggered"]]
            s["state"], s["prompt"] = "decision", {"month": cur, "drawdown": round(dd, 4), "threshold": t,
                                                   "value": round(v, 2), "peak": round(s["peak"], 2), "choices": CHOICES,
                                                   "labels": LABELS}
            return
    s["state"], s["prompt"] = "done", None
    s["result"] = _result(s)
    audit.append("client", "replay_finished", "T1", {"session": s["id"], "episode": s["episode"], "portfolio": s["portfolio"],
                                                     "decisions": [d["choice"] for d in s["decisions"]],
                                                     "comparison": s["result"]["comparison"]}, s["client_id"])


def _result(s: dict) -> dict:
    v = [h["value"] for h in s["history"]]
    peak, worst = v[0], 0.0
    for x in v:
        peak = max(peak, x)
        worst = min(worst, x / peak - 1)
    # What the client did when the drop reached -20% (the questionnaire's situation), plus any cautious move at the milder -10% point:
    # someone who sold everything at -10% has shown how they react to -20%, even though the portfolio then never fell further.
    at20 = next((d for d in s["decisions"] if d["threshold"] <= -0.20), None)
    earlier_sells = [d["choice"] for d in s["decisions"] if d["threshold"] > -0.20 and d["choice"] in ("sell_all", "sell_some")]
    cands = ([at20["choice"]] if at20 else []) + earlier_sells
    stated = s["stated"]
    if not cands or stated not in REACTION_ORDER:
        comparison, revealed = "not_tested", None
    else:
        revealed = min(cands, key=REACTION_ORDER.index)  # the most cautious of them
        comparison = "more_cautious" if REACTION_ORDER.index(revealed) < REACTION_ORDER.index(stated) else "same_or_bolder"
    final = _value(s)
    return {"final_value": round(final, 2), "held_value": round(s["held"], 2), "contributions": round(s["added"], 2),
            "worst_drawdown": round(worst, 4), "decisions": s["decisions"], "stated_loss_reaction": stated,
            "revealed_loss_reaction": revealed, "comparison": comparison,
            "cost_of_acting": round(final - s["added"] - s["held"], 2),
            "can_apply": comparison == "more_cautious", "note": NOTE}


def _view(s: dict) -> dict:
    return {"ok": True, "id": s["id"], "episode": s["episode"], "label": s["label"], "portfolio": s["portfolio"],
            "state": s["state"], "month": s["months"][s["i"]], "progress": [s["i"], len(s["months"]) - 1],
            "history": s["history"], "prompt": s["prompt"], "decisions": s["decisions"], "result": s["result"],
            "applied": s["applied"], "note": NOTE}


def step(session_id: str, client_id: str, choice: str | None) -> dict:
    s = SESSIONS.get(session_id)
    if not s or s["client_id"] != client_id:
        return {"ok": False, "error": "replay not found for this client", "status": 403}
    if s["state"] != "decision":
        return {"ok": False, "error": "no decision is pending", "status": 409}
    if choice not in CHOICES:
        return {"ok": False, "error": f"choice must be one of {CHOICES}", "status": 422}
    p = s["prompt"]
    if choice == "sell_some":
        moved = 0.25 * s["risky"]
        s["risky"] -= moved
        s["cash"] += moved
    elif choice == "sell_all":
        s["cash"] += s["risky"]
        s["risky"] = 0.0
    elif choice == "buy_more":
        add = 0.10 * s["start"]
        s["risky"] += add
        s["added"] += add  # the "held everything" comparison never adds money
    s["decisions"].append({"month": p["month"], "drawdown": p["drawdown"], "threshold": p["threshold"], "choice": choice})
    s["state"], s["prompt"] = "running", None
    _advance(s, _shiller_prices())
    out = _view(s)
    out["ok"] = True
    return out


def apply(session_id: str, client_id: str) -> dict:
    """Apply the revealed reaction to the profile. Only if the client acted more cautiously than they answered."""
    s = SESSIONS.get(session_id)
    if not s or s["client_id"] != client_id:
        return {"ok": False, "error": "replay not found for this client", "status": 403}
    r = s["result"]
    if s["state"] != "done" or not r or not r["can_apply"] or s["applied"]:
        return {"ok": False, "error": "nothing to apply: the replay is unfinished, did not show a more cautious reaction, or was already applied",
                "status": 409}
    d = store.load_client(client_id)
    before = d["facts"].get("loss_reaction")
    if REACTION_ORDER.index(r["revealed_loss_reaction"]) >= REACTION_ORDER.index(before):
        return {"ok": False, "error": "behaviour can only make the profile more cautious", "status": 409}
    d["facts"]["loss_reaction"] = r["revealed_loss_reaction"]
    d["profile"] = None  # recomputed from the new answer
    store.save_client(client_id, d)
    s["applied"] = True
    audit.append("client", "replay_applied", "T1", {"session": session_id, "from": before, "to": r["revealed_loss_reaction"]}, client_id)
    return {"ok": True, "from": before, "to": r["revealed_loss_reaction"], "note": "Your loss-reaction answer is now the more cautious one; the profile will be recomputed."}


def reset() -> None:
    SESSIONS.clear()
