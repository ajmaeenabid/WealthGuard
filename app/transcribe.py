"""Speech-to-text with Whisper for voice commands.

Two providers, both Whisper:
  groq   Groq's hosted Whisper (whisper-large-v3-turbo by default) over HTTPS: no install, works on Vercel, uses the GROQ_API_KEY.
  local  faster-whisper running on this machine (optional: pip install faster-whisper; the model downloads once). No audio leaves it.

The transcript is only text for the chat box: the user still presses Send, so spoken and typed input take the same guarded path
(injection guard, compliance, tiers). Uploads are size-limited and checked by their file signature, only the allowlisted Groq origin is
contacted, the key never appears in a response or log, and silence (which Whisper tends to "hear" as stock phrases) yields no text.
"""
import os
import re
import tempfile
import threading
import time
from collections import defaultdict, deque

from app import config

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL_DEFAULT = "whisper-large-v3-turbo"
LOCAL_MODEL_DEFAULT = "base"
MAX_BYTES = 2_000_000          # about 2 minutes of speech as webm/opus; Vercel bodies are limited to 4.5 MB
MAX_TEXT_CHARS = 1000
LANGUAGES = {"en", "zh", "bn"}
RATE_LIMIT = 20                # requests per client per minute
TIMEOUT = 30.0
_TRANSPORT = None              # tests inject httpx.MockTransport here
_LOCK = threading.RLock()
_LOCAL_MODEL = {}
_HITS: dict = defaultdict(deque)

PROMPTS = {  # a short vocabulary hint: Whisper spells product and regulator names correctly when it has seen them
    "en": "WealthGuard, NovaYield Note, CSRC, CNY, yuan, RMB, stress test, order ticket, risk bucket, purchase history.",
    "zh": "以下是普通话的句子。WealthGuard，NovaYield，证监会，压力测试，订单，风险档位，购买记录。",
    "bn": "আজ ৮৫০ টাকা বাজার করলাম। খরচ, আয়, বিকাশ, নগদ, ব্যাংক, বেতন, ভাড়া, বিদ্যুৎ বিল, রিকশা ভাড়া, ছাড়, ভ্যাট।",
}
# What Whisper tends to output for silence or noise. A transcript consisting only of these is treated as empty.
HALLUCINATIONS = [
    "thank you for watching", "thanks for watching", "thank you", "thanks", "please subscribe", "subscribe to my channel",
    "like and subscribe", "you", "bye", "bye bye", "subtitles by the amara.org community", "字幕由amara.org社群提供",
    "请不吝点赞订阅转发打赏支持明镜与点点栏目", "谢谢观看", "谢谢大家", "感谢观看", "订阅", "字幕",
]


class TranscribeError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------------------------- configuration
def _local_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def provider() -> str:
    """groq | local | off. Mock mode (USE_MOCK_LLM=1) turns it off so the offline demo stays deterministic."""
    want = (os.environ.get("WHISPER_PROVIDER") or "").strip().lower()
    if want == "off" or os.environ.get("USE_MOCK_LLM", "0") == "1":
        return "off"
    if want == "local":
        return "local" if _local_available() else "off"
    if want in ("", "groq"):
        return "groq" if config.groq_key() else "off"
    return "off"


def model() -> str:
    m = (os.environ.get("WHISPER_MODEL") or "").strip()
    return m or (LOCAL_MODEL_DEFAULT if provider() == "local" else GROQ_MODEL_DEFAULT)


def status() -> dict:
    p = provider()
    return {"available": p != "off", "provider": p, "model": model() if p != "off" else None,
            "max_bytes": MAX_BYTES, "languages": sorted(LANGUAGES)}


# ---------------------------------------------------------------------------------------------- validation
def sniff(data: bytes) -> str | None:
    """Audio container by file signature (not by what the client claims), or None."""
    if data[:4] == b"\x1aE\xdf\xa3":
        return "webm"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"fLaC":
        return "flac"
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    if data[4:8] == b"ftyp":
        return "m4a"
    return None


