"""FastAPI app: JSON API (contract in CLAUDE.md) plus the static single-page UI."""
import json
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles

from app import accounts, behaviour, comparison, conversations, config, knowledge, ledger, memory, profiling, provenance, receipt, redteam, replay, selfinspection, service, state, store, transcribe, translate
from app.agent import loop
from app.agent.tools import Ctx
from app.products import load_personas, load_products
from app.schemas import (AllocationReq, ApproveReq, ChatReq, ClientProfile, CompareReq, DocumentReq, LedgerCommandReq,
                         LedgerIn, LedgerPatch, LedgerSampleReq, ProfileReq, ReplayStartReq, ReplayStepReq, SessionReq, StressReq, TranslateReq)
from app.security import audit, guard, tiers

@asynccontextmanager
async def lifespan(_app):
    print(f"WealthGuard LLM: {config.describe_llm()}", flush=True)
    from app import knowledge, vectorstore
    try:
        knowledge.ensure_index()
    except Exception as e:  # the app must start even if the vector index cannot be built
        print(f"WealthGuard vector DB: index build failed ({type(e).__name__})", flush=True)
    st = vectorstore.backend_status()
    print(f"WealthGuard vector DB: {st['backend']}" + (f" (qdrant: {st['qdrant_state']})" if st["qdrant_configured"] else
                                                   " (set QDRANT_URL and QDRANT_API_KEY to use Qdrant)"), flush=True)
    yield


app = FastAPI(title="WealthGuard", description=config.DISCLAIMER, lifespan=lifespan)
from app.finance.routes import router as finance_router  # noqa: E402
app.include_router(finance_router)
STATIC = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")


OPEN_API = {"/api/health", "/api/auth/login", "/api/auth/signup"}


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    """Every /api route needs a signed-in user, except health and the sign-in / sign-up routes."""
    request.state.user, request.state.token = None, ""
    path = request.url.path
    if path.startswith("/api/"):
        h = request.headers.get("authorization", "")
        request.state.token = h[7:].strip() if h.lower().startswith("bearer ") else ""
        if request.state.token:
            request.state.user = await run_in_threadpool(accounts.user_for_token, request.state.token)
        if accounts.auth_required() and path not in OPEN_API and request.state.user is None:
            return JSONResponse({"detail": "Sign in required."}, status_code=401)
        me = request.state.user
        if me and accounts.auth_required():
            if path.startswith("/api/admin/") and me["role"] != "admin":
                return JSONResponse({"detail": "Administrators only."}, status_code=403)
            feat = accounts.feature_for(path, request.method)
            if feat and not me["permissions"].get(feat, True):
                return JSONResponse({"detail": f"Your account does not have access to {accounts.FEATURES[feat].lower()}. "
                                               "Ask an administrator."}, status_code=403)
    response = await call_next(request)
    if not path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"      # the page and its scripts are re-validated on every load, so an update is never masked by a stale copy
    return response


def _me(request: Request) -> dict:
    if request.state.user is None:
        raise HTTPException(401, "Sign in required.")
    return request.state.user


def _owns(request: Request, client_id: str) -> None:
    """A signed-in user can only open their own chats (admins can open any). Sessions without a saved chat are open."""
    if accounts.auth_required() and not conversations.can_access(request.state.user, client_id):
        raise HTTPException(403, "This chat belongs to another account.")


class Credentials(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=200)
    display_name: str = Field("", max_length=40)


class PasswordChange(BaseModel):
    old_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


class BanReq(BaseModel):
    banned: bool


class RoleReq(BaseModel):
    role: str = Field(max_length=10)


class PermsReq(BaseModel):
    permissions: dict[str, bool]


class NewUser(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=200)
    display_name: str = Field("", max_length=40)
    role: str = Field("client", max_length=10)


class DeleteUser(BaseModel):
    confirm: str = Field(max_length=64)


class NewPassword(BaseModel):
    new_password: str = Field(max_length=200)


class FactReq(BaseModel):
    key: str = Field(max_length=40)
    value: str = Field(max_length=80)


