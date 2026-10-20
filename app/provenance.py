"""Number provenance: "where does this number come from, and does it recompute?" """
import csv
import hashlib
import json
import os

from app import allocation as al
from app import realdata
from app import behaviour, config, ledger, profiling, simulator, store
from app.config import BUCKETS
from app.products import DATA, load_products

KINDS = ["tolerance", "capacity", "bucket", "expected_return", "volatility", "stress_loss", "goal_probability",
         "backtest_share", "ledger_total"]


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _manifest() -> dict:
    with open(os.path.join(os.path.dirname(DATA), "data", "real", "MANIFEST.json"), encoding="utf-8") as f:
        return {d["file"]: d for d in json.load(f)["datasets"]}


def _datasets(*files: str) -> list[dict]:
    m = _manifest()
    return [{"file": f, "sha256": m[f]["sha256"], "license": m[f]["license"], "url": m[f]["url"], "title": m[f]["title"]} for f in files]


def _products_input() -> dict:
    return {"name": "Synthetic product assumptions (products.json)", "value": "expected return, volatility, fee per product",
            "source": "synthetic, project-authored", "sha256": _sha(os.path.join(DATA, "products.json"))}


def _out(kind, label, value, display, formula, inputs, recomputed, datasets=None, extra=None):
    matches = None if recomputed is None else (abs(float(recomputed) - float(value)) < 1e-6)
    return {"ok": True, "kind": kind, "label": label, "value": value, "display": display, "formula": formula, "inputs": inputs,
            "datasets": datasets or [], "recomputed": recomputed, "matches": matches, **(extra or {})}


def _profile_parts(client_id: str, dim: str):
    d = store.load_client(client_id)
    facts = profiling.infer(d["facts"])
    rows = []
    for q in profiling.QUESTIONS:
        if q["dim"] != dim:
            continue
        v = facts[q["id"]]
        s = profiling._score(q, v)
        rows.append({"name": q["text"], "value": v, "source": "the client's answer" + (" (inferred)" if q["id"] in facts.get("_inferred", []) else ""),
                     "score": round(s, 1), "weight": q["w"], "contribution": round(s * q["w"], 2)})
    return d, rows


def _independent_stress(alloc, products, scenario: str) -> float | None:
    spec = simulator.EPISODES.get(scenario)
    if not spec:
        return None
    a, b = spec["years"]
    with open(os.path.join(realdata.DIR, "returns_annual.csv"), encoding="utf-8") as f:
        raw = {int(r["year"]): {k: float(v) for k, v in r.items() if k != "year"} for r in csv.DictReader(f)}
    total = 0.0
    for l in alloc.lines:
        growth = 1.0
        for y in range(a, b + 1):
            growth *= 1 + sum(w * raw[y][col] for col, w in realdata.ASSET_MIX[products[l.product_id].asset_class].items())
        total += l.weight * round((growth - 1) * 100, 1)
    return round(total, 2)


