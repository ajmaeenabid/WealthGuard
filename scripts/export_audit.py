"""Print the full audit log (with chain verification result) as JSON - execution evidence for submission."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.security import audit

if __name__ == "__main__":
    print(json.dumps({"verify": audit.verify(), "entries": audit.list_entries()}, indent=1))
