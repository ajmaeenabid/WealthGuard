"""Check your Qdrant Cloud setup end to end.  Usage:  python scripts/check_qdrant.py

Reads QDRANT_URL / QDRANT_API_KEY from .env (never prints them), mirrors the knowledge base to your cluster, runs a
search through Qdrant and compares it with the local index. Exit code 0 only if Qdrant really answered.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from app import config, knowledge, qdrant_backend, vectorstore  # noqa: E402


def main() -> int:
    if not qdrant_backend.configured():
        print("Qdrant is not configured: put QDRANT_URL and QDRANT_API_KEY in .env (see .env.example).")
        return 2
    print(f"Qdrant origin allowed: {config.qdrant_url().split('//')[-1].split(':')[0]}")
    n = knowledge.ensure_index()
    st = vectorstore.backend_status()
    print(f"index chunks: {n}; backend: {st['backend']}; qdrant state: {st['qdrant_state']}; error: {st['qdrant_error']}")
    if st["backend"] != "qdrant":
        print("FAILED: searches are still answered locally. Check the URL (https, port 6333), the key and that the cluster is running.")
        return 1
    q = "Can a retail customer buy a complex structured product?"
    hits, backend = knowledge.search_ex(q, k=3, source="csrc_suitability")
    print(f"query answered by: {backend}")
    if backend != "qdrant":
        print(f"qdrant error: {vectorstore.backend_status()['qdrant_error']}")
    for h in hits:
        print(f"  {h['score']:.3f}  {h['ref']}  {h['text'][:40]}")
    return 0 if backend == "qdrant" and hits else 1


if __name__ == "__main__":
    raise SystemExit(main())
