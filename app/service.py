"""Shared application services used by both the REST routes and the agent loop."""
from typing import Optional

from app import behaviour, comparison, config, profiling, state, store
from app.agent.tools import Ctx
from app.products import load_personas, load_products
from app.security import audit, tiers


def create_session(persona_id: Optional[str], facts: Optional[dict] = None, extra: Optional[dict] = None,
                   name: Optional[str] = None) -> dict:
    """A session starts blank (or from facts the account already remembers); a persona is only a demo shortcut."""
    cid = store.new_id("client")
    facts, extra, name = dict(facts or {}), dict(extra or {}), name or "Client"
    if persona_id:
        per = load_personas().get(persona_id)
        if not per:
            raise KeyError(persona_id)
        facts = {k: per[k] for k in per["known"]}
        extra = {"investable_amount_cny": per["investable_amount_cny"], "goal_target_cny": per["goal_target_cny"]}
        name = per["name"]
    store.save_client(cid, {"name": name, "persona_id": persona_id, "facts": facts, "profile": None, "extra": extra})
    audit.append("system", "session_started", "T0", {"persona_id": persona_id}, cid)
    q = profiling.next_question(facts)
    if q:
        state.PENDING_QUESTION[cid] = q["id"]
    return {"client_id": cid, "name": name, "persona_id": persona_id, "next_question": q,
            "story": (load_personas().get(persona_id) or {}).get("story"), "disclaimer": config.DISCLAIMER}


def why_not_notes(client_id: str, allocation=None, limit: int = 4) -> dict:
    prof = store.load_profile(client_id)
    if not prof:
        return {}
    products = load_products()
    held = {l.product_id for l in allocation.lines} if allocation else set()
    cands = sorted((p for p in products.values() if p.id not in held),
                   key=lambda p: (-p.expected_return, p.id))[:limit]
    return {p.id: {"name": p.name, "text": comparison.why_not(p, prof, products, allocation)} for p in cands}


def run_pipeline(client_id: str, preferred_ids: list[str]) -> dict:
    """Deterministic propose -> check -> revise loop (max 3 revisions), every step through the tier engine."""
    ctx = Ctx(client_id)
    store.archive_blocked(client_id)
    attempts, exclude, final, last_res = [], [], None, None
    for n in range(config.MAX_REVISIONS + 1):
        draft = tiers.execute("propose_allocation", {"preferred_ids": preferred_ids if n == 0 else [],
                                                      "exclude_ids": exclude}, ctx)
        if not draft.get("allocation_id"):
            return {"ok": False, "error": draft.get("error", "could not build an allocation"), "attempts": attempts}
        res = tiers.execute("check_compliance", {"allocation_id": draft["allocation_id"]}, ctx)
        attempts.append({"allocation_id": draft["allocation_id"], "passed": res["passed"],
                         "failed_rules": res["failed_rules"], "violating_product_ids": res["violating_product_ids"],
                         "draft_lines": draft["lines"]})
        last_res = res
        if res["passed"]:
            final = draft["allocation_id"]
            break
        exclude = sorted(set(exclude) | set(res["violating_product_ids"]))
    out = {"ok": bool(final), "attempts": attempts, "compliance": store.load_compliance(
        final or attempts[-1]["allocation_id"])}
    if final:
        alloc = store.load_allocation(final)
        out["allocation"] = alloc
        out["why_not"] = why_not_notes(client_id, alloc)
    else:
        out["error"] = ("I could not produce an allocation that passes compliance after "
                        f"{config.MAX_REVISIONS} revisions (failed: {', '.join(last_res['failed_rules'])}).")
    return out


def sync_profile_with_behaviour(client_id: str) -> bool:
    """If the ledger changed the behaviour penalty, drop the stale profile so it is recomputed (more cautious only)."""
    d = store.load_client(client_id)
    if not d or not d.get("profile"):
        return False
    applied = float((d.get("extra") or {}).get("behaviour_penalty_applied", 0) or 0)
    if behaviour.capacity_penalty(client_id) == applied:
        return False
    d["profile"] = None
    store.save_client(client_id, d)
    audit.append("system", "profile_invalidated_by_behaviour", "T1", {"previous_penalty": applied}, client_id)
    return True