class NoteReq(BaseModel):
    text: str = Field(max_length=200)


class DemoReq(BaseModel):
    persona_id: str = Field(max_length=40)


def _auth_call(fn, *a):
    try:
        return fn(*a)
    except accounts.AuthError as e:
        raise HTTPException(e.status, e.message)


@app.post("/api/auth/signup")
def auth_signup(req: Credentials):
    out = _auth_call(accounts.signup, req.username, req.password, req.display_name)
    audit.append("system", "account_created", "T0", {"username": out["user"]["username"]})
    return out


@app.post("/api/auth/login")
def auth_login(req: Credentials):
    out = _auth_call(accounts.login, req.username, req.password)
    audit.append("system", "login", "T0", {"username": out["user"]["username"]})
    return out


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    accounts.logout(request.state.token)
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(request: Request):
    return _me(request)


@app.post("/api/auth/password")
def auth_password(req: PasswordChange, request: Request):
    me = _me(request)
    _auth_call(accounts.change_password, me["username"], req.old_password, req.new_password, request.state.token)
    audit.append("system", "password_changed", "T0", {"username": me["username"]})
    return {"ok": True}


@app.get("/api/conversations")
def list_conversations(request: Request):
    return conversations.listing(_me(request))


@app.post("/api/conversations")
def new_conversation(request: Request):
    me = _me(request)
    if me["role"] == "admin":
        raise HTTPException(403, "Administrators manage accounts; they do not have advice chats.")
    return conversations.create(me)


# ---- administration: accounts, roles, per-account feature access (never chat contents)
def _admin(request: Request) -> dict:
    me = _me(request)
    if me["role"] != "admin":
        raise HTTPException(403, "Administrators only.")
    return me


@app.get("/api/admin/users")
def admin_users(request: Request):
    _admin(request)
    return {"users": accounts.list_users(), "features": accounts.FEATURES, "summary": accounts.admin_summary()}


@app.post("/api/admin/users/{username}/ban")
def admin_ban(username: str, req: BanReq, request: Request):
    me = _admin(request)
    out = _auth_call(accounts.set_banned, me["username"], username, req.banned)
    audit.append("system", "admin_suspend" if req.banned else "admin_restore", "T2", {"admin": me["username"], "target": out["username"]})
    return out


@app.post("/api/admin/users/{username}/role")
def admin_role(username: str, req: RoleReq, request: Request):
    me = _admin(request)
    out = _auth_call(accounts.set_role, me["username"], username, req.role)
    audit.append("system", "admin_role", "T2", {"admin": me["username"], "target": out["username"], "role": out["role"]})
    return out


@app.post("/api/admin/users/{username}/permissions")
def admin_permissions(username: str, req: PermsReq, request: Request):
    me = _admin(request)
    out = _auth_call(accounts.set_permissions, username, req.permissions)
    audit.append("system", "admin_permissions", "T2", {"admin": me["username"], "target": out["username"],
                                                       "denied": sorted(k for k, v in out["permissions"].items() if not v)})
    return out


@app.post("/api/admin/users")
def admin_create(req: NewUser, request: Request):
    me = _admin(request)
    out = _auth_call(accounts.create_user, req.username, req.password, req.display_name, req.role)
    audit.append("system", "admin_user_created", "T2", {"admin": me["username"], "target": out["username"], "role": out["role"]})
    return out


@app.post("/api/admin/users/{username}/signout")
def admin_signout(username: str, request: Request):
    me = _admin(request)
    n = _auth_call(accounts.revoke_sessions, username)
    audit.append("system", "admin_signout", "T2", {"admin": me["username"], "target": username.strip().lower(), "sessions": n})
    return {"signed_out": n}


@app.post("/api/admin/users/{username}/delete")
def admin_delete(username: str, req: DeleteUser, request: Request):
    me = _admin(request)
    out = _auth_call(accounts.delete_user, me["username"], username, req.confirm)
    audit.append("system", "admin_user_deleted", "T2", {"admin": me["username"], "target": out["deleted"], "conversations": out["conversations"]})
    return out


