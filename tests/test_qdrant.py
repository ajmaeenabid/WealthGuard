"""Optional Qdrant backend, tested against an in-memory stand-in for its REST API (no real service is contacted)."""
import json
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, knowledge, qdrant_backend, vectorstore
from app.main import app
from app.security import tiers

c = TestClient(app)
URL = "https://demo-cluster.qdrant.example:6333"
KEY = "super-secret-key-123"


class FakeQdrant:
    """Implements the REST calls we use: collections list/get/create/delete, points upsert, points query."""

    def __init__(self, key=KEY):
        self.key, self.cols, self.calls, self.fail = key, {}, [], None
        self.strict = False       # Qdrant Cloud strict mode: filters need a payload index
        self.index_fail = False   # creating the payload index is refused

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append((method, path))
        if request.headers.get("api-key") != self.key:
            return httpx.Response(401, json={"status": {"error": "unauthorized"}})
        if self.fail == "network":
            raise httpx.ConnectError("boom")
        if self.fail and method == "POST":
            return httpx.Response(self.fail, json={})
        body = json.loads(request.content) if request.content else {}
        m = re.fullmatch(r"/collections(?:/([^/]+))?(/points(?:/query)?|/index)?", path)
        name, sub = m.group(1), m.group(2)
        if name is None:
            return httpx.Response(200, json={"result": {"collections": [{"name": n} for n in self.cols]}})
        if sub is None:
            if method == "GET":
                if name not in self.cols:
                    return httpx.Response(404, json={})
                return httpx.Response(200, json={"result": {"points_count": len(self.cols[name]["points"])}})
            if method == "PUT":
                assert body["vectors"]["distance"] == "Cosine" and body["vectors"]["size"] == vectorstore.DIM
                self.cols[name] = {"points": {}}
                return httpx.Response(200, json={"result": True, "status": "ok"})
            if method == "DELETE":
                self.cols.pop(name, None)
                return httpx.Response(200, json={"result": True})
        if sub == "/index" and method == "PUT":
            if self.index_fail:
                return httpx.Response(403, json={"status": {"error": "forbidden by strict mode"}})
            self.cols[name].setdefault("indexes", set()).add(body["field_name"])
            assert body["field_schema"] == "keyword"
            return httpx.Response(200, json={"result": {"status": "completed"}})
        if sub == "/points" and method == "PUT":
            for p in body["points"]:
                assert re.fullmatch(r"[0-9a-f-]{36}", p["id"]) and len(p["vector"]) == vectorstore.DIM
                self.cols[name]["points"][p["id"]] = p
            return httpx.Response(200, json={"result": {"status": "completed"}})
        if sub == "/points/query" and method == "POST":
            if name not in self.cols:
                return httpx.Response(404, json={})
            must = (body.get("filter") or {}).get("must", [])
            for f in must:
                if self.strict and f["key"] not in self.cols[name].get("indexes", set()):
                    return httpx.Response(400, json={"status": {"error": f'Index required but not found for "{f["key"]}"'}})
            scored = []
            for p in self.cols[name]["points"].values():
                if all(p["payload"].get(f["key"]) == f["match"]["value"] for f in must):
                    s = sum(a * b for a, b in zip(body["query"], p["vector"]))
                    if s >= body.get("score_threshold", -9):
                        scored.append({"id": p["id"], "score": s, "payload": p["payload"]})
            scored.sort(key=lambda x: -x["score"])
            return httpx.Response(200, json={"result": {"points": scored[:body["limit"]]}})
        return httpx.Response(400, json={})

    def count(self, method, suffix):
        return sum(1 for m, p in self.calls if m == method and p.endswith(suffix))


@pytest.fixture
def qd(monkeypatch):
    fake = FakeQdrant()
    monkeypatch.setenv("QDRANT_URL", URL)
    monkeypatch.setenv("QDRANT_API_KEY", KEY)
    monkeypatch.setattr(qdrant_backend, "_TRANSPORT", httpx.MockTransport(fake))
    vectorstore.REMOTE.update(state="off", collection=None, error=None, until=0.0, synced_fp=None)
    vectorstore._CACHE.clear()
    yield fake
    vectorstore.REMOTE.update(state="off", collection=None, error=None, until=0.0, synced_fp=None)


