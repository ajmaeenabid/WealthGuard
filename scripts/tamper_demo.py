"""Demo step 7: edit one audit row directly in SQLite, then show that verification fails at that row."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db
from app.security import audit

if __name__ == "__main__":
    print("before:", audit.verify())
    conn = db.connect()
    row = conn.execute("SELECT id FROM audit ORDER BY id LIMIT 1 OFFSET 2").fetchone()
    if not row:
        sys.exit("Not enough audit entries; run the demo first.")
    conn.execute("UPDATE audit SET action='edited_by_attacker' WHERE id=?", (row["id"],))
    conn.commit()
    conn.close()
    print(f"edited row {row['id']}")
    print("after: ", audit.verify())
