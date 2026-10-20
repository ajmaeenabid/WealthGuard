// Hands-free voice mode for the money assistant. Turn-based, NOT full-duplex.
(function (root) {
  function createVad(opt) {
    const o = Object.assign({ minLevel: 0.015, factor: 3, minSpeechMs: 250, silenceMs: 900, maxMs: 20000, abortMs: 500 }, opt || {});
    let floor = 0.005, state = "quiet", since = 0, lastLoud = 0, confirmedAt = 0;
    const loud = (lv) => lv > Math.max(o.minLevel, floor * o.factor);
    return {
      get state() { return state; },
      get floor() { return floor; },
      reset() { state = "quiet"; since = lastLoud = confirmedAt = 0; },
      push(level, now) {
        const ev = [], isLoud = loud(level);
        if (state === "quiet") {
          if (isLoud) { state = "candidate"; since = lastLoud = now; ev.push("candidate"); }
          else floor = floor * 0.95 + level * 0.05;
        } else if (state === "candidate") {
          if (isLoud) lastLoud = now;
          if (now - since >= o.minSpeechMs && now - lastLoud < o.silenceMs && isLoud) { state = "speech"; confirmedAt = now; ev.push("start"); }
          else if (!isLoud && now - lastLoud >= o.abortMs) { state = "quiet"; ev.push("abort"); }
        } else if (state === "speech") {
          if (isLoud) lastLoud = now;
          if (now - lastLoud >= o.silenceMs) { state = "quiet"; ev.push("end"); }
          else if (now - since >= o.maxMs) { state = "quiet"; ev.push("end"); }
        }
        return ev;
      },
    };
  }
  const exported = { createVad };
  if (typeof module !== "undefined" && module.exports) { module.exports = exported; }
  if (typeof document === "undefined") return;
  root.WGVoiceMode = exported;

  const $ = (id) => document.getElementById(id);
  const L = () => root.WGLang;
  const tt = (s) => (L() ? L().t(s) : s);
  const synth = root.speechSynthesis;
  let S = null;

  function langCode() {
    const prefs = (L() && L().prefs) || {};
    return L().speechCode(prefs.speech_lang);
  }
  function whisperLang(code) { return code.startsWith("zh") ? "zh" : code.startsWith("bn") ? "bn" : "en"; }
  function pickVoice(code) {
    if (!synth) return null;
    const vs = synth.getVoices();
    const base = code.split("-")[0];
    return vs.find((v) => v.lang === code) || vs.find((v) => v.lang.replace("_", "-").startsWith(base)) || null;
  }
  const clean = (t) => String(t || "").replace(/[*_`#>]/g, "").replace(/\s+/g, " ").trim();

  function ui() {
    let el = $("vmPanel");
    if (el) return el;
    el = document.createElement("div");
    el.id = "vmPanel"; el.className = "vm-panel"; el.hidden = true;
    el.setAttribute("role", "dialog"); el.setAttribute("aria-modal", "false"); el.setAttribute("aria-label", tt("Voice mode"));
    el.innerHTML = `<div class="vm-orb" id="vmOrb" aria-hidden="true"></div>
      <div class="vm-state" id="vmState" role="status" aria-live="assertive">${tt("Listening…")}</div>
      <p class="vm-heard" id="vmHeard" aria-live="polite"></p>
      <p class="vm-reply" id="vmReply" aria-live="polite"></p>
      <p class="vm-note" id="vmNote" role="note"></p>
      <div class="vm-actions"><button type="button" id="vmStop" class="primary">${tt("Back to text chat")}</button></div>`;
    document.body.appendChild(el);
    $("vmStop").onclick = stop;
    return el;
  }
  function setState(name, label) {
    if (!S) return;
    S.state = name;
    const p = ui(); p.dataset.state = name;
    $("vmState").textContent = label || tt({ listening: "Listening…", processing: "Processing…", speaking: "Speaking…", idle: "Say something" }[name] || "");
  }
  const note = (m) => { const n = $("vmNote"); if (n) n.textContent = m || ""; };

  async function start() {
    if (S) return;
    const prefs = (L() && L().prefs) || {};
    if (prefs.voice_enabled === false) { alert(tt("Voice mode") + ": " + "off (Settings → Language and region)"); return; }
    if (!navigator.mediaDevices || !root.MediaRecorder) { alert("This browser cannot record audio, so voice mode is unavailable. You can keep typing."); return; }
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }); }
    catch (e) { alert("The microphone was not allowed. Allow it in the browser's site settings, or keep typing."); return; }
    const ctx = new (root.AudioContext || root.webkitAudioContext)();
    const src = ctx.createMediaStreamSource(stream), an = ctx.createAnalyser();
    an.fftSize = 1024; src.connect(an);
    S = { stream, ctx, an, vad: createVad(), rec: null, chunks: [], state: "idle", busy: false, buf: new Float32Array(an.fftSize), timer: null, gen: 0 };
    ui().hidden = false;
    document.documentElement.classList.add("vm-on");
    const btn = $("finVoiceMode"); if (btn) btn.setAttribute("aria-pressed", "true");
    const code = langCode();
    note(pickVoice(code) ? "" : `No ${code} voice is installed in this browser: replies stay as text. Recognition still works.`);
    setState("listening");
    S.timer = setInterval(tick, 50);
  }

  function rms(s) {
    s.an.getFloatTimeDomainData(s.buf);
    let sum = 0;
    for (let i = 0; i < s.buf.length; i++) sum += s.buf[i] * s.buf[i];
    return Math.sqrt(sum / s.buf.length);
  }
  function tick() {
    if (!S) return;
    const speaking = S.state === "speaking";
    if (S.state === "processing") return;
    const level = rms(S) * (speaking ? 0.5 : 1);
    for (const ev of S.vad.push(level, performance.now())) {
      if (ev === "candidate" && !S.rec) beginClip();
      else if (ev === "start" && speaking) { S.gen++; try { synth.cancel(); } catch (e) { } setState("listening"); }
      else if (ev === "end") endClip(true);
      else if (ev === "abort") endClip(false);
    }
  }
  function beginClip() {
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"].find((m) => MediaRecorder.isTypeSupported(m)) || "";
    S.chunks = [];
    const rec = new MediaRecorder(S.stream, mime ? { mimeType: mime } : undefined);
    rec.ondataavailable = (e) => { if (e.data && e.data.size) S.chunks.push(e.data); };
    rec.start(); S.rec = rec; S.mime = rec.mimeType || mime;
  }
  function endClip(keep) {
    const rec = S.rec; S.rec = null;
    if (!rec) return;
    rec.onstop = () => { if (keep && S) handle(new Blob(S.chunks, { type: S.mime || "audio/webm" })); };
    try { rec.stop(); } catch (e) { }
  }

  async function handle(blob) {
    if (!S || S.busy) return;
    S.busy = true; setState("processing");
    const gen = S.gen;
    try {
      const code = langCode();
      const q = new URLSearchParams({ language: whisperLang(code) });
      const tr = await fetch("/api/transcribe?" + q, { method: "POST", headers: { "Content-Type": blob.type || "application/octet-stream" }, body: blob });
      const j = await tr.json().catch(() => ({}));
      if (!tr.ok) { note("Speech recognition failed (" + (j.detail || tr.status) + "). You can type instead."); return; }
      if (j.empty || !(j.text || "").trim()) { note("I did not hear anything clearly. Try again."); return; }
      const text = (j.text || "").trim();
      $("vmHeard").textContent = text; note("");
      const reply = await root.WGFinance.sendVoice(text, whisperLang(code));
      if (reply && reply.reply) {
        $("vmReply").textContent = clean(reply.reply);
        await speak(clean(reply.reply), code, gen);
      }
    } catch (e) { note("Something went wrong: " + e.message + ". The conversation is kept; you can continue by typing."); }
    finally { if (S) { S.busy = false; S.vad.reset(); if (S.state !== "speaking") setState("listening"); } }
  }

  function speak(text, code, gen) {
    return new Promise((resolve) => {
      const v = synth && pickVoice(code);
      if (!v || !text) { resolve(); return; }
      const u = new SpeechSynthesisUtterance(text);
      u.voice = v; u.lang = v.lang;
      u.onend = u.onerror = () => { if (S && S.state === "speaking") setState("listening"); resolve(); };
      setState("speaking");
      if (S && gen !== S.gen) { resolve(); return; }
      synth.cancel(); synth.speak(u);
    });
  }

  function stop() {
    if (!S) return;
    clearInterval(S.timer);
    try { if (S.rec) S.rec.stop(); } catch (e) { }
    try { synth && synth.cancel(); } catch (e) { }
    S.stream.getTracks().forEach((t) => t.stop());
    try { S.ctx.close(); } catch (e) { }
    S = null;
    const p = $("vmPanel"); if (p) p.hidden = true;
    document.documentElement.classList.remove("vm-on");
    const btn = $("finVoiceMode"); if (btn) btn.setAttribute("aria-pressed", "false");
    const input = $("finInput"); if (input) input.focus();
  }

  root.WGVoiceMode.start = start;
  root.WGVoiceMode.stop = stop;
  root.WGVoiceMode.toggle = () => (S ? stop() : start());
  root.WGVoiceMode.active = () => !!S;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && S) stop(); });
})(typeof window !== "undefined" ? window : globalThis);