def local_hits(query, k=3, source=None):
    rows, mat, idf = vectorstore._load()
    q = vectorstore._unit(vectorstore._tf(knowledge.expand(query)) * idf)
    return vectorstore._local_search(rows, mat, q, k, source, 0.0)


# ------------------------------------------------------------------------------------------ off by default
def test_without_configuration_everything_stays_local(monkeypatch):
    monkeypatch.delenv("QDRANT_URL", raising=False)
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)
    knowledge.ensure_index()
    hits, backend = knowledge.search_ex("complex structured product")
    assert backend == "local" and hits
    st = vectorstore.backend_status()
    assert st == {"backend": "local", "qdrant_configured": False, "qdrant_state": "off", "qdrant_error": None}


def test_url_without_key_is_not_configured(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", URL)
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)
    assert not qdrant_backend.configured()


# ------------------------------------------------------------------------------------------ sync and search
def test_index_is_mirrored_to_qdrant_with_one_point_per_chunk(qd):
    assert knowledge.ensure_index() == 61
    (name, col), = qd.cols.items()
    assert name.startswith("wealthguard_kb_") and len(col["points"]) == 61
    p = next(iter(col["points"].values()))
    assert set(p["payload"]) == {"id", "source", "ref", "lang", "title", "text", "url"}
    assert vectorstore.backend_status()["backend"] == "qdrant"


def test_searches_are_answered_by_qdrant_and_match_the_local_index(qd):
    knowledge.ensure_index()
    for q in ["Can a retail customer buy a complex structured product?", "which license applies to the Shiller data",
              "什么情况下可以转化为专业投资者"]:
        hits, backend = knowledge.search_ex(q, k=3)
        local = local_hits(q, k=3)
        assert backend == "qdrant"
        assert [h["ref"] for h in hits] == [h["ref"] for h in local]
        assert [h["score"] for h in hits] == pytest.approx([h["score"] for h in local], abs=1e-3)
    assert qd.count("POST", "/points/query") == 3


def test_source_filter_and_threshold_are_sent_to_qdrant(qd):
    knowledge.ensure_index()
    hits, backend = knowledge.search_ex("risk disclosure", k=5, source="csrc_suitability")
    assert backend == "qdrant" and hits and all(h["source"] == "csrc_suitability" for h in hits)
    assert knowledge.basis_for_rule("R3")["article_no"] == 16      # rule basis goes through the same backend


def test_unchanged_index_is_not_uploaded_again_but_a_new_version_replaces_the_old(qd, monkeypatch):
    knowledge.ensure_index()
    uploads = qd.count("PUT", "/points")
    knowledge.ensure_index()
    vectorstore.REMOTE.update(state="off", synced_fp=None)             # simulate a fresh process
    knowledge.ensure_index()
    assert qd.count("PUT", "/points") == uploads                       # collection already complete: reused
    monkeypatch.setattr(knowledge, "_fingerprint", lambda its: "newversion123456")
    knowledge.ensure_index()
    assert list(qd.cols) == ["wealthguard_kb_newversion12"]           # old collection removed


# ------------------------------------------------------------------------------------------ failure handling
def test_server_error_falls_back_to_local_then_recovers(qd):
    knowledge.ensure_index()
    qd.fail = 500
    hits, backend = knowledge.search_ex("promise guaranteed returns", k=2)
    assert backend == "local" and hits[0]["ref"] == local_hits("promise guaranteed returns", 2)[0]["ref"]
    assert vectorstore.backend_status()["qdrant_state"] == "error"
    queries = qd.count("POST", "/points/query")
    knowledge.search_ex("promise guaranteed returns", k=2)
    assert qd.count("POST", "/points/query") == queries                # cooldown: no hammering a failing service
    qd.fail = None
    vectorstore.REMOTE["until"] = 0.0                                  # cooldown over
    _, backend = knowledge.search_ex("promise guaranteed returns", k=2)
    assert backend == "qdrant" and vectorstore.backend_status()["qdrant_state"] == "ok"


def test_network_error_falls_back_to_local(qd):
    qd.fail = "network"
    vectorstore._CACHE.clear()
    knowledge.ensure_index()
    hits, backend = knowledge.search_ex("elderly investors special protection", k=1)
    assert backend == "local" and hits[0]["ref"] == "第七条"
    assert vectorstore.backend_status()["qdrant_error"] == "network error: ConnectError"