def _rate_check(client_id: str | None) -> None:
    key = client_id or "anon"
    now = time.time()
    with _LOCK:
        q = _HITS[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            raise TranscribeError(429, "Too many voice requests; wait a minute.")
        q.append(now)


def reset_limits() -> None:
    with _LOCK:
        _HITS.clear()


# ---------------------------------------------------------------------------------------------- cleaning
def clean(text: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    norm = re.sub(r"[\s\.,!?。，！？、\-]+$", "", t.lower())
    norm = re.sub(r"^[\s\.,!?。，！？、\-]+", "", norm)
    if norm in HALLUCINATIONS or not re.search(r"[A-Za-z0-9一-鿿]", t):
        return ""
    return t[:MAX_TEXT_CHARS]


def _from_segments(body: dict) -> str:
    """Join segments, dropping the ones Whisper itself marks as probably silence."""
    segs = body.get("segments")
    if not isinstance(segs, list) or not segs:
        return str(body.get("text") or "")
    keep = [s.get("text", "") for s in segs if not (float(s.get("no_speech_prob", 0) or 0) > 0.6 and float(s.get("avg_logprob", 0) or 0) < -1.0)]
    return " ".join(keep)


# ---------------------------------------------------------------------------------------------- providers
def _groq(data: bytes, ext: str, language: str | None) -> str:
    import httpx
    from app.security import tiers  # lazy: tiers imports modules that import config
    if not tiers.is_url_allowed(GROQ_URL):
        raise TranscribeError(503, "Transcription is blocked: the speech service is not on the URL allowlist.")
    fields = {"model": model(), "response_format": "verbose_json", "temperature": "0",
              "prompt": PROMPTS.get(language or "en", PROMPTS["en"])}
    if language:
        fields["language"] = language
    for attempt in range(2):
        try:
            with httpx.Client(timeout=TIMEOUT, transport=_TRANSPORT) as c:
                r = c.post(GROQ_URL, data=fields, files={"file": (f"voice.{ext}", data, f"audio/{ext}")},
                           headers={"Authorization": f"Bearer {config.groq_key()}"})
        except httpx.HTTPError as e:
            raise TranscribeError(502, f"Speech service unreachable ({type(e).__name__}).") from None
        if r.status_code == 429 and attempt == 0:
            time.sleep(min(float(r.headers.get("retry-after", 1) or 1), 3))
            continue
        break
    if r.status_code in (401, 403):
        raise TranscribeError(503, "The speech service rejected the API key.")
    if r.status_code == 429:
        raise TranscribeError(429, "The speech service is rate limited; try again shortly.")
    if r.status_code >= 400:
        raise TranscribeError(502, f"The speech service returned HTTP {r.status_code}.")
    try:
        return _from_segments(r.json())
    except ValueError:
        raise TranscribeError(502, "The speech service returned an unreadable answer.") from None


def _local(data: bytes, ext: str, language: str | None) -> str:
    try:
        from faster_whisper import WhisperModel
    except Exception:
        raise TranscribeError(503, "Local Whisper is not installed (pip install faster-whisper).") from None
    name = model()
    with _LOCK:
        if name not in _LOCAL_MODEL:
            _LOCAL_MODEL[name] = WhisperModel(name, device="cpu", compute_type="int8")
        m = _LOCAL_MODEL[name]
    fd, path = tempfile.mkstemp(suffix="." + ext)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        segments, _info = m.transcribe(path, language=language, initial_prompt=PROMPTS.get(language or "en"), beam_size=1,
                                       temperature=0.0, condition_on_previous_text=False)
        out = []
        for s in segments:
            if float(getattr(s, "no_speech_prob", 0) or 0) > 0.6 and float(getattr(s, "avg_logprob", 0) or 0) < -1.0:
                continue
            out.append(s.text)
        return " ".join(out)
    except TranscribeError:
        raise
    except Exception as e:
        raise TranscribeError(502, f"Local Whisper failed ({type(e).__name__}).") from None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------------------------- public API
def transcribe(data: bytes, language: str | None = None, client_id: str | None = None) -> dict:
    p = provider()
    if p == "off":
        raise TranscribeError(503, "Whisper transcription is not available (needs GROQ_API_KEY and a live model, or WHISPER_PROVIDER=local).")
    if language is not None and language not in LANGUAGES:
        raise TranscribeError(422, f"language must be one of {sorted(LANGUAGES)}")
    if not data:
        raise TranscribeError(422, "No audio received.")
    if len(data) > MAX_BYTES:
        raise TranscribeError(413, f"Audio is too long (limit {MAX_BYTES // 1000} KB).")
    ext = sniff(data)
    if not ext:
        raise TranscribeError(415, "Unsupported audio format (use webm, ogg, wav, mp3, m4a or flac).")
    _rate_check(client_id)
    raw = _groq(data, ext, language) if p == "groq" else _local(data, ext, language)
    text = clean(raw)
    return {"text": text, "empty": not text, "provider": p, "model": model(), "language": language, "container": ext}
