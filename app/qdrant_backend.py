"""Optional Qdrant Cloud backend for the knowledge base (REST API over HTTPS, no extra library).

Configured by QDRANT_URL and QDRANT_API_KEY (.env). When set, the vectors built locally are mirrored to a Qdrant
collection and searches go to Qdrant; if the service is missing, slow or erroring, vectorstore.py falls back to the
local SQLite index, so the app never depends on it. Every call is checked against the URL allowlist (the Qdrant origin is
allowed only because the operator configured it), and the API key is sent only as the `api-key` header, never logged.
"""
import uuid

from app import config

BATCH = 64
TIMEOUT = 10.0
_TRANSPORT = None  # tests inject httpx.MockTransport here


class QdrantError(Exception):
    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


def configured() -> bool:
    return bool(config.qdrant_url() and config.qdrant_key())


def collection_name(fp: str) -> str:
    return f"{config.qdrant_prefix()}_{fp[:12]}"


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"wealthguard:{chunk_id}"))


def _detail(r) -> str:
    """A short server-side reason (Qdrant error text), never the request headers or key."""
    try:
        j = r.json()
        d = (j.get("status") or {}).get("error") if isinstance(j.get("status"), dict) else j.get("detail")
        return f": {str(d)[:120]}" if d else ""
    except Exception:
        return ""


def _call(method: str, path: str, json=None, params=None) -> dict:
    import httpx
    from app.security import tiers  # lazy: tiers imports modules that import this one
    url = config.qdrant_url() + path
    if not tiers.is_url_allowed(url):
        raise QdrantError("blocked: URL is not on the allowlist (https and QDRANT_URL origin only)")
    try:
        with httpx.Client(timeout=TIMEOUT, transport=_TRANSPORT) as c:
            r = c.request(method, url, json=json, params=params, headers={"api-key": config.qdrant_key()})
    except httpx.HTTPError as e:
        raise QdrantError(f"network error: {type(e).__name__}") from None
    if r.status_code >= 400:
        raise QdrantError(f"HTTP {r.status_code}{_detail(r)}", r.status_code)
    try:
        return r.json()
    except ValueError:
        raise QdrantError("invalid JSON from server") from None


def _exists(name: str) -> int | None:
    """points_count if the collection exists, else None."""
    try:
        out = _call("GET", f"/collections/{name}")
    except QdrantError as e:
        if e.status == 404:
            return None
        raise
    res = out.get("result") or {}
    return int(res.get("points_count") or 0)


def sync(rows, mat, fp: str) -> dict:
    """Make sure the collection for this index fingerprint exists and holds every chunk. Idempotent."""
    name = collection_name(fp)
    have = _exists(name)
    if have == len(rows):
        state = "reused"
    else:
        if have is not None:
            _call("DELETE", f"/collections/{name}")
        _call("PUT", f"/collections/{name}", json={"vectors": {"size": int(mat.shape[1]), "distance": "Cosine"}})
        try:  # Qdrant Cloud's strict mode refuses filters on unindexed fields, so index the one we filter on
            _call("PUT", f"/collections/{name}/index", json={"field_name": "source", "field_schema": "keyword"},
                  params={"wait": "true"})
        except QdrantError:
            pass  # search() then filters client-side
        for i in range(0, len(rows), BATCH):
            pts = [{"id": point_id(r["id"]), "vector": [float(x) for x in mat[j]],
                    "payload": {"id": r["id"], "source": r["source"], "ref": r["ref"], "lang": r["lang"],
                                "title": r["title"], "text": r["text"], "url": r["url"]}}
                   for j, r in enumerate(rows[i:i + BATCH], start=i)]
            _call("PUT", f"/collections/{name}/points", json={"points": pts}, params={"wait": "true"})
        state = "uploaded"
    try:  # tidy: drop collections of older index versions (free clusters are small)
        for c in (_call("GET", "/collections").get("result") or {}).get("collections", []):
            n = c.get("name", "")
            if n.startswith(config.qdrant_prefix() + "_") and n != name:
                _call("DELETE", f"/collections/{n}")
    except QdrantError:
        pass
    return {"collection": name, "state": state, "points": len(rows)}


def _query(vector, fp: str, limit: int, flt: dict | None, min_score: float) -> list[dict]:
    body = {"query": [float(x) for x in vector], "limit": limit, "with_payload": True}
    if flt:
        body["filter"] = flt
    if min_score > 0:
        body["score_threshold"] = float(min_score)
    out = _call("POST", f"/collections/{collection_name(fp)}/points/query", json=body)
    pts = (out.get("result") or {}).get("points")
    if pts is None:
        raise QdrantError("unexpected response shape")
    hits = []
    for p in pts:
        pl = p.get("payload") or {}
        hits.append({"id": pl.get("id", ""), "source": pl.get("source", ""), "ref": pl.get("ref", ""),
                     "lang": pl.get("lang", ""), "title": pl.get("title", ""), "text": pl.get("text", ""),
                     "url": pl.get("url", ""), "score": round(float(p.get("score", 0.0)), 4)})
    return hits


def search(vector, fp: str, k: int, source: str | None, min_score: float) -> list[dict]:
    if not source:
        return _query(vector, fp, k, None, min_score)
    try:
        return _query(vector, fp, k, {"must": [{"key": "source", "match": {"value": source}}]}, min_score)
    except QdrantError as e:
        if e.status != 400:  # 400 = the server refused the filter (e.g. no payload index): filter here instead
            raise
    return [h for h in _query(vector, fp, 200, None, min_score) if h["source"] == source][:k]
