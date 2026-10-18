"""The Vercel entry point must import cleanly, keep its DB in the temp dir (/tmp on Vercel) and serve both UI and API."""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_vercel_entry_serves_ui_and_api():
    code = (
        "import os, json; os.environ.pop('WEALTHGUARD_DB', None); os.environ['USE_MOCK_LLM']='1';"
        "import importlib.util as u; s=u.spec_from_file_location('idx','api/index.py'); m=u.module_from_spec(s); s.loader.exec_module(m);"
        "from fastapi.testclient import TestClient; c=TestClient(m.app);"
        "cid=c.post('/api/session', json={'persona_id':'persona_li'}).json()['client_id'];"
        "print(json.dumps({'db': os.environ['WEALTHGUARD_DB'], 'home': 'chatInput' in c.get('/').text,"
        "'reply': 'reply' in c.post('/api/chat', json={'client_id':cid,'message':'hi'}).json()}))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    res = json.loads(out.stdout.strip().splitlines()[-1])
    assert res["db"] == os.path.join(tempfile.gettempdir(), "wealthguard.db") and res["home"] and res["reply"]


def test_vercel_config_routes_everything_to_the_function():
    cfg = json.load(open(os.path.join(ROOT, "vercel.json")))
    assert cfg["rewrites"][0]["destination"] == "/api/index"
    assert "static" in cfg["functions"]["api/index.py"]["includeFiles"]
    ignore = open(os.path.join(ROOT, ".vercelignore")).read()
    assert "*.db" in ignore
