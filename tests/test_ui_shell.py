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
         "rcCard", "rtCard", "siCard", "docCard", "auditCard", "memCard"]


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
    assert sorted(navs) == sorted(CARDS) and len(set(navs)) == 14
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
    for name in ("auth", "i18n", "voice", "app", "ui"):
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


def test_the_screen_has_no_disclaimer_lines_and_chat_replies_hide_the_api_disclaimer():
    assert 'class="banner"' not in HTML and "<footer" not in HTML and "Not real financial advice" not in HTML
    assert "syncBanner" not in UI and "s.disclaimer" not in APP
    assert "d.textContent = m && m[1].trim() ? m[1] : body" in APP     # the API reply keeps it; the bubble drops it


def test_the_welcome_page_greets_the_user_by_name_and_there_is_no_client_list_or_client_cards():
    assert 'id="heroName"' in HTML and 'id="heroMemory"' in HTML and 'id="start"' in HTML
    assert 'id="heroCards"' not in HTML and 'id="personaRow"' not in HTML and "persona-card" not in UI
    assert HTML.count('id="persona"') == 1 and HTML.index('id="persona"') > HTML.index('id="memCard"')   # only the demo-profile loader
    assert "function newChatView" in APP and "paintHero" in APP
    assert re.search(r"async function startSession\(\) \{\s*const s = await api\(\"/api/conversations\", \{\}\);", APP)


def test_navigation_labels_and_hero_copy_have_chinese_translations():
    z = c.get("/static/i18n.js").text
    keys = set(re.findall(r'data-i18n="(\w+)"', HTML))
    for k in keys:
        assert re.search(rf'(^|[\s,{{])"?{k}"?\s*:', z), k
    assert "咨询流程" in z and "可以验证的建议" in z


def test_charts_use_the_theme_colours():
    assert "PALETTE" in APP and "styleCharts" in UI and "Chart.defaults.color" in UI


# ------------------------------------------------------------------------------------------ voice text and the Send button
def test_the_composer_works_before_a_session_and_send_follows_the_text():
    assert not re.search(r'<textarea id="chatInput"[^>]*\bdisabled\b', HTML)          # no longer locked until a session exists
    assert "syncSend" in APP and "!$(\"chatInput\").value.trim()" in APP                 # Send is enabled by having text
    assert re.search(r"async function send\(text\) \{\s*if \(!text\.trim\(\)\) return;\s*if \(!clientId\)", APP)   # starts a session itself
    voice = c.get("/static/voice.js").text
    assert voice.count('new Event("input"') == 1 and voice.count("announce(input)") >= 2     # spoken text tells the page it changed


@pytest.mark.parametrize("raw,expected", [
    ("Hello, how are you? Hello, how are you?", "Hello, how are you?"),
    ("hello how are you  Hello, how are you?", "hello how are you"),
    ("I bought headphones I bought headphones I bought headphones", "I bought headphones"),
    ("no no", "no no"), ("yes yes yes", "yes yes yes"), ("Hello hello", "Hello hello"),
    ("buy a laptop buy a phone", "buy a laptop buy a phone"), ("cancel the laptop", "cancel the laptop"),
    ("你好你好", "你好"), ("买了耳机", "买了耳机"), ("", ""),
])
def test_repeated_phrases_from_speech_recognition_are_collapsed_but_real_speech_is_kept(raw, expected):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    js = ("global.window = {}; global.document = {addEventListener() {}, getElementById() { return null; }};"
          "require('./static/voice.js'); console.log(JSON.stringify(window.WGVoice.tidy(process.argv[1])));")
    r = subprocess.run([node, "-e", js, raw], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:300]
    import json
    assert json.loads(r.stdout) == expected


# ------------------------------------------------------------------------------------------ accounts, saved chats, icons
AUTH = c.get("/static/auth.js").text
I18N = c.get("/static/i18n.js").text


def test_sign_in_page_settings_dialog_and_user_box_exist_and_auth_loads_first():
    for el in ['id="auth"', 'id="authForm"', 'id="tabLogin"', 'id="tabSignup"', 'id="authUser"', 'id="authPass"', 'id="settings"',
               'id="pwForm"', 'id="pwOld"', 'id="pwNew"', 'id="pwNew2"', 'id="userBox"', 'id="settingsBtn"', 'id="logoutBtn"']:
        assert HTML.count(el) == 1, el
    assert HTML.index("/static/auth.js") < HTML.index("/static/i18n.js") < HTML.index("/static/app.js")
    assert 'Bearer' in AUTH and "/api/auth/password" in AUTH and "WGAuth" in AUTH and "WGAuth.onReady" in APP
    assert "Password 123" in HTML          # the demo hint tells people which accounts exist


def test_chat_history_ui_lists_opens_creates_and_deletes_chats():
    assert 'id="chatList"' in HTML and 'id="start"' in HTML and 'data-i18n="newChat"' in HTML
    for token in ["/api/conversations", "openChat", "deleteChat", "refreshChats", "beginChat"]:
        assert token in APP, token
    assert "chat-item" in CSS and ".ci-del" in CSS


def test_voice_settings_no_longer_use_a_sun_icon_and_the_tagline_is_a_real_headline():
    btn = re.search(r'<button[^>]*id="vsetBtn".*?</button>', HTML, re.S).group(0)
    assert "M12 2.5v3M12 18.5v3" not in btn and 'r="2"' in btn        # sun rays are gone, sliders are in
    assert HTML.count('class="vrow"') == 2
    assert 'class="tg-main"' in HTML and 'class="tg-sub"' in HTML
    size = int(re.search(r"\.tg-main \{[^}]*font:[^;]*?(\d+)px", CSS).group(1))
    assert size >= 19


def test_new_interface_words_have_chinese_translations():
    for k in ["newChat", "navChats", "noChats", "signIn", "signUp", "username", "password", "settings", "changePassword", "tagline2", "authHint"]:
        assert re.search(rf'(^|[\s,{{])"?{k}"?\s*:', I18N), k
    for phrase in ["Delete this chat?", "The two passwords do not match.", "Password changed. Other devices were signed out."]:
        assert f'"{phrase}"' in I18N, phrase


def test_memory_panel_and_admin_console_exist_and_admins_do_not_see_the_client_screens():
    for el in ['id="memCard"', 'id="memFacts"', 'id="memNotes"', 'id="memSums"', 'id="memNoteAdd"', 'id="memDemo"', 'id="memClear"',
               'id="adminView"', 'id="adminUsers"']:
        assert HTML.count(el) == 1, el
    for token in ["/api/memory", "/api/admin/users", "applyAccess", "adminRender", "memRender", "FEATURE_PANELS"]:
        assert token in APP, token
    assert '.is-admin [data-for="user"]' in CSS and ".is-admin .chat" in CSS and ".nav[hidden]" in CSS
    for pid in ["profileCard", "allocCard", "ledgerCard", "memCard", "docCard"]:
        assert re.search(rf'data-panel="{pid}" data-for="user"', HTML), pid
    for pid in ["auditCard", "rtCard", "siCard"]:                                     # what an administrator keeps: oversight
        assert f'data-panel="{pid}" data-for="user"' not in HTML, pid