@app.get("/api/admin/activity")
def admin_activity(request: Request, limit: int = Query(40, ge=1, le=200)):
    """Recent account-level events: sign-ins, sign-ups and every administrator action (who did what to whom, never contents)."""
    _admin(request)
    kinds = ("login", "account_created", "password_changed")
    rows = [e for e in audit.list_entries(None) if e["action"] in kinds or e["action"].startswith("admin_")]
    return {"entries": [{"ts": e["ts"], "action": e["action"], "detail": e["payload"] if isinstance(e["payload"], dict) else {}} for e in rows[-limit:][::-1]]}


@app.get("/api/admin/ai-usage")
def admin_ai_usage(request: Request, days: int = Query(30, ge=1, le=365)):
    """Token use and estimated cost of the finance assistant across all accounts (no message contents)."""
    _admin(request)
    from app.finance import ai
    return ai.usage_summary(None, days)


@app.post("/api/admin/users/{username}/password")
def admin_password(username: str, req: NewPassword, request: Request):
    me = _admin(request)
    _auth_call(accounts.admin_reset_password, username, req.new_password)
    audit.append("system", "admin_password_reset", "T2", {"admin": me["username"], "target": username.strip().lower()})
    return {"ok": True}


# ---- memory: what the assistant remembers about the signed-in account
def _memory_user(request: Request) -> str:
    me = _me(request)
    if me["role"] == "admin":
        raise HTTPException(403, "Administrators do not have a client memory.")
    return me["username"]


def _memory_call(fn, *a):
    try:
        return fn(*a)
    except memory.MemoryInputError as e:
        raise HTTPException(400, str(e))


@app.get("/api/memory")
def memory_overview(request: Request):
    return memory.overview(_memory_user(request))


@app.post("/api/memory/fact")
def memory_set_fact(req: FactReq, request: Request):
    user = _memory_user(request)
    _memory_call(memory.set_fact, user, req.key, req.value)
    audit.append("client", "memory_fact_saved", "T1", {"key": req.key})
    return memory.overview(user)


@app.post("/api/memory/fact/{key}/delete")
def memory_delete_fact(key: str, request: Request):
    user = _memory_user(request)
    memory.delete_fact(user, key)
    return memory.overview(user)


@app.post("/api/memory/notes")
def memory_add_note(req: NoteReq, request: Request):
    user = _memory_user(request)
    _memory_call(memory.add_note, user, req.text)
    return memory.overview(user)


@app.post("/api/memory/item/{item_id}/delete")
def memory_delete_item(item_id: int, request: Request):
    user = _memory_user(request)
    memory.delete_item(user, item_id)
    return memory.overview(user)


@app.post("/api/memory/clear")
def memory_clear(request: Request):
    user = _memory_user(request)
    memory.clear(user)
    audit.append("client", "memory_cleared", "T1", {})
    return memory.overview(user)


@app.post("/api/memory/demo")
def memory_demo(req: DemoReq, request: Request):
    user = _memory_user(request)
    _memory_call(memory.load_demo, user, req.persona_id)
    audit.append("client", "memory_demo_loaded", "T1", {"persona_id": req.persona_id})
    return memory.overview(user)


@app.get("/api/conversations/{client_id}")
def open_conversation(client_id: str, request: Request):
    me = _me(request)
    if conversations.get(client_id) is None:
        raise HTTPException(404, "unknown chat")
    if not conversations.can_access(me, client_id):
        raise HTTPException(403, "This chat belongs to another account.")
    return conversations.open_chat(client_id)


@app.post("/api/conversations/{client_id}/delete")
def delete_conversation(client_id: str, request: Request):
    me = _me(request)
    if conversations.get(client_id) is None:
        raise HTTPException(404, "unknown chat")
    if not conversations.can_access(me, client_id):
        raise HTTPException(403, "This chat belongs to another account.")
    conversations.delete(client_id)
    return {"ok": True}


