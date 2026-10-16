"""Reset the database and print the demo personas. Usage: python scripts/demo_seed.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, db  # noqa: E402
from app.products import load_personas  # noqa: E402
from app.security import audit  # noqa: E402

if __name__ == "__main__":
    db.reset()
    audit.append("system", "demo_reset", "T0", {})
    print(f"Database reset: {config.db_path()}")
    for p in load_personas().values():
        print(f"- {p['name']}: {p['story']}")
    print(config.DISCLAIMER)
