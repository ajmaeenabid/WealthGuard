"""Voice mode: the voice-activity detector (run in Node) and the honest wiring of the browser parts (checked statically)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
NODE = shutil.which("node")


def run_vad(frames):
    script = (
        "const {createVad}=require(%s);const v=createVad();const out=[];"
        "for(const [lvl,t] of %s){for(const e of v.push(lvl,t))out.push([e,t]);}console.log(JSON.stringify(out));"
        % (json.dumps(str(STATIC / "voicemode.js")), json.dumps(frames))
    )
    return json.loads(subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout)


def frames(spec, step=50):
    """spec: list of (level, duration_ms)"""
    out, t = [], 0
    for lvl, dur in spec:
        for _ in range(dur // step):
            out.append([lvl, t])
            t += step
    return out


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_silence_produces_no_events():
    assert run_vad(frames([(0.003, 3000)])) == []


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_a_spoken_phrase_starts_and_ends_once():
    ev = [e for e, _ in run_vad(frames([(0.003, 500), (0.1, 1500), (0.003, 1500)]))]
    assert ev == ["candidate", "start", "end"]


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_a_click_or_cough_is_aborted_not_sent():
    ev = [e for e, _ in run_vad(frames([(0.003, 500), (0.1, 100), (0.003, 1500)]))]
    assert ev == ["candidate", "abort"]


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_a_pause_inside_a_sentence_does_not_split_it():
    ev = [e for e, _ in run_vad(frames([(0.1, 800), (0.003, 500), (0.1, 800), (0.003, 1500)]))]
    assert ev == ["candidate", "start", "end"]


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_a_long_monologue_is_cut_at_the_limit():
    ev = [e for e, _ in run_vad(frames([(0.1, 25000)]))]
    assert ev[:3] == ["candidate", "start", "end"]                        # cut at 20 s; speech that continues is captured as the next clip
    assert ev[3:] == ["candidate", "start"]


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_quiet_room_noise_adapts_without_false_starts():
    ev = [e for e, _ in run_vad(frames([(0.004, 2000), (0.006, 2000)]))]
    assert ev == []


def test_voice_mode_is_wired_honestly():
    js = (STATIC / "voicemode.js").read_text(encoding="utf-8")
    assert "NOT full-duplex" in js and "/api/transcribe" in js and "sendVoice" in js
    assert "No ${code} voice is installed" in js                          # text fallback when no voice for the language exists
    assert "speechSynthesis" in js and "synth.cancel()" in js             # barge-in
    for state in ("listening", "processing", "speaking"):
        assert state in js
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "voicemode.js" in html and 'id="finVoiceMode"' in html and "lang.js" in html
    assert "sendVoice" in (STATIC / "finance.js").read_text(encoding="utf-8")


def test_voice_input_uses_the_same_validated_endpoint_with_voice_source():
    fin = (STATIC / "finance.js").read_text(encoding="utf-8")
    assert '"/assistant/chat"' in fin and 'source: "voice"' in fin
