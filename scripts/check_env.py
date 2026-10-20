"""Print the configuration inventory: variable names, whether each is set and valid, what depends on it. Never prints a value. python scripts/check_env.py            table of every variable python scripts/check_env.py."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, envcheck

config.load_dotenv()
rows = envcheck.audit()
only_missing = "--missing" in sys.argv
example = open(".env.example", encoding="utf-8").read() if os.path.exists(".env.example") else ""
in_example = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", example, re.M))
print(f"{'Variable':28} {'Status':12} {'Need':12} Feature")
for r in rows:
    if only_missing and r["status"] == "set":
        continue
    print(f"{r['name']:28} {r['status']:12} {r['requirement']:12} {r['feature'][:60]}")
    for p in r["problems"]:
        print(f"{'':28} -> {p}")
    if r["status"] in ("unset", "empty") and r["obtain"] and only_missing:
        print(f"{'':28} obtain: {r['obtain']}  ({r['free'] or 'see provider'})")
print()
for line in envcheck.cross_checks():
    print("NOTE:", line)
print("Features:", envcheck.feature_status())
missing_from_example = [r["name"] for r in rows if r["name"] not in in_example]
if missing_from_example:
    print("Not documented in .env.example:", ", ".join(missing_from_example))
