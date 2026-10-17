// Voice input (speech-to-text) and read-aloud (text-to-speech) using the browser's Web Speech API.
// No audio is sent to our server: the transcript is placed in the chat box and the user presses Send,
// so typed and spoken messages go through the same guard, tier and audit path.
(function () {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const synth = window.speechSynthesis;
  const $ = (id) => document.getElementById(id);
  let rec = null, listening = false, speakOn = false;

  function lang() { return $("voiceLang") ? $("voiceLang").value : "en-US"; }

  function setMicState(on) {
    listening = on;
    const b = $("micBtn");
    b.classList.toggle("rec", on);
    b.setAttribute("aria-pressed", String(on));
    b.textContent = on ? "Stop" : "Mic";
  }

  function note(msg) { $("voiceNote").textContent = msg; }

  function startListening() {
    rec = new SR();
    rec.lang = lang();
    rec.interimResults = true;
    rec.continuous = false;
    const input = $("chatInput");
    const base = input.value ? input.value + " " : "";
    rec.onresult = (ev) => {
      let t = "";
      for (let i = 0; i < ev.results.length; i++) t += ev.results[i][0].transcript;
      input.value = base + t;
    };
    rec.onerror = (ev) => { note("Voice error: " + ev.error); setMicState(false); };
    rec.onend = () => { setMicState(false); if (input.value.trim()) note("Check the text, then press Send."); };
    try { rec.start(); setMicState(true); note("Listening..."); } catch (e) { note("Could not start the microphone."); }
  }

  function toggleMic() {
    if (listening && rec) { rec.stop(); return; }
    startListening();
  }

  function speak(text) {
    if (!speakOn || !synth || !text) return;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(String(text).slice(0, 1500));
    u.lang = lang();
    synth.speak(u);
  }

  function toggleSpeak() {
    speakOn = !speakOn;
    const b = $("speakBtn");
    b.setAttribute("aria-pressed", String(speakOn));
    b.textContent = speakOn ? "Read aloud: on" : "Read aloud: off";
    if (!speakOn && synth) synth.cancel();
  }

  function init() {
    if (!$("micBtn")) return;
    if (SR) $("micBtn").onclick = toggleMic;
    else { $("micBtn").disabled = true; $("micBtn").title = "Voice input needs Chrome or Edge"; }
    if (synth) $("speakBtn").onclick = toggleSpeak;
    else $("speakBtn").disabled = true;
    if (!SR) note("Voice input is not supported in this browser. Typing still works.");
  }

  window.WGVoice = { speak };
  document.addEventListener("DOMContentLoaded", init);
})();
