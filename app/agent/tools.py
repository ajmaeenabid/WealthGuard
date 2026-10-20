"""Tool definitions the agent may call. Every call goes through security.tiers.execute (never directly)."""
from dataclasses import dataclass
from typing import Callable, Literal, Optional

from pydantic import Field

from app import allocation as al
from app import behaviour, comparison, compliance, config, counterfactual, knowledge, profiling, simulator, state, store
from app.products import load_products
from app.schemas import ClientProfile, OrderTicket, StrictArgs
from app.security import audit


@dataclass
class Ctx:
    client_id: str
    denied: frozenset = frozenset()


class NoArgs(StrictArgs):
    pass


class ListProductsArgs(StrictArgs):
    asset_class: Optional[str] = None


class CompareArgs(StrictArgs):
    product_ids: list[str] = Field(max_length=15)


class SearchKnowledgeArgs(StrictArgs):
    query: str = Field(min_length=2, max_length=300)
    k: int = Field(default=3, ge=1, le=5)
    source: Optional[Literal["csrc_suitability", "data_sources", "market_episodes", "wealthguard_rules", "history_cards"]] = None


class ProductIdArgs(StrictArgs):
    product_id: str = Field(min_length=2, max_length=20)


class ProposeArgs(StrictArgs):
    preferred_ids: list[str] = Field(default_factory=list, max_length=5)
    exclude_ids: list[str] = Field(default_factory=list, max_length=15)
    summary: str = Field(default="", max_length=1500)


class AllocIdArgs(StrictArgs):
    allocation_id: str = Field(max_length=64)


class StressArgs(StrictArgs):
    allocation_id: str = Field(max_length=64)
    scenario: str = Field(max_length=40)


class GoalArgs(StrictArgs):
    allocation_id: str = Field(max_length=64)
    shock_pct: float = Field(default=0.0, ge=-100, le=100)


@dataclass
class Tool:
    name: str
    tier: str
    args: type
    handler: Callable
    description: str


def _fail(msg: str) -> dict:
    return {"ok": False, "error": msg}


def _facts(client_id: str) -> dict:
    d = store.load_client(client_id) or {}
    return d.get("facts", {})


def list_products(a: ListProductsArgs, ctx: Ctx) -> dict:
    ps = [comparison.row(p) for p in load_products().values() if not a.asset_class or p.asset_class == a.asset_class]
    return {"products": ps}


def search_knowledge(a: SearchKnowledgeArgs, ctx: Ctx) -> dict:
    hits = knowledge.search(a.query, k=a.k, source=a.source)
    return {"results": [{"source": h["source"], "ref": h["ref"], "title": h["title"], "score": h["score"],
                         "url": h["url"], "text": h["text"][:600]} for h in hits]}


def get_client_profile(a: NoArgs, ctx: Ctx) -> dict:
    d = store.load_client(ctx.client_id)
    if not d:
        return _fail("unknown client")
    return {"profile": d.get("profile"), "answered": sorted(k for k in d.get("facts", {})),
            "missing": profiling.missing(d.get("facts", {}))}


def ask_profile_question(a: NoArgs, ctx: Ctx) -> dict:
    q = profiling.next_question(_facts(ctx.client_id))
    if q is None:
        state.PENDING_QUESTION.pop(ctx.client_id, None)
        return {"complete": True}
    state.PENDING_QUESTION[ctx.client_id] = q["id"]
    return {"complete": False, "question": q}