def explain(client_id: str, kind: str, allocation_id: str = "", scenario: str = "", shock_pct: float = 0.0) -> dict:
    if kind not in KINDS:
        return {"ok": False, "error": f"unknown kind; choose from {KINDS}"}
    d = store.load_client(client_id)
    if not d:
        return {"ok": False, "error": "unknown client"}
    prof = store.load_profile(client_id)
    products = load_products()

    if kind in ("tolerance", "capacity"):
        if not prof:
            return {"ok": False, "error": "no profile yet"}
        dim = "tolerance" if kind == "tolerance" else "capacity"
        d, rows = _profile_parts(client_id, dim)
        penalty = float((d.get("extra") or {}).get("behaviour_penalty_applied", 0) or 0) if dim == "capacity" else 0.0
        tol, cap = profiling.compute_scores(d["facts"])
        base = tol if dim == "tolerance" else cap
        recomputed = base if dim == "tolerance" else round(max(0.0, base - penalty), 1)
        inputs = rows + ([{"name": "Behaviour penalty", "value": -penalty, "source": "purchase-history insights (can only lower capacity)"}] if penalty else [])
        value = prof.risk_tolerance_score if dim == "tolerance" else prof.risk_capacity_score
        return _out(kind, f"Risk {dim}", value, f"{value:g}/100",
                    "sum of (option score x question weight) over the " + dim + " questions" + (", minus the behaviour penalty" if dim == "capacity" else ""),
                    inputs, recomputed, extra={"rule": "profiling.py; lower of tolerance and capacity decides the bucket"})

    if kind == "bucket":
        if not prof:
            return {"ok": False, "error": "no profile yet"}
        tb, cb = profiling.score_to_bucket(prof.risk_tolerance_score), profiling.score_to_bucket(prof.risk_capacity_score)
        eff = config.effective_bucket(prof.bucket, prof.age, prof.horizon_years)
        lim = BUCKETS[eff]
        inputs = [{"name": "Tolerance bucket", "value": tb, "source": f"score {prof.risk_tolerance_score:g}; bands <20, <40, <60, <80, else"},
                  {"name": "Capacity bucket", "value": cb, "source": f"score {prof.risk_capacity_score:g}"},
                  {"name": "Final bucket = the lower of the two", "value": prof.bucket, "source": "CLAUDE rule: real advisors use the lower"},
                  {"name": "Effective bucket after R5 (age 65+ or horizon under 2 years cap at Moderate)", "value": eff,
                   "source": f"age {prof.age}, horizon {prof.horizon_years:g} years"},
                  {"name": "Limits", "value": f"max risk {lim['max_risk']}, equity-like {lim['max_equity_pct']}%, single product {lim['max_single_pct']}%",
                   "source": "config.BUCKETS (project risk-bucket table)"}]
        recomputed = config.lower_bucket(tb, cb)
        return {"ok": True, "kind": kind, "label": "Risk bucket", "value": prof.bucket, "display": f"{prof.bucket}" + (f" (capped to {eff})" if eff != prof.bucket else ""),
                "formula": "lower of the tolerance bucket and the capacity bucket, then the R5 cap", "inputs": inputs, "datasets": [],
                "recomputed": recomputed, "matches": recomputed == prof.bucket}

    if kind in ("expected_return", "volatility", "stress_loss", "goal_probability", "backtest_share"):
        alloc = store.load_allocation(allocation_id) if allocation_id else store.latest_allocation(client_id)
        if not alloc or alloc.client_id != client_id or not prof:
            return {"ok": False, "error": "no compliance-approved allocation for this client"}
        lines = [{"name": products[l.product_id].name, "value": f"{l.weight:.1%}", "source": "allocation line",
                  "detail": f"expected return {products[l.product_id].expected_return:.1%}, fee {products[l.product_id].annual_fee_pct}%, "
                            f"volatility {products[l.product_id].volatility:.1%}"} for l in alloc.lines]
        w = {l.product_id: l.weight for l in alloc.lines}
        ret, vol = al.portfolio_stats(w, products)

        if kind == "expected_return":
            return _out(kind, "Expected net return", alloc.expected_return, f"{alloc.expected_return:.2%} a year",
                        "sum over lines of weight x (product expected return - annual fee)", lines + [_products_input()], ret)
        if kind == "volatility":
            return _out(kind, "Volatility", alloc.volatility, f"{alloc.volatility:.2%}",
                        f"square root of the sum over line pairs of weight_i x weight_j x correlation x vol_i x vol_j (correlation {al.RHO} between different products, 1 for the same)",
                        lines + [_products_input()], vol)

        if kind == "stress_loss":
            if scenario not in simulator.SCENARIOS:
                return {"ok": False, "error": f"unknown scenario; choose from {sorted(simulator.SCENARIOS)}"}
            st = simulator.stress(alloc, products, scenario)
            sc = simulator.SCENARIOS[scenario]
            by = [{"name": x["name"], "value": f"{x['weight']:.1%} x {x['shock_pct']:+.1f}%", "source": "weight x shock of its asset class",
                   "contribution": x["contribution_pct"]} for x in st["by_line"]]
            ds = _datasets("returns_annual.csv", "shiller_monthly.csv") if sc["basis"]["type"] == "historical" else []
            return _out(kind, f"Portfolio change: {sc['label']}", st["loss_pct"], f"{st['loss_pct']:+.2f}%",
                        "sum over lines of weight x the shock of the line's asset class; the shocks are " +
                        ("the compounded real returns of the named years" if ds else "a hypothetical round-number shock"),
                        by + [{"name": "Basis", "value": sc["basis"]["note"], "source": sc["basis"]["source"] or "hypothetical"}],
                        _independent_stress(alloc, products, scenario) if ds else st["loss_pct"], ds,
                        extra={"independent_recomputation": bool(ds)})
        if kind == "goal_probability":
            g = simulator.goal_projection(alloc, prof, shock_pct)
            g2 = simulator.goal_projection(alloc, prof, shock_pct)
            inputs = [{"name": "Start amount", "value": g["start_cny"], "source": f"investable CNY {prof.investable_amount_cny:,.0f}" + (f" after a {shock_pct:+.1f}% shock" if shock_pct else "")},
                      {"name": "Goal", "value": g["target_cny"], "source": "client goal"},
                      {"name": "Years", "value": g["years"], "source": "client horizon"},
                      {"name": "Expected return / volatility", "value": f"{alloc.expected_return:.2%} / {alloc.volatility:.2%}", "source": "allocation (synthetic product assumptions)"},
                      {"name": "Method", "value": f"{g['paths']:,} lognormal paths, seed {config.MC_SEED}", "source": "simulator.goal_projection"}]
            return _out(kind, "Chance of reaching the goal", g["probability"], f"{g['probability']:.0%}",
                        "share of simulated paths whose final value reaches the goal", inputs, g2["probability"])
        h = simulator.historical_backtest(alloc, products, prof)
        h2 = simulator.historical_backtest(alloc, products, prof)
        inputs = [{"name": "Windows", "value": f"{h['windows']} rolling {h['years']}-year windows, {h['first_year']}-{h['last_year']}", "source": "real US annual returns"},
                  {"name": "Reached the goal", "value": f"{h['windows_reaching_target']} of {h['windows']}", "source": "windows whose final value >= the goal"},
                  {"name": "Worst window", "value": f"starting {h['worst_start_year']}, ended at CNY {h['worst_cny']:,.0f}", "source": "backtest"},
                  {"name": "Median / best", "value": f"CNY {h['median_cny']:,.0f} / CNY {h['best_cny']:,.0f}", "source": "backtest"},
                  {"name": "Fees", "value": "weighted annual product fees are deducted each year", "source": "products.json"}]
        return _out(kind, "Share of historical windows reaching the goal", h["share_reaching_target"], f"{h['share_reaching_target']:.0%}",
                    "for every real rolling window, compound the allocation's mapped asset-class returns minus fees; count windows ending at or above the goal",
                    inputs, h2["share_reaching_target"], _datasets("returns_annual.csv"))

    insights = behaviour.insights(client_id)
    bought = [e for e in ledger.list_entries(client_id) if e.status == "bought"]
    rows = [{"name": e.item, "value": f"CNY {e.amount_cny:,.0f}", "source": f"{e.ts}, {e.category}, entered by {e.source}"} for e in bought]
    total = sum(e.amount_cny for e in bought)
    return _out(kind, "Bought total", insights["bought_total"], f"CNY {insights['bought_total']:,.0f}",
                "sum of the entries with status 'bought' (planned and cancelled items are not counted)", rows, round(total, 2))
