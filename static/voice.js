// Voice input (speech-to-text) and read-aloud (text-to-speech) using the browser's Web Speech API.
// No audio is sent to our server: the transcript is placed in a text box and the user presses Send / Interpret, so
// typed and spoken text take the same guarded path. Push-to-talk only: nothing listens in the background.
(function () {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const synth = window.speechSynthesis;
  const $ = (id) => document.getElementById(id);
  let speakOn = false;
  let active = null; // the one recognition session that may run at a time

  function lang() { return $("voiceLang") ? $("voiceLang").value : "en-US"; }

  // Wire a mic button to a text input. noteId is a status line shown next to the control.
  function attach(btnId, inputId, noteId) {
    const btn = $(btnId), input = $(inputId), note = $(noteId);
    if (!btn || !input) return;
    const say = (m) => { if (note) note.textContent = m; };
    if (!SR) { btn.disabled = true; btn.title = "Voice input needs Chrome or Edge"; say("Voice input is not supported in this browser. Typing still works."); return; }
    const label = btn.textContent;
    let rec = null;

    function state(on) {
      btn.classList.toggle("rec", on);
      btn.setAttribute("aria-pressed", String(on));
      btn.textContent = on ? "Stop" : label;
      if (!on && active === rec) active = null;
    }

    btn.onclick = () => {
      if (active && active.btn === btn) { active.rec.stop(); return; }
      if (active) active.rec.stop();
      rec = new SR();
      rec.lang = lang();
      rec.interimResults = true;
      rec.continuous = false;
      const base = input.value ? input.value + " " : "";
      rec.onresult = (ev) => {
        let t = "";
        for (let i = 0; i < ev.results.length; i++) t += ev.results[i][0].transcript;
        input.value = base + t;
        input.dataset.voice = "1";
      };
      rec.onerror = (ev) => { say("Voice error: " + ev.error); state(false); };
      rec.onend = () => { state(false); if (input.value.trim()) say("Check the text, then confirm."); };
      try { rec.start(); active = { rec, btn }; state(true); say("Listening..."); } catch (e) { say("Could not start the microphone."); }
    };
  }

  function speak(text) {
    if (!speakOn || !synth || !text) return;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(String(text).slice(0, 1500));
    u.lang = lang();
    synth.speak(u);
  }

  function init() {
    attach("micBtn", "chatInput", "voiceNote");
    attach("ledgerMic", "ledgerCmd", "ledgerNote");
    const sb = $("speakBtn");
    if (!sb) return;
    if (!synth) { sb.disabled = true; return; }
    sb.onclick = () => {
      speakOn = !speakOn;
      sb.setAttribute("aria-pressed", String(speakOn));
      sb.textContent = speakOn ? "Read aloud: on" : "Read aloud: off";
      if (!speakOn) synth.cancel();
    };
  }

  window.WGVoice = { speak, attach };
  document.addEventListener("DOMContentLoaded", init);
})();
