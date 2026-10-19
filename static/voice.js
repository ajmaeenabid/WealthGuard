// Voice input and read-aloud.
// Two speech-to-text engines fill a text box; the user then presses Send / Interpret, so spoken and typed text take the same guarded
// path (injection guard, compliance, tiers). Push-to-talk only: nothing listens in the background and nothing is sent automatically.
//   Whisper  (server): records with MediaRecorder and uploads the clip to /api/transcribe (Groq-hosted or local Whisper).
//            Works in any modern browser, in English and Chinese. The audio is sent to the transcription service.
//   Browser  : the Web Speech API (Chrome/Edge). The browser vendor may process the audio.
// "Auto" uses Whisper when the server reports it as available, otherwise the browser engine.
(function () {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const synth = window.speechSynthesis;
  const $ = (id) => document.getElementById(id);
  const MAX_MS = 30000;   // a voice command is short; the server also limits the upload size
  let speakOn = false;
  let active = null;      // the one recording or recognition session that may run at a time
  let whisper = { available: false, provider: null, model: null };
  let getClientId = null;

  function lang() { return $("voiceLang") ? $("voiceLang").value : "en-US"; }

  // Some browsers return the same phrase twice ("Hello, how are you? Hello, how are you?"): collapse an exact repeat of a multi-word phrase.
  function tidy(text) {
    const t = String(text || "").replace(/\s+/g, " ").trim();
    const words = t.split(" ");
    const norm = (w) => w.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
    for (let len = 2; len <= words.length / 2; len++) {
      if (words.length % len) continue;
      const first = words.slice(0, len).map(norm).join(" ");
      let same = true;
      for (let i = len; i < words.length && same; i += len) same = words.slice(i, i + len).map(norm).join(" ") === first;
      if (same) return words.slice(0, len).join(" ");
    }
    // spaceless scripts (Chinese): an exact doubled string
    const h = t.length / 2;
    if (!t.includes(" ") && t.length >= 4 && t.length % 2 === 0 && t.slice(0, h) === t.slice(h)) return t.slice(0, h);
    return t;
  }
  const announce = (input) => input.dispatchEvent(new Event("input", { bubbles: true }));
  function engine() {
    const v = $("voiceEngine") ? $("voiceEngine").value : "auto";
    if (v === "whisper") return whisper.available ? "whisper" : (SR ? "browser" : "none");
    if (v === "browser") return SR ? "browser" : (whisper.available ? "whisper" : "none");
    return whisper.available ? "whisper" : (SR ? "browser" : "none");
  }

  // Wire a mic button to a text input. noteId is a status line shown next to the control.
  function attach(btnId, inputId, noteId) {
    const btn = $(btnId), input = $(inputId), note = $(noteId);
    if (!btn || !input) return;
    const say = (m) => { if (note) note.textContent = m; };
    const labelHtml = btn.innerHTML;

    function state(on) {
      btn.classList.toggle("rec", on);
      btn.setAttribute("aria-pressed", String(on));
      btn.innerHTML = on ? (btn.dataset.stopHtml || "Stop") : labelHtml;
      if (!on && active && active.btn === btn) active = null;
    }
    const finish = (text) => {
      input.value = (input.value ? input.value + " " : "") + tidy(text);
      input.dataset.voice = "1";
      announce(input);
      say("Check the text, then confirm.");
    };

    async function sendToWhisper(blob) {
      if (blob.size < 1000) { say("Nothing was recorded."); return; }
      say("Transcribing with Whisper...");
      const q = new URLSearchParams({ language: lang().startsWith("zh") ? "zh" : lang().startsWith("bn") ? "bn" : "en" });
      const cid = getClientId ? getClientId() : null;
      if (cid) q.set("client_id", cid);
      try {
        const r = await fetch("/api/transcribe?" + q.toString(), { method: "POST", headers: { "Content-Type": blob.type || "application/octet-stream" }, body: blob });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) { say("Whisper error: " + (j.detail || r.status) + (SR ? " (try the Browser engine)" : "")); return; }
        if (j.empty) { say("I did not hear anything. Try again closer to the microphone."); return; }
        finish(j.text);
      } catch (e) { say("Could not reach the speech service."); }
    }

    async function startWhisper() {
      if (!navigator.mediaDevices || !window.MediaRecorder) { say("This browser cannot record audio."); return; }
      let stream;
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
      catch (e) { say("Microphone permission was denied."); return; }
      const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"].find((m) => MediaRecorder.isTypeSupported(m)) || "";
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      const chunks = [];
      const timer = setTimeout(() => { if (rec.state !== "inactive") rec.stop(); }, MAX_MS);
      rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
      rec.onstop = async () => {
        clearTimeout(timer);
        stream.getTracks().forEach((t) => t.stop());
        state(false);
        await sendToWhisper(new Blob(chunks, { type: rec.mimeType || mime || "audio/webm" }));
      };
      active = { btn, stop: () => { if (rec.state !== "inactive") rec.stop(); } };
      rec.start();
      state(true);
      say("Recording... click Stop when you are done.");
    }

    function startBrowser() {
      const rec = new SR();
      rec.lang = lang();
      rec.interimResults = true;
      rec.continuous = false;
      const base = input.value ? input.value + " " : "";
      rec.onresult = (ev) => {
        let fin = "", interim = "";
        for (let i = 0; i < ev.results.length; i++) {
          const r = ev.results[i];
          if (r.isFinal) fin += r[0].transcript + " "; else interim = r[0].transcript;
        }
        input.value = base + tidy(fin + interim);
        input.dataset.voice = "1";
        announce(input);
      };
      rec.onerror = (ev) => { say("Voice error: " + ev.error); state(false); };
      rec.onend = () => { state(false); if (input.value.trim()) say("Check the text, then confirm."); };
      try { rec.start(); active = { btn, stop: () => rec.stop() }; state(true); say("Listening..."); } catch (e) { say("Could not start the microphone."); }
    }

    btn.onclick = () => {
      if (active && active.btn === btn) { active.stop(); return; }
      if (active) active.stop();
      const eng = engine();
      if (eng === "whisper") startWhisper();
      else if (eng === "browser") startBrowser();
      else say("Voice input is not available in this browser or setup. Typing still works.");
    };
    if (engine() === "none") { btn.disabled = true; btn.title = "Voice input is not available"; }
  }

  function speak(text) {
    if (!speakOn || !synth || !text) return;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(String(text).slice(0, 1500));
    u.lang = lang();
    synth.speak(u);
  }

  function describe() {
    return;                      // the engine description line was removed on purpose; status messages still use the note
    const n = $("voiceNote");
    if (!n) return;
    const e = engine();
    n.textContent = e === "whisper" ? `Voice: Whisper (${whisper.provider}, ${whisper.model}). The clip is sent to the transcription service.`
      : e === "browser" ? "Voice: browser speech recognition." : "Voice input is not available here. Typing still works.";
  }

  async function init() {
    try {
      const h = await (await fetch("/api/health")).json();
      if (h.transcription) whisper = h.transcription;
    } catch (e) { /* offline: browser engine only */ }
    attach("micBtn", "chatInput", "voiceNote");
    attach("ledgerMic", "ledgerCmd", "ledgerNote");
    attach("finMic", "finInput", "finNote");
    const sel = $("voiceEngine");
    if (sel) {
      const opt = [...sel.options].find((o) => o.value === "whisper");
      if (opt && !whisper.available) opt.disabled = true;
      sel.onchange = describe;
    }
    describe();
    const sb = $("speakBtn");
    if (!sb) return;
    if (!synth) { sb.disabled = true; return; }
    sb.onclick = () => {
      speakOn = !speakOn;
      sb.setAttribute("aria-pressed", String(speakOn));
      sb.title = speakOn ? "Reading replies aloud (click to stop)" : "Read replies aloud";
      if (!speakOn) synth.cancel();
    };
  }

  // the Money settings can switch "read replies aloud" on or off for the whole page
  function setSpeak(on) {
    speakOn = !!on && !!synth;
    const sb = $("speakBtn");
    if (sb) { sb.setAttribute("aria-pressed", String(speakOn)); sb.title = speakOn ? "Reading replies aloud (click to stop)" : "Read replies aloud"; }
    if (!speakOn && synth) synth.cancel();
  }

  window.WGVoice = { speak, setSpeak, attach, tidy, setClientIdGetter: (fn) => { getClientId = fn; } };
  document.addEventListener("DOMContentLoaded", init);
})();
