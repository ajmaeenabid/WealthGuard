"""Chat replies render as formatted text (tables, lists, bold) through a renderer that escapes everything first."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "static"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="node is not installed")

TABLE = """Here's a draft allocation:

| Product | Weight | Why it's in the mix |
|-----|----|-----------|
| P08 – Diversified Equity Fund | 20.0% | Provides growth potential |
| P05 – Corporate Bond Fund | 14.7% | Adds steady income |

Why this mix?
- Growth vs. safety: **40%** in equities
- Liquidity: 10% short-term
"""


def run(fn, arg):
    code = f"const m=require({json.dumps(str(STATIC / 'markdown.js'))});console.log(JSON.stringify(m.{fn}({json.dumps(arg)})))"
    return json.loads(subprocess.run([NODE, "-e", code], capture_output=True, text=True, encoding="utf-8", check=True).stdout)


def test_a_pipe_table_becomes_a_real_table_with_header_and_numeric_alignment():
    html = run("render", TABLE)
    assert html.count("<table>") == 1 and html.count("</th>") == 3 and html.count("<tr>") == 3
    assert '<th>Product</th>' in html and "<td>P08 – Diversified Equity Fund</td>" in html
    assert 'class="a-right">20.0%' in html and "|---" not in html
    assert "<strong>40%</strong>" in html and "<ul>" in html and html.count("<li>") == 2


def test_markup_in_a_reply_is_escaped_never_executed():
    html = run("render", '<script>alert(1)</script> **x** | a | b |\n<img src=x onerror=alert(1)>')
    assert "<script" not in html and "<img" not in html and "&lt;script&gt;" in html


def test_a_lone_pipe_line_is_not_mistaken_for_a_table():
    assert "<table" not in run("render", "a | b | c\njust text | here |")


def test_plain_text_for_speech_has_no_pipes_or_asterisks():
    plain = run("plain", TABLE)
    assert "|" not in plain and "*" not in plain and "P08 – Diversified Equity Fund, 20.0%" in plain


def test_chats_use_the_renderer_and_it_is_loaded():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    fin = (STATIC / "finance.js").read_text(encoding="utf-8")
    assert "WGMarkdown.render" in app and "WGMarkdown.render" in fin and "WGMarkdown.plain" in app
    assert "/static/markdown.js" in (STATIC / "index.html").read_text(encoding="utf-8")