def _client(client_id: str) -> dict:
    d = store.load_client(client_id)
    if not d:
        raise HTTPException(404, "unknown client_id")
    return d


@app.get("/api/health")
def health():
    from app import vectorstore
    return {"ok": True, "mock_llm": config.use_mock_llm(), "llm": config.describe_llm(),
            "vector_db": vectorstore.backend_status(), "transcription": transcribe.status(),
            "disclaimer": config.DISCLAIMER}


@app.get("/api/personas")
def personas():
    return [{"id": p["id"], "name": p["name"], "story": p["story"]} for p in load_personas().values()]


@app.post("/api/session")
def session(req: SessionReq):
    try:
        return service.create_session(req.persona_id)
    except KeyError:
        raise HTTPException(404, "unknown persona")


@app.post("/api/chat")
def chat(req: ChatReq, request: Request):
    _client(req.client_id)
    _owns(request, req.client_id)
    out = loop.run_turn(req.client_id, req.message)
    conversations.record_turn(req.client_id, req.message, out["reply"])
    return out


@app.post("/api/transcribe")
async def transcribe_audio(request: Request, language: Optional[str] = None, client_id: Optional[str] = None):
    """Whisper speech-to-text. The body is the raw audio; the answer is text for the chat box (nothing is sent to the agent).

    T1, audited (provider, model, size, language, length; never the audio or the transcript)."""
    if client_id:
        _client(client_id)
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > transcribe.MAX_BYTES:
        raise HTTPException(413, "Audio is too long.")
    data = b""
    async for chunk in request.stream():
        data += chunk
        if len(data) > transcribe.MAX_BYTES:
            raise HTTPException(413, "Audio is too long.")
    try:
        out = await run_in_threadpool(transcribe.transcribe, data, language, client_id)
    except transcribe.TranscribeError as e:
        audit.append("client", "voice_transcribe_failed", "T1", {"status": e.status, "bytes": len(data)}, client_id)
        raise HTTPException(e.status, e.message)
    audit.append("client", "voice_transcribed", "T1", {"provider": out["provider"], "model": out["model"], "bytes": len(data),
                                                      "language": language, "chars": len(out["text"]), "empty": out["empty"],
                                                      "container": out["container"]}, client_id)
    return out


@app.post("/api/translate")
def translate_texts(req: TranslateReq):
    if req.client_id:
        _client(req.client_id)
    return translate.translate_many(req.texts, req.target, req.client_id)


def _ledger_view(client_id: str) -> dict:
    return {"entries": ledger.list_entries(client_id), "insights": behaviour.insights(client_id),
            "pending": ledger.pending_changes(client_id)}


@app.get("/api/ledger")
def get_ledger(client_id: str):
    _client(client_id)
    return _ledger_view(client_id)


@app.post("/api/ledger")
def add_ledger(req: LedgerIn):
    _client(req.client_id)
    try:
        ledger.add_entry(req.client_id, req.item, req.amount_cny, req.category, req.status, req.impulse, req.ts)
    except ValueError as e:
        raise HTTPException(409, str(e))
    service.sync_profile_with_behaviour(req.client_id)
    return _ledger_view(req.client_id)


@app.post("/api/ledger/{entry_id}/update")
def update_ledger(entry_id: str, req: LedgerPatch):
    _client(req.client_id)
    try:
        ledger.update_entry(entry_id, req.client_id, item=req.item, category=req.category,
                            amount_cny=req.amount_cny, status=req.status, impulse=req.impulse)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    service.sync_profile_with_behaviour(req.client_id)
    return _ledger_view(req.client_id)


@app.post("/api/ledger/{entry_id}/delete")
def delete_ledger(entry_id: str, req: ApproveReq):
    _client(req.client_id)
    try:
        ledger.delete_entry(entry_id, req.client_id)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    service.sync_profile_with_behaviour(req.client_id)
    return _ledger_view(req.client_id)


