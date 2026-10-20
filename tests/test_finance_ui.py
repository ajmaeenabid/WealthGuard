"""Static checks for the Money workspace and for secrets never reaching the browser."""
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
HTML = c.get("/").text
JS = c.get("/static/finance.js").text
CSS = c.get("/static/finance.css").text


def test_assets_are_served_and_the_script_parses():
    assert c.get("/static/finance.js").status_code == 200 and c.get("/static/finance.css").status_code == 200
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    r = subprocess.run([node, "--check", "static/finance.js"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[:300]


def test_workspace_markup_has_every_tab_the_switch_and_the_assistant_controls():
    for el in ['id="modeSwitch"', 'id="modeMoney"', 'id="moneyView"', 'id="finTab-overview"', 'id="finTab-transactions"', 'id="finTab-accounts"',
               'id="finTab-plan"', 'id="finTab-reports"', 'id="finTab-assistant"', 'id="finMic"', 'id="finInput"', 'id="finSend"', 'id="finYes"', 'id="finModal"']:
        assert HTML.count(el) == 1, el
    for tab in ["overview", "transactions", "accounts", "plan", "reports", "assistant"]:
        assert HTML.count(f'data-tab="{tab}"') == 2, tab
    assert 'href="/static/finance.css"' in HTML and HTML.index("/static/app.js") < HTML.index("/static/finance.js")


def test_workspace_is_only_shown_in_money_mode_and_advisor_screens_are_hidden_there():
    assert 'body:not(.mode-money) [data-for="money"]' in CSS and "body.mode-money .chat" in CSS and "body.mode-money [data-for=\"user\"]" in CSS


def test_voice_input_offers_bangla_and_the_microphone_is_wired_to_the_assistant():
    assert 'value="bn-BD"' in HTML
    voice = c.get("/static/voice.js").text
    assert 'attach("finMic", "finInput", "finNote")' in voice and '"bn"' in voice


def test_retries_reuse_the_request_id_and_forms_carry_an_idempotency_key():
    assert "request_id" in JS and "A.pending" in JS and "uuid()" in JS
    assert "idempotency_key" in JS and "Send again" in JS


def test_money_is_never_computed_with_floats_in_the_browser():
    assert "toMinor" in JS and "fromMinor" in JS
    assert "parseFloat" not in JS
    assert re.search(r"Number\(", JS)


def test_dynamic_text_is_escaped_before_it_reaches_innerhtml():
    assert "const esc" in JS and JS.count("esc(") > 150
    assert "textContent" in JS


def test_no_api_key_or_provider_secret_is_present_in_anything_the_browser_loads():
    for name in ["finance.js", "finance.css", "app.js", "auth.js", "voice.js", "ui.js", "i18n.js"]:
        body = c.get(f"/static/{name}").text
        assert "gsk_" not in body and "GROQ_API_KEY" not in body and "api.groq.com" not in body, name
    assert "gsk_" not in HTML and "api.groq.com" not in HTML
    health = c.get("/api/health").text
    assert "gsk_" not in health and "GROQ_API_KEY" not in health


def test_charts_have_text_alternatives_and_empty_states():
    assert 'role="img"' in JS and "aria-label" in JS and "emptyHtml(" in JS
    assert "No budgets yet" in JS and "No spending recorded" in JS and "Add your accounts" in JS


def test_forecasts_and_estimates_are_labelled_as_estimates_in_the_interface():
    assert "estimate" in JS.lower() and "not a balance" in JS and "Forecast" in JS
    assert ".kpi.estimate" in CSS


def test_receipts_reminders_activity_and_report_language_are_wired_in_the_interface():
    for token in ["/receipt", "wireReceipt", "image/jpeg,image/png,image/webp", "checkReminders", "wg-notify", "modeBadge", "/activity", "rpLang", "localizeReport", "BN_LABELS"]:
        assert token in JS or token in HTML, token
    assert 'id="modeBadge"' in HTML and 'id="adminAi"' in HTML
    assert "only works while WealthGuard is open" in JS
    admin = c.get("/static/admin.js").text
    assert "/ai-usage" in admin and "never message text" in admin


def test_sign_in_is_per_tab_session_and_the_admin_member_list_really_hides():
    auth = c.get("/static/auth.js").text
    assert "sessionStorage.setItem(\"wg-token\"" in auth and "localStorage.setItem(\"wg-token\"" not in auth
    assert ".admin-users[hidden]" in c.get("/static/styles.css").text
