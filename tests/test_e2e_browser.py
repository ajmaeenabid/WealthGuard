"""Opt-in browser end-to-end run of the My money workspace (set RUN_E2E=1; needs Node and an installed Edge/Chrome)."""
import os
import shutil
import socket
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RUN_E2E") != "1", reason="set RUN_E2E=1 to run the browser end-to-end test")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_money_workspace_end_to_end(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    port = free_port()
    env = dict(os.environ, USE_MOCK_LLM="1", WEALTHGUARD_NO_DOTENV="1", WEALTHGUARD_DB=str(tmp_path / "e2e.db"))
    env.pop("WEALTHGUARD_AUTH", None)
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.5)
        r = subprocess.run([node, "scripts/e2e_money.mjs", f"http://127.0.0.1:{port}", str(tmp_path / "shots")], capture_output=True, text=True, encoding="utf-8", timeout=600)
        print(r.stdout.encode("ascii", "replace").decode())
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1000:]
    finally:
        server.terminate()
