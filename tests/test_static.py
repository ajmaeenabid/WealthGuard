from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


def test_index_and_assets_carry_disclaimer():
    r = c.get("/")
    assert r.status_code == 200 and "Not real financial advice" in r.text
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/static/styles.css").status_code == 200


def test_state_endpoint_reports_effective_bucket():
    cid = c.post("/api/session", json={"persona_id": "persona_wang"}).json()["client_id"]
    c.post("/api/profile", json={"client_id": cid, "answers": {
        "loss_reaction": "hold", "income_stability": "stable", "liquidity_need_pct": 25}})
    st = c.get("/api/state", params={"client_id": cid}).json()
    assert st["profile"]["bucket"] == "Balanced" and st["effective_bucket"] == "Moderate"
