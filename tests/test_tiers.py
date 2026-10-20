import pytest

from app import store
from app.agent import tools
from app.agent.tools import Ctx
from app.schemas import OrderTicket
from app.security import audit, tiers
from tests.test_flow_helpers import ready_client


@pytest.mark.parametrize("tool", sorted(tools.FORBIDDEN))
def test_t3_always_refused_and_logged(tool):
    r = tiers.execute(tool, {}, Ctx("c1"))
    assert r["ok"] is False and r["refused"] and r["tier"] == "T3"
    assert any(e["action"] == f"refused_forbidden:{tool}" for e in audit.list_entries())


def test_unknown_tool_and_unknown_fields_refused():
    assert tiers.execute("rm_rf", {}, Ctx("c1"))["refused"]
    r = tiers.execute("list_products", {"evil": 1}, Ctx("c1"))
    assert r["ok"] is False and r["refused"]
    assert tiers.execute("run_stress_test", {"allocation_id": "x"}, Ctx("c1"))["ok"] is False


def test_t0_t1_allowed_and_audited():
    cid, _ = ready_client()
    assert "products" in tiers.execute("list_products", {}, Ctx(cid))
    assert "allocation_id" in tiers.execute("propose_allocation", {}, Ctx(cid))
    acts = [e["action"] for e in audit.list_entries()]
    assert "tool:list_products" in acts and "tool:propose_allocation" in acts


def test_tier_lookup():
    assert tiers.tier_of("list_products") == "T0"
    assert tiers.tier_of("propose_allocation") == "T1"
    assert tiers.tier_of("create_order_ticket") == "T2"
    assert tiers.tier_of("execute_real_trade") == "T3"
    assert tiers.tier_of("nope") is None


def test_t2_is_staged_never_approved_by_agent():
    cid, aid = ready_client(passed=True)
    r = tiers.execute("create_order_ticket", {"allocation_id": aid}, Ctx(cid))
    assert r["status"] == "awaiting_approval"
    assert store.load_ticket(r["ticket_id"]).status == "awaiting_approval"
    r2 = tiers.execute("create_order_ticket", {"allocation_id": aid, "approved": True}, Ctx(cid))
    assert r2["ok"] is False


def test_t2_refused_without_compliance():
    cid, aid = ready_client(passed=False)
    r = tiers.execute("create_order_ticket", {"allocation_id": aid}, Ctx(cid))
    assert r["ok"] is False and "compliance" in r["error"]


def test_approve_requires_owner_and_state():
    cid, aid = ready_client(passed=True)
    t = tiers.execute("create_order_ticket", {"allocation_id": aid}, Ctx(cid))["ticket_id"]
    with pytest.raises(PermissionError):
        tiers.approve_ticket(t, "someone_else")
    assert tiers.approve_ticket(t, cid)["status"] == "approved"
    with pytest.raises(PermissionError):
        tiers.approve_ticket(t, cid)


def test_approve_refused_if_not_compliant():
    cid, aid = ready_client(passed=True)
    store.save_ticket(OrderTicket(id="tkt_x", client_id=cid, allocation_id="alloc_unknown",
                                  status="awaiting_approval"))
    with pytest.raises(PermissionError):
        tiers.approve_ticket("tkt_x", cid)


def test_url_allowlist():
    assert tiers.is_url_allowed("https://api.anthropic.com/v1/messages")
    assert not tiers.is_url_allowed("https://evil.example/x")
    assert not tiers.is_url_allowed("http://api.anthropic.com")
