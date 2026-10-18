"""Verify an advice receipt offline.   Usage:  python scripts/verify_receipt.py receipt.json [--server http://localhost:8000]

Offline (needs no server, no key): recomputes the content hash, recomputes every audit entry hash and compares the dataset hashes
with the files in this repository. With --server it also asks the issuing server to check membership, the chain anchor and the HMAC
checkpoint. Exit code 0 only if everything that was checked passed.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from app import receipt  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--server", help="base URL of the issuing server, for the checks that need its audit log and key")
    a = ap.parse_args()
    with open(a.file, encoding="utf-8") as f:
        r = json.load(f)
    ok = True

    def show(name, good, detail):
        nonlocal ok
        ok &= good
        print(f"[{'OK' if good else 'FAIL'}] {name}: {detail}")

    try:
        content = receipt._content_of(r)
        show("content hash", receipt._sha(content) == r["content_hash"], f"sha256 {r['content_hash'][:16]}...")
        bad = receipt.check_entry_hashes(content["audit"]["entries"])
        show("audit entry hashes", not bad, f"{len(content['audit']['entries'])} entries" + (f", bad: {bad}" if bad else ""))
        badd = receipt.check_data_hashes(r)
        show("dataset hashes", not badd, f"{len(r['data_provenance'])} datasets" + (f", changed: {badd}" if badd else ""))
        comp = content["compliance"]
        show("compliance", comp["passed"] and all(c["passed"] for c in comp["checks"]), f"{len(comp['checks'])} checks passed")
        cp = r["checkpoint"]
        print(f"anchor: audit chain head #{cp['head_id']} {cp['head_hash'][:16]}... (compare with the server's /api/audit/verify head)")
    except (KeyError, TypeError) as e:
        print(f"[FAIL] not a valid receipt ({type(e).__name__}: {e})")
        return 1
    if a.server:
        import httpx
        res = httpx.post(a.server.rstrip("/") + "/api/receipt/verify", json={"receipt": r}, timeout=20).json()
        for c in res["checks"]:
            show("server: " + c["name"], c["ok"], c["detail"])
    else:
        print("(membership, chain anchor and HMAC checkpoint need the issuing server: add --server URL)")
    print("RESULT:", "valid" if ok else "NOT valid")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
