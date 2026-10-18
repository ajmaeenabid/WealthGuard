"""A small vector database on SQLite + numpy.

Chunks are embedded with a deterministic hashing TF-IDF embedder (Chinese character 2/3-grams, Latin words), stored as
float32 BLOBs, and searched by cosine similarity. It needs no network, no model download and no extra service, so mock
mode, the tests and the Vercel build all work the same way. The embedder is a thin class: a neural model could replace
it later without touching the store. Lexical overlap is what it measures, not deep semantics; knowledge.py adds a small
English->Chinese glossary so English questions can reach the Chinese regulation text.
"""
import hashlib
import math
import re
import threading
import unicodedata
from collections import Counter
from functools import lru_cache

import numpy as np

from app import config, db

DIM = 1024
_CJK = re.compile(r"[一-鿿]+")
_LATIN = re.compile(r"[a-z0-9]{2,}")
_LOCK = threading.RLock()
_CACHE: dict = {}


@lru_cache(maxsize=100_000)
def _slot(token: str) -> tuple[int, int]:
    h = int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big")
    return h % DIM, 1 if (h >> 40) & 1 else -1


def tokens(text: str) -> list[str]:
    t = unicodedata.normalize("NFKC", text).lower()
    out = []
    for run in _CJK.findall(t):
        for n in (2, 3):
            out += [run[i:i + n] for i in range(len(run) - n + 1)]
        if len(run) == 1:
            out.append(run)
    for w in _LATIN.findall(t):
        out.append(w[:-1] if len(w) > 3 and w.endswith("s") else w)
    return out


def _tf(text: str) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    for tok, c in Counter(tokens(text)).items():
        i, sign = _slot(tok)
        v[i] += sign * (1.0 + math.log(c))
    return v


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n else v


def _ensure_schema(conn) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS kb_chunks (
      id TEXT PRIMARY KEY, source TEXT NOT NULL, ref TEXT NOT NULL, lang TEXT NOT NULL, title TEXT NOT NULL,
      text TEXT NOT NULL, url TEXT NOT NULL, vec BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS kb_meta (key TEXT PRIMARY KEY, value BLOB NOT NULL);""")


def fingerprint() -> str | None:
    conn = db.connect()
    _ensure_schema(conn)
    r = conn.execute("SELECT value FROM kb_meta WHERE key='fingerprint'").fetchone()
    conn.close()
    return r["value"].decode() if r else None


def count(source: str | None = None) -> int:
    conn = db.connect()
    _ensure_schema(conn)
    q, p = "SELECT COUNT(*) FROM kb_chunks", ()
    if source:
        q, p = q + " WHERE source=?", (source,)
    n = conn.execute(q, p).fetchone()[0]
    conn.close()
    return n


def build(items: list[dict], fp: str) -> int:
    """Replace the whole index with `items` (id, source, ref, lang, title, text, url) and record its fingerprint."""
    raws = [_tf(f"{it['title']} {it['text']}") for it in items]
    df = np.zeros(DIM, dtype=np.float32)
    for r in raws:
        df += (r != 0)
    idf = (np.log((len(items) + 1) / (df + 1)) + 1.0).astype(np.float32)
    with db.LOCK, _LOCK:
        conn = db.connect()
        _ensure_schema(conn)
        conn.execute("DELETE FROM kb_chunks")
        for it, r in zip(items, raws):
            vec = _unit(r * idf).astype(np.float32)
            conn.execute("INSERT INTO kb_chunks VALUES (?,?,?,?,?,?,?,?)",
                         (it["id"], it["source"], it["ref"], it["lang"], it["title"], it["text"], it["url"],
                          vec.tobytes()))
        conn.execute("INSERT OR REPLACE INTO kb_meta VALUES ('idf', ?)", (idf.tobytes(),))
        conn.execute("INSERT OR REPLACE INTO kb_meta VALUES ('fingerprint', ?)", (fp.encode(),))
        conn.commit()
        conn.close()
        _CACHE.clear()
    return len(items)


def _load():
    key = (config.db_path(), fingerprint())
    with _LOCK:
        if _CACHE.get("key") == key:
            return _CACHE["data"]
        conn = db.connect()
        _ensure_schema(conn)
        rows = conn.execute("SELECT id, source, ref, lang, title, text, url, vec FROM kb_chunks ORDER BY rowid").fetchall()
        idf_row = conn.execute("SELECT value FROM kb_meta WHERE key='idf'").fetchone()
        conn.close()
        mat = np.vstack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows]) if rows else np.zeros((0, DIM), np.float32)
        idf = np.frombuffer(idf_row["value"], dtype=np.float32) if idf_row else np.ones(DIM, np.float32)
        _CACHE.update(key=key, data=(rows, mat, idf))
        return _CACHE["data"]


def search(query: str, k: int = 3, source: str | None = None, min_score: float = 0.0) -> list[dict]:
    rows, mat, idf = _load()
    if not len(rows):
        return []
    q = _unit(_tf(query) * idf)
    if not float(np.linalg.norm(q)):
        return []
    scores = mat @ q
    order = np.argsort(-scores, kind="stable")
    out = []
    for i in order:
        r = rows[int(i)]
        if source and r["source"] != source:
            continue
        s = float(scores[int(i)])
        if s < min_score:
            break
        out.append({"id": r["id"], "source": r["source"], "ref": r["ref"], "lang": r["lang"], "title": r["title"],
                    "text": r["text"], "url": r["url"], "score": round(s, 4)})
        if len(out) >= k:
            break
    return out