@app.post("/api/ledger/command")
def ledger_command(req: LedgerCommandReq):
    """Parse a typed or spoken command into a proposal. Nothing changes until /confirm (an explicit click)."""
    _client(req.client_id)
    findings = guard.scan(req.text)
    if findings:
        audit.append("system", "injection_flagged", "T1", {"source": "ledger_command", "findings": findings},
                     req.client_id)
    res = ledger.parse_command(req.client_id, req.text)
    audit.append("client", "ledger_command", "T1", {"source": req.source, "ok": res["ok"],
                                                   "action": res.get("proposal", {}).get("action")}, req.client_id)
    return res | {"warnings": guard.warnings_for(req.text, "ledger command") if findings else []}


@app.post("/api/ledger/confirm/{change_id}")
def ledger_confirm(change_id: str, req: ApproveReq):
    _client(req.client_id)
    try:
        ledger.confirm(change_id, req.client_id)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    service.sync_profile_with_behaviour(req.client_id)
    return _ledger_view(req.client_id)


@app.post("/api/ledger/reject/{change_id}")
def ledger_reject(change_id: str, req: ApproveReq):
    _client(req.client_id)
    try:
        ledger.reject(change_id, req.client_id)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    return _ledger_view(req.client_id)


@app.post("/api/ledger/sample")
def ledger_sample(req: LedgerSampleReq):
    _client(req.client_id)
    ledger.load_sample(req.client_id, req.kind)
    service.sync_profile_with_behaviour(req.client_id)
    return _ledger_view(req.client_id)


KB_SOURCES = {"csrc_suitability", "data_sources", "market_episodes", "wealthguard_rules", "history_cards"}


@app.get("/api/knowledge/search")
def knowledge_search(q: str = Query(min_length=2, max_length=300), k: int = Query(3, ge=1, le=5),
                     source: Optional[str] = None, client_id: Optional[str] = None):
    """Vector search over the regulation text, data sources, stress episodes and our rules (T0 read, audited)."""
    if source and source not in KB_SOURCES:
        raise HTTPException(422, f"unknown source; choose from {sorted(KB_SOURCES)}")
    if client_id:
        _client(client_id)
    hits, backend = knowledge.search_ex(q, k=k, source=source)
    audit.append("client", "knowledge_search", "T0", {"chars": len(q), "source": source, "k": k, "hits": len(hits),
                                                      "backend": backend}, client_id)
    return {"query": q, "results": hits, "backend": backend}


def _replay_result(out: dict) -> dict:
    if out.get("ok") is False:
        raise HTTPException(out.pop("status", 409), out["error"])
    return out


@app.post("/api/replay/start")
def replay_start(req: ReplayStartReq):
    """Start a revealed-risk replay of a real market episode with the client's approved allocation."""
    _client(req.client_id)
    out = replay.start(req.client_id, req.episode, req.portfolio)
    if out.get("ok") is False:
        raise HTTPException(422 if "unknown episode" in out["error"] or "portfolio" in out["error"] else 409, out["error"])
    return out


@app.post("/api/replay/{session_id}/step")
def replay_step(session_id: str, req: ReplayStepReq):
    _client(req.client_id)
    return _replay_result(replay.step(session_id, req.client_id, req.choice))


@app.post("/api/replay/{session_id}/apply")
def replay_apply(session_id: str, req: ApproveReq):
    """Apply the revealed (more cautious) reaction to the profile: an explicit click, never automatic."""
    _client(req.client_id)
    return _replay_result(replay.apply(session_id, req.client_id))


@app.get("/api/provenance")
def get_provenance(client_id: str, kind: str, allocation_id: str = "", scenario: str = "", shock_pct: float = Query(0.0, ge=-100, le=100)):
    """Where a displayed number comes from, with a fresh recomputation (T0 read, audited)."""
    _client(client_id)
    out = provenance.explain(client_id, kind, allocation_id, scenario, shock_pct)
    if out.get("ok") is False:
        raise HTTPException(404 if "unknown client" in out["error"] else 422 if "unknown" in out["error"] else 409, out["error"])
    audit.append("client", "provenance_viewed", "T0", {"kind": kind, "matches": out["matches"]}, client_id)
    return out


