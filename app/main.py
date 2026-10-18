"""FastAPI app: JSON API (contract in CLAUDE.md) plus the static single-page UI."""
import json
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import behaviour, comparison, config, knowledge, ledger, profiling, provenance, receipt, redteam, replay, selfinspection, service, state, store, transcribe, translate
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
STATIC = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")


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
def chat(req: ChatReq):
    _client(req.client_id)
    return loop.run_turn(req.client_id, req.message)


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
def get_state(client_id: str):
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
def get_audit(client_id: Optional[str] = None):
    return audit.list_entries(client_id)


@app.get("/api/audit/verify")
def verify_audit():
    return audit.verify()


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


os.makedirs(STATIC, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