def compute_risk_profile(a: NoArgs, ctx: Ctx) -> dict:
    d = store.load_client(ctx.client_id)
    if not d:
        return _fail("unknown client")
    penalty = behaviour.capacity_penalty(ctx.client_id)
    try:
        prof = profiling.build_profile(ctx.client_id, d["facts"], d.get("name", "Client"),
                                       {**(d.get("extra") or {}), "behaviour_penalty": penalty})
    except ValueError as e:
        return _fail(str(e))
    d["profile"] = prof.model_dump()
    d.setdefault("extra", {})["behaviour_penalty_applied"] = penalty
    store.save_client(ctx.client_id, d)
    store.archive_blocked(ctx.client_id)
    eff = config.effective_bucket(prof.bucket, prof.age, prof.horizon_years)
    return {"profile": prof.model_dump(), "tolerance_bucket": profiling.score_to_bucket(prof.risk_tolerance_score),
            "capacity_bucket": profiling.score_to_bucket(prof.risk_capacity_score), "final_bucket": prof.bucket,
            "effective_bucket": eff,
            "behaviour_penalty": penalty,
            "explanation": f"Tolerance {prof.risk_tolerance_score:g} and capacity {prof.risk_capacity_score:g}"
                           + (f" (lowered by {penalty:g} for spending behaviour)" if penalty else "")
                           + f"; final bucket is the lower of the two: {prof.bucket}"
                           + (f", capped to {eff} (vulnerable client, R5)." if eff != prof.bucket else ".")}


def get_behaviour_insights(a: NoArgs, ctx: Ctx) -> dict:
    return behaviour.insights(ctx.client_id)


def explain_counterfactual(a: ProductIdArgs, ctx: Ctx) -> dict:
    return counterfactual.explain(ctx.client_id, a.product_id)


def compare_products(a: CompareArgs, ctx: Ctx) -> dict:
    prof = store.load_profile(ctx.client_id)
    alloc = store.latest_allocation(ctx.client_id)
    return comparison.compare(a.product_ids, load_products(), prof, alloc)


def propose_allocation(a: ProposeArgs, ctx: Ctx) -> dict:
    prof = store.load_profile(ctx.client_id)
    if not prof:
        return _fail("no risk profile yet; compute_risk_profile first")
    if store.consecutive_blocked(ctx.client_id) >= config.MAX_REVISIONS:
        return _fail(f"Maximum of {config.MAX_REVISIONS} blocked drafts reached. I cannot produce a compliant "
                     f"allocation for this request; please adjust the profile or request.")
    alloc = al.build(prof, load_products(), a.preferred_ids, a.exclude_ids, a.summary)
    store.save_allocation(alloc, "draft")
    return {"allocation_id": alloc.id, "lines": [{"product_id": l.product_id, "weight": l.weight} for l in alloc.lines],
            "note": "DRAFT. Not shown to the client until check_compliance passes."}


def check_compliance(a: AllocIdArgs, ctx: Ctx) -> dict:
    alloc = store.load_allocation(a.allocation_id)
    prof = store.load_profile(ctx.client_id)
    if not alloc or alloc.client_id != ctx.client_id or not prof:
        return _fail("allocation or profile not found for this client")
    products = load_products()
    res = compliance.check(alloc, prof, products)
    store.set_compliance(alloc.id, res)
    failed = [c.rule_id for c in res.checks if not c.passed]
    audit.append("compliance", "compliance_check", "T1",
                 {"allocation_id": alloc.id, "passed": res.passed, "failed_rules": failed}, ctx.client_id)
    return {"allocation_id": alloc.id, "passed": res.passed, "failed_rules": failed,
            "checks": [c.model_dump() for c in res.checks],
            "violating_product_ids": [] if res.passed else compliance.violating_products(alloc, prof, products)}


def _compliant(ctx: Ctx, allocation_id: str):
    alloc = store.load_allocation(allocation_id)
    if not alloc or alloc.client_id != ctx.client_id:
        return None, _fail("allocation not found for this client")
    res = store.load_compliance(allocation_id)
    if not res or not res.passed:
        return None, _fail("allocation has not passed compliance, so it cannot be used")
    return alloc, None


def run_stress_test(a: StressArgs, ctx: Ctx) -> dict:
    alloc, err = _compliant(ctx, a.allocation_id)
    if err:
        return err
    try:
        return simulator.stress(alloc, load_products(), a.scenario)
    except ValueError as e:
        return _fail(str(e))


