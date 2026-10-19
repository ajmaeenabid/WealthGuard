from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


def test_index_and_assets_are_served():
    r = c.get("/")
    assert r.status_code == 200 and 'id="chatInput"' in r.text
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/static/styles.css").status_code == 200


def test_state_endpoint_reports_effective_bucket():
    cid = c.post("/api/session", json={"persona_id": "persona_wang"}).json()["client_id"]
    c.post("/api/profile", json={"client_id": cid, "answers": {
        "loss_reaction": "hold", "income_stability": "stable", "liquidity_need_pct": 25}})
    st = c.get("/api/state", params={"client_id": cid}).json()
    assert st["profile"]["bucket"] == "Balanced" and st["effective_bucket"] == "Moderate"


def test_voice_controls_and_script_served():
    html = c.get("/").text
    for el in ['id="micBtn"', 'id="speakBtn"', 'id="voiceLang"', '/static/voice.js']:
        assert el in html
    js = c.get("/static/voice.js")
    assert js.status_code == 200
    # voice only fills a text box: it may call the speech endpoint and the health check, never the agent, and never auto-sends
    import re
    assert set(re.findall(r"/api/[a-z]+", js.text)) == {"/api/transcribe", "/api/health"}
    assert "/api/chat" not in js.text and "onsubmit" not in js.text and "requestSubmit" not in js.text and ".submit(" not in js.text


def test_i18n_keys_in_html_exist_in_dictionary():
    import re
    html = c.get("/").text
    js = c.get("/static/i18n.js").text
    keys = set(re.findall(r'data-i18n(?:-ph)?="([^"]+)"', html))
    assert keys and 'id="langBtn"' in html and "/static/i18n.js" in html
    missing = [k for k in keys if not re.search(r'(^|[\s,{])"?' + re.escape(k) + r'"?\s*:', js)]
    assert not missing, missing


def test_chinese_banner_keeps_disclaimer():
    js = c.get("/static/i18n.js").text
    assert js.count("不构成真实的投资建议") >= 2  # banner and footer


def test_pages_and_scripts_are_revalidated_so_browsers_never_run_stale_code():
    for path in ["/", "/static/app.js", "/static/finance.js", "/static/styles.css"]:
        assert c.get(path).headers["cache-control"] == "no-cache", path
    assert "no-cache" not in c.get("/api/health").headers.get("cache-control", "")
