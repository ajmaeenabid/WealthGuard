"""Check Whisper voice transcription end to end.   Usage:  python scripts/check_whisper.py [--file audio.wav] [--language en|zh] [--no-call]"""
import argparse
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from app import transcribe

SENTENCE = "I bought headphones for three hundred yuan"


def synthesise(path: str) -> bool:
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.SetOutputToWaveFile('{path}'); $s.Speak('{SENTENCE}'); $s.Dispose()")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True, timeout=60)
        return os.path.getsize(path) > 1000
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--language", default="en", choices=["en", "zh"])
    ap.add_argument("--no-call", action="store_true")
    a = ap.parse_args()
    path = a.file
    if not path:
        path = os.path.join(tempfile.gettempdir(), "wealthguard_whisper_check.wav")
        if not synthesise(path):
            print("Could not synthesise speech here (needs Windows). Pass --file with a recording instead.")
            return 2
    data = open(path, "rb").read()
    print(f"audio: {len(data):,} bytes, container: {transcribe.sniff(data)}")
    st = transcribe.status()
    print(f"whisper: provider={st['provider']} model={st['model']} available={st['available']}")
    if a.no_call:
        return 0
    if not st["available"]:
        print("Whisper is not available: put GROQ_API_KEY in .env (and unset USE_MOCK_LLM), or WHISPER_PROVIDER=local with faster-whisper installed.")
        return 2
    try:
        out = transcribe.transcribe(data, a.language)
    except transcribe.TranscribeError as e:
        print(f"FAILED ({e.status}): {e.message}")
        return 1
    print(f"transcript: {out['text']!r}")
    if a.file:
        return 0 if out["text"] else 1
    ok = "headphones" in out["text"].lower()
    print("RESULT:", "ok" if ok else "unexpected transcript")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