def run_goal_projection(a: GoalArgs, ctx: Ctx) -> dict:
    alloc, err = _compliant(ctx, a.allocation_id)
    if err:
        return err
    prof = store.load_profile(ctx.client_id)
    base = simulator.goal_projection(alloc, prof)
    shocked = simulator.goal_projection(alloc, prof, a.shock_pct)
    hist = simulator.historical_backtest(alloc, load_products(), prof)
    return {**shocked, "base_probability": base["probability"], "shock_pct": a.shock_pct, "historical": hist}


def _stage(kind: str, a: AllocIdArgs, ctx: Ctx) -> dict:
    alloc, err = _compliant(ctx, a.allocation_id)
    if err:
        return err
    t = OrderTicket(id=store.new_id("tkt"), client_id=ctx.client_id, allocation_id=alloc.id,
                    status="awaiting_approval", sandbox=True, kind=kind,
                    detail=f"Sandbox {kind} for allocation {alloc.id}")
    store.save_ticket(t)
    return {"ticket_id": t.id, "status": t.status, "kind": kind, "sandbox": True,
            "note": "Awaiting the client's explicit approval click."}


def create_order_ticket(a: AllocIdArgs, ctx: Ctx) -> dict:
    return _stage("order", a, ctx)


def generate_report(a: AllocIdArgs, ctx: Ctx) -> dict:
    return _stage("report", a, ctx)


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("list_products", "T0", ListProductsArgs, list_products, "List the synthetic product universe."),
    Tool("search_knowledge", "T0", SearchKnowledgeArgs, search_knowledge,
         "Search the knowledge base: the real CSRC suitability regulation (Chinese original), real data sources, "
         "historical stress episodes, our compliance rules and real yearly history cards (US returns, China macro). "
         "Cite the article or source you use."),
    Tool("get_client_profile", "T0", NoArgs, get_client_profile, "Read the current client's profile and answers."),
    Tool("ask_profile_question", "T0", NoArgs, ask_profile_question,
         "Get the next unanswered profiling question (adaptive: answered or implied ones are skipped)."),
    Tool("compute_risk_profile", "T1", NoArgs, compute_risk_profile,
         "Score risk tolerance and capacity from the answers; final bucket is the lower of the two."),
    Tool("get_behaviour_insights", "T1", NoArgs, get_behaviour_insights,
         "Summarise the client's purchase history (totals, categories, impulse share) with plain-language guidance."),
    Tool("explain_counterfactual", "T1", ProductIdArgs, explain_counterfactual,
         "Explain what would have to be true for a blocked product to be allowed for this client (rule by rule, with the "
         "smallest set of different answers, or why it is impossible). Never suggest changing truthful answers."),
    Tool("compare_products", "T1", CompareArgs, compare_products,
         "Compare products side by side with 'why not' notes for this client."),
    Tool("propose_allocation", "T1", ProposeArgs, propose_allocation,
         "Build a DRAFT allocation. It is not visible to the client until check_compliance passes."),
    Tool("check_compliance", "T1", AllocIdArgs, check_compliance,
         "Run the independent compliance engine (R1-R8) on a draft allocation."),
    Tool("run_stress_test", "T1", StressArgs, run_stress_test,
         "Stress test a compliant allocation. Scenarios: equity_-20, rate_+2, crash_2008, inflation_spike."),
    Tool("run_goal_projection", "T1", GoalArgs, run_goal_projection,
         "Monte Carlo probability of reaching the goal, optionally after an immediate shock."),
    Tool("create_order_ticket", "T2", AllocIdArgs, create_order_ticket,
         "Stage a sandbox order ticket. Needs the client's approval click before it counts."),
    Tool("generate_report", "T2", AllocIdArgs, generate_report,
         "Stage the advisory report. Released only after the client's approval click."),
]}

FORBIDDEN = {"execute_real_trade", "change_bank_details", "export_client_data", "disable_audit_log", "fetch_url"}


def anthropic_tools() -> list[dict]:
    out = []
    for t in TOOLS.values():
        schema = t.args.model_json_schema()
        schema.pop("title", None)
        out.append({"name": t.name, "description": f"[{t.tier}] {t.description}", "input_schema": schema})
    return out