@app.get("/api/receipt")
def get_receipt(client_id: str):
    """A verifiable advice receipt for the latest compliance-approved allocation (T1, audited)."""
    _client(client_id)
    r = receipt.build(client_id)
    if not r:
        raise HTTPException(409, "no compliance-approved allocation yet")
    audit.append("client", "receipt_issued", "T1", {"content_hash": r["content_hash"], "head_id": r["checkpoint"]["head_id"]},
                 client_id)
    return r


@app.post("/api/receipt/verify")
def verify_receipt(body: dict = Body(...)):
    """Verify a receipt (the receipt itself, or {"receipt": ...}) against this server's audit log and key."""
    r = body.get("receipt", body)
    if len(json.dumps(r, default=str)) > 2_000_000:
        raise HTTPException(413, "receipt too large")
    res = receipt.verify(r if isinstance(r, dict) else {})
    audit.append("system", "receipt_verified", "T1", {"valid": res["valid"], "failed": [c["name"] for c in res["checks"] if not c["ok"]]}, None)
    return res


@app.get("/api/counterfactual")
def counterfactual_route(client_id: str, product_id: str = Query(min_length=2, max_length=20)):
    """What would have to be true for this product to be allowed (T1, audited through the tier engine)."""
    _client(client_id)
    out = tiers.execute("explain_counterfactual", {"product_id": product_id}, Ctx(client_id))
    if out.get("ok") is False:
        raise HTTPException(404 if "unknown product" in out.get("error", "") else 409, out.get("error", "cannot explain"))
    return out


@app.post("/api/redteam/run")
def redteam_run():
    """Run the attack battery against the live engines (deterministic, no model call) on throw-away probe clients."""
    return redteam.run_all()


@app.get("/api/selfinspection")
def self_inspection(lang: str = "en", client_id: Optional[str] = None):
    """Article 30 style self-inspection report counted from the audit log (T1 read, audited after it is computed)."""
    if lang not in ("en", "zh"):
        raise HTTPException(422, "lang must be en or zh")
    if client_id:
        _client(client_id)
    r = selfinspection.build(client_id, lang)
    audit.append("client", "selfinspection_report", "T1", {"lang": lang, "scope": "client" if client_id else "all"},
                 client_id)
    return r | {"markdown": selfinspection.to_markdown(r)}


@app.get("/api/products")
def products():
    audit.append("system", "list_products", "T0", {}, None)
    return [comparison.row(p) | {"description": p.description} for p in load_products().values()]


@app.post("/api/compare")
def compare(req: CompareReq):
    if req.client_id:
        _client(req.client_id)
        if store.load_profile(req.client_id):
            return tiers.execute("compare_products", {"product_ids": req.product_ids}, Ctx(req.client_id))
    return comparison.compare(req.product_ids, load_products(), None, None)


@app.post("/api/profile", response_model=ClientProfile)
def profile(req: ProfileReq):
    d = _client(req.client_id)
    for k, v in req.answers.items():
        if k not in profiling.QBY:
            raise HTTPException(422, f"unknown answer field '{k}'")
        val = profiling.parse_answer(k, str(v)) if profiling.QBY[k]["type"] == "choice" or not isinstance(
            v, (int, float)) else v
        if val is None:
            raise HTTPException(422, f"could not understand answer for '{k}'")
        d["facts"][k] = val
    store.save_client(req.client_id, d)
    audit.append("client", "profile_answers", "T1", {"fields": sorted(req.answers)}, req.client_id)
    missing = profiling.missing(d["facts"])
    if missing:
        raise HTTPException(409, {"missing": missing, "next_question": profiling.next_question(d["facts"])})
    state.PENDING_QUESTION.pop(req.client_id, None)
    out = tiers.execute("compute_risk_profile", {}, Ctx(req.client_id))
    if not out.get("profile"):
        raise HTTPException(422, out.get("error", "could not compute profile"))
    return ClientProfile(**out["profile"])


