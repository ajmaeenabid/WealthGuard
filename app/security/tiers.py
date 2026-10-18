"""Permission tiers, enforced in code (not in the prompt).

T0 read, T1 suggest (audited), T2 act (staged only; needs the client's approval click via `approve_ticket`),
T3 forbidden (always refused and logged). There is deliberately no auto-execute tier: nothing in `execute` can move a
ticket to 'approved'.
"""
from urllib.parse import urlparse

from pydantic import ValidationError

from app import config, store
from app.security import audit


def tier_of(tool: str):
    from app.agent import tools
    if tool in tools.FORBIDDEN:
        return "T3"
    t = tools.TOOLS.get(tool)
    return t.tier if t else None


def is_url_allowed(url: str) -> bool:
    try:
        u = urlparse(url)
    except Exception:
        return False
    base = f"{u.scheme}://{u.netloc}"
    return u.scheme == "https" and base in config.url_allowlist()


def _digest(result) -> dict:
    if not isinstance(result, dict):
        return {}
    keys = ("ok", "error", "allocation_id", "passed", "failed_rules", "ticket_id", "status", "loss_pct",
            "probability", "complete")
    return {k: result[k] for k in keys if k in result}


def execute(tool: str, args, ctx, actor: str = "agent") -> dict:
    """Single entry point for every agent tool call. Returns a dict; refusals have ok=False, refused=True."""
    from app.agent import tools
    cid = ctx.client_id
    tier = tier_of(tool)
    if tier is None:
        audit.append(actor, "refused_unknown_tool", "T3", {"tool": tool}, cid)
        return {"ok": False, "refused": True, "error": f"Unknown tool '{tool}'."}
    if tier == "T3":
        audit.append(actor, f"refused_forbidden:{tool}", "T3", {"tool": tool, "args": args}, cid)
        return {"ok": False, "refused": True, "tier": "T3",
                "error": f"'{tool}' is a forbidden (T3) action. It is always refused and has been logged."}
    spec = tools.TOOLS[tool]
    try:
        parsed = spec.args.model_validate(args if args is not None else {})
    except ValidationError as e:
        audit.append(actor, f"refused_invalid_args:{tool}", tier, {"args": args, "errors": e.error_count()}, cid)
        return {"ok": False, "refused": True, "error": f"Invalid arguments for {tool}: {e.errors()[0]['msg']}"}
    try:
        result = spec.handler(parsed, ctx)
    except Exception as e:  # never leak internals to the model
        audit.append(actor, f"tool_error:{tool}", tier, {"args": args, "error": type(e).__name__}, cid)
        return {"ok": False, "error": f"{tool} failed ({type(e).__name__})."}
    audit.append(actor, f"tool:{tool}", tier, {"args": parsed.model_dump(), "result": _digest(result)}, cid)
    return result


def approve_ticket(ticket_id: str, client_id: str) -> dict:
    """T2 execution. Only the approval endpoint (an explicit client click) may call this."""
    t = store.load_ticket(ticket_id)
    if not t or t.client_id != client_id:
        audit.append("client", "refused_approve_unknown_ticket", "T2", {"ticket_id": ticket_id}, client_id)
        raise PermissionError("ticket not found for this client")
    if t.status != "awaiting_approval":
        audit.append("client", "refused_approve_bad_state", "T2", {"ticket_id": ticket_id, "status": t.status},
                     client_id)
        raise PermissionError(f"ticket is '{t.status}', not awaiting approval")
    res = store.load_compliance(t.allocation_id)
    if not res or not res.passed:
        audit.append("compliance", "refused_approve_not_compliant", "T2", {"ticket_id": ticket_id}, client_id)
        raise PermissionError("allocation is not compliance-approved")
    t.status = "approved"
    if t.kind == "report":
        t.detail = build_report(t.allocation_id)
    store.save_ticket(t)
    audit.append("client", f"approve_{t.kind}", "T2", {"ticket_id": t.id, "allocation_id": t.allocation_id},
                 client_id)
    return t.model_dump()


def reject_ticket(ticket_id: str, client_id: str) -> dict:
    t = store.load_ticket(ticket_id)
    if not t or t.client_id != client_id or t.status != "awaiting_approval":
        raise PermissionError("ticket cannot be rejected")
    t.status = "rejected"
    store.save_ticket(t)
    audit.append("client", "reject_ticket", "T2", {"ticket_id": t.id}, client_id)
    return t.model_dump()


def build_report(allocation_id: str) -> str:
    alloc = store.load_allocation(allocation_id)
    return alloc.client_text if alloc else ""