def test_wrong_api_key_never_breaks_search_and_the_key_is_not_leaked(monkeypatch, qd):
    monkeypatch.setenv("QDRANT_API_KEY", "wrong-key-xyz")
    knowledge.ensure_index()
    hits, backend = knowledge.search_ex("penalties for firms", k=1)
    assert backend == "local" and hits
    st = json.dumps(vectorstore.backend_status())
    assert "HTTP 401" in st and "wrong-key-xyz" not in st and KEY not in st and URL not in st


def test_startup_never_fails_when_qdrant_is_down(qd):
    qd.fail = "network"
    assert c.get("/api/health").json()["ok"] is True


# ------------------------------------------------------------------------------------------ security
def test_only_https_and_the_configured_origin_are_allowed(monkeypatch, qd):
    assert tiers.is_url_allowed(URL + "/collections") and not tiers.is_url_allowed("https://evil.example/collections")
    assert not tiers.is_url_allowed("http://demo-cluster.qdrant.example:6333/collections")
    assert URL.replace(":6333", ":6333") in config.url_allowlist()
    monkeypatch.delenv("QDRANT_URL")
    assert not tiers.is_url_allowed(URL + "/collections")              # allowed only while configured


def test_plain_http_url_is_blocked_before_any_request(monkeypatch, qd):
    monkeypatch.setenv("QDRANT_URL", "http://insecure.example:6333")
    knowledge.ensure_index()
    assert qd.calls == [] and knowledge.search_ex("risk", k=1)[1] == "local"
    assert "allowlist" in (vectorstore.backend_status()["qdrant_error"] or "")


# ------------------------------------------------------------------------------------------ API visibility
def test_api_reports_the_backend_and_audits_it(qd):
    cid = c.post("/api/session", json={"persona_id": "persona_li"}).json()["client_id"]
    r = c.get("/api/knowledge/search", params={"q": "risk warning disclosure", "client_id": cid}).json()
    assert r["backend"] == "qdrant" and r["results"]
    entry = [e for e in c.get("/api/audit", params={"client_id": cid}).json() if e["action"] == "knowledge_search"][-1]
    assert c.get("/api/audit/verify").json()["valid"] and entry["tier"] == "T0"
    health = c.get("/api/health").json()
    assert health["vector_db"]["backend"] == "qdrant" and KEY not in json.dumps(health) and URL not in json.dumps(health)


# ------------------------------------------------------------------------------------------ strict mode (Qdrant Cloud default)
def test_payload_index_is_created_so_filtered_search_works_in_strict_mode(qd):
    qd.strict = True
    knowledge.ensure_index()
    (name, col), = qd.cols.items()
    assert col["indexes"] == {"source"}
    hits, backend = knowledge.search_ex("risk disclosure", k=3, source="csrc_suitability")
    assert backend == "qdrant" and hits and all(h["source"] == "csrc_suitability" for h in hits)


def test_filtered_search_still_answered_by_qdrant_when_the_index_cannot_be_created(qd):
    qd.strict, qd.index_fail = True, True
    knowledge.ensure_index()
    hits, backend = knowledge.search_ex("Can a retail customer buy a complex structured product?", k=3,
                                         source="csrc_suitability")
    assert backend == "qdrant" and vectorstore.backend_status()["qdrant_state"] == "ok"
    assert [h["ref"] for h in hits] == [h["ref"] for h in local_hits("Can a retail customer buy a complex structured product?", 3, "csrc_suitability")]
    assert qd.count("POST", "/points/query") == 2   # the refused filtered query, then the unfiltered one


def test_server_reason_is_reported_without_secrets(qd):
    qd.fail = 500
    knowledge.ensure_index()
    knowledge.search_ex("risk", k=1)
    err = vectorstore.backend_status()["qdrant_error"]
    assert err.startswith("HTTP 500") and KEY not in err and URL not in err


def test_an_existing_collection_without_the_index_gets_it_on_the_next_start(qd):
    qd.strict = True
    knowledge.ensure_index()
    (name, col), = qd.cols.items()
    col["indexes"].clear()                                   # a collection uploaded before the index existed
    vectorstore.REMOTE.update(state="off", synced_fp=None)   # new process
    knowledge.ensure_index()
    assert col["indexes"] == {"source"} and len(col["points"]) == 61