@app.post("/api/allocation")
def allocation(req: AllocationReq):
    d = _client(req.client_id)
    if not d.get("profile"):
        raise HTTPException(409, "compute the risk profile first (POST /api/profile)")
    out = service.run_pipeline(req.client_id, req.preferred_ids)
    return {"allocation": out.get("allocation"), "compliance": out.get("compliance"),
            "attempts": out["attempts"], "why_not": out.get("why_not", {}), "error": out.get("error")}


@app.post("/api/stress")
def stress(req: StressReq):
    alloc = store.load_allocation(req.allocation_id)
    if not alloc:
        raise HTTPException(404, "unknown allocation")
    ctx = Ctx(alloc.client_id)
    out = tiers.execute("run_stress_test", {"allocation_id": req.allocation_id, "scenario": req.scenario}, ctx)
    if out.get("ok") is False:
        raise HTTPException(422, out["error"])
    goal = tiers.execute("run_goal_projection", {"allocation_id": req.allocation_id, "shock_pct": out["loss_pct"]},
                         ctx)
    return {**out, "goal": goal}


@app.post("/api/documents")
def documents(req: DocumentReq):
    _client(req.client_id)
    warnings = guard.warnings_for(req.text, req.filename)
    store.add_document(req.client_id, req.filename, req.text, warnings)
    audit.append("client", "document_uploaded", "T1",
                 {"filename": req.filename, "chars": len(req.text), "flagged": len(warnings)}, req.client_id)
    if warnings:
        audit.append("system", "injection_flagged", "T1",
                     {"source": req.filename, "findings": guard.scan(req.text)}, req.client_id)
    return {"warnings": warnings, "safe_preview": guard.redact(req.text)[:500]}


@app.post("/api/approve/{ticket_id}")
def approve(ticket_id: str, req: ApproveReq):
    try:
        return tiers.approve_ticket(ticket_id, req.client_id)
    except PermissionError as e:
        raise HTTPException(403, str(e))


@app.post("/api/reject/{ticket_id}")
def reject(ticket_id: str, req: ApproveReq):
    try:
        return tiers.reject_ticket(ticket_id, req.client_id)
    except PermissionError as e:
        raise HTTPException(403, str(e))


def _regulatory_basis(alloc) -> dict:
    res = store.load_compliance(alloc.id) if alloc else None
    out = {}
    for ck in (res.checks if res else []):
        b = knowledge.basis_for_rule(ck.rule_id)
        if b:
            out[ck.rule_id] = {k: b[k] for k in ("article", "article_no", "snippet", "text", "score", "url", "source")}
    return out


@app.get("/api/state")
def get_state(client_id: str, request: Request):
    _owns(request, client_id)
    d = _client(client_id)
    alloc = store.latest_allocation(client_id)
    prof = d.get("profile")
    return {"name": d.get("name"), "profile": prof, "allocation": alloc,
            "effective_bucket": config.effective_bucket(prof["bucket"], prof["age"], prof["horizon_years"])
            if prof else None,
            "attempts_blocked": store.consecutive_blocked(client_id),
            "compliance": store.load_compliance(alloc.id) if alloc else None,
            "regulatory_basis": _regulatory_basis(alloc),
            "tickets": store.list_tickets(client_id),
            "why_not": service.why_not_notes(client_id, alloc) if alloc else {},
            "next_question": profiling.next_question(d["facts"]),
            "documents": [{"filename": x["filename"], "warnings": x["warnings"]}
                          for x in store.list_documents(client_id)]}


@app.get("/api/audit")
def get_audit(request: Request, client_id: Optional[str] = None):
    if accounts.auth_required() and request.state.user and request.state.user["role"] != "admin":
        if not client_id:
            return []              # members only ever see the log of their own chat
        _owns(request, client_id)
    return audit.list_entries(client_id)


@app.get("/api/audit/verify")
def verify_audit():
    return audit.verify()


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


os.makedirs(STATIC, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
