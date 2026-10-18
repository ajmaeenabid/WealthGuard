"""The app shell: sidebar navigation, feature drawer, Claude-style composer, separate voice dock, theme and accessibility hooks."""
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
HTML = c.get("/").text
CSS = c.get("/static/styles.css").text
UI = c.get("/static/ui.js").text
APP = c.get("/static/app.js").text
CARDS = ["profileCard", "allocCard", "compCard", "stressCard", "approvalCard", "ledgerCard", "rpCard", "kbCard",
         "rcCard", "rtCard", "siCard", "docCard", "auditCard"]


def block(open_tag_regex: str) -> str:
    """Text of the element that starts at the first match, up to its matching closing div (simple depth count)."""
    m = re.search(open_tag_regex, HTML)
    assert m, open_tag_regex
    depth, i = 0, m.start()
    for t in re.finditer(r"<div\b|</div>", HTML[m.start():]):
        depth += 1 if t.group(0) == "<div" else -1
        if depth == 0:
            return HTML[m.start(): m.start() + t.end()]
    raise AssertionError("unbalanced")


def test_every_feature_has_one_sidebar_button_and_one_card_in_the_drawer():
    navs = re.findall(r'<button[^>]*class="nav"[^>]*data-panel="(\w+)"', HTML)
    assert sorted(navs) == sorted(CARDS) and len(set(navs)) == 13
    drawer = block(r'<aside class="drawer"')
    for cid in CARDS:
        assert drawer.count(f'<div class="card" id="{cid}"') == 1, cid
        assert HTML.count(f'id="{cid}"') == 1
    for b in re.findall(r"<button[^>]*class=\"nav\"[^>]*>", HTML):
        assert 'aria-controls="' in b and 'aria-pressed="false"' in b


def test_the_advice_flow_is_a_five_step_thread_and_the_tools_are_grouped_apart():
    flow = block(r'<div class="flow">')
    assert flow.count('class="node"') == 5 and flow.count('class="nav"') == 5
    for cid in ["profileCard", "allocCard", "compCard", "stressCard", "approvalCard"]:
        assert f'data-panel="{cid}"' in flow
    assert HTML.count('class="group-label"') == 3


def test_the_composer_is_a_growing_textarea_with_send_on_one_side_and_voice_on_the_other():
    assert re.search(r'<textarea id="chatInput" rows="1" maxlength="4000"', HTML)
    composer = HTML[HTML.index('<form id="chatForm"'): HTML.index("</form>") + 7]
    dock = HTML[HTML.index('id="voiceBar"'): HTML.index('id="sendBtn"')]
    for el in ['id="micBtn"', 'id="speakBtn"', 'id="voiceEngine"', 'id="voiceLang"', 'id="vsetBtn"']:
        assert el in dock, el
    assert 'id="sendBtn"' not in dock and composer.index('id="voiceBar"') < composer.index('id="sendBtn"')


def test_quick_replies_and_suggestions_are_separate_and_the_suggestions_are_smaller():
    assert HTML.index('id="quick"') < HTML.index('id="chatForm"') < HTML.index('id="chips"')
    assert re.search(r"\.chips button \{[^}]*font-size: 12px", CSS) and re.search(r"\.quick button \{[^}]*font-size: 14px", CSS)


def test_icon_buttons_are_labelled_for_screen_readers():
    for bid in ["micBtn", "speakBtn", "vsetBtn", "sendBtn", "drawerClose", "menuBtn", "themeBtn", "ledgerMic"]:
        tag = re.search(rf'<button[^>]*id="{bid}"[^>]*>', HTML).group(0)
        assert "aria-label=" in tag, bid


def test_the_theme_script_does_not_leak_a_global_that_would_break_app_js():
    head = HTML[: HTML.index("</head>")]
    inline = re.findall(r"<script>(.*?)</script>", head, flags=re.S)
    assert inline and all(s.strip().startswith("(function") or "(function" in s for s in inline)
    top_level = set(re.findall(r"(?m)^(?:const|let|function|async function)\s+(\w+)", APP))
    for s in inline:
        for name in re.findall(r"\bvar\s+(\w+)", s.split("(function")[0]):
            assert name not in top_level


def test_scripts_load_in_the_right_order_and_all_parse():
    order = [HTML.index(f'/static/{n}.js') for n in ("i18n", "voice", "app", "ui")]
    assert order == sorted(order)
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    for name in ("i18n", "voice", "app", "ui"):
        r = subprocess.run([node, "--check", f"static/{name}.js"], capture_output=True, text=True)
        assert r.returncode == 0, (name, r.stderr[:300])


def test_theme_and_motion_and_small_screens_are_handled_in_css():
    assert ':root[data-theme="light"]' in CSS and "prefers-color-scheme: light" in CSS and "prefers-reduced-motion: reduce" in CSS
    assert "@media (max-width: 900px)" in CSS and "100dvh" in CSS and ":focus-visible" in CSS
    for kf in ["rise", "fadeslide", "bounce", "wave", "toastin", "recpulse", "breathe"]:
        assert f"@keyframes {kf}" in CSS


def test_shell_behaviour_is_in_ui_js_and_exposed_for_the_app():
    for token in ["openPanel", "closePanel", "Escape", "wg-theme", "requestSubmit", "WGUI", "has-update", "MutationObserver"]:
        assert token in UI, token
    assert "window.WGUI.progress" in APP and "window.WGApp" in APP


def test_the_disclaimer_still_shows_on_every_screen_and_replies_show_it_quietly():
    assert 'class="banner"' in HTML and "Not real financial advice" in HTML[HTML.index("<footer"):]
    assert "disc" in APP and ".msg .disc" in CSS


def test_the_start_flow_has_a_hero_with_client_cards_and_keeps_the_classic_selector():
    assert 'id="heroCards"' in HTML and 'id="persona"' in HTML and 'id="start"' in HTML
    assert "persona-card" in UI and "/api/personas" in UI


def test_navigation_labels_and_hero_copy_have_chinese_translations():
    z = c.get("/static/i18n.js").text
    keys = set(re.findall(r'data-i18n="(\w+)"', HTML))
    for k in keys:
        assert re.search(rf'(^|[\s,{{])"?{k}"?\s*:', z), k
    assert "咨询流程" in z and "可以验证的建议" in z


def test_charts_use_the_theme_colours():
    assert "PALETTE" in APP and "styleCharts" in UI and "Chart.defaults.color" in UI
