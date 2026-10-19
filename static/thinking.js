// "Thinking" indicator and reply reveal for both chats.
//
// Honest about what it is: the AI service answers in one piece (the structured-output API does not stream), so the dots and the changing
// status line only show that the request is in progress, and the typing effect reveals the finished answer in a few seconds at most.
// If the service is slow the person sees how long it has been and, past a limit, a clear notice instead of silence.
(function () {
  const L = () => window.WGLang;
  const T = (s) => (L() ? L().t(s) : s);
  const reduced = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const PHASES = ["Thinking…", "Reading your message…", "Working on the answer…"];

  // Shows a pending reply bubble in `box`. Returns { stop(), seconds() }.
  function start(box, opts) {
    opts = opts || {};
    const phases = opts.phases || PHASES;
    const el = document.createElement("div");
    el.className = "msg agent thinking m bot";
    el.setAttribute("role", "status");
    el.innerHTML = '<span class="think-dots" aria-hidden="true"><i></i><i></i><i></i></span><span class="think-label"></span>';
    const label = el.querySelector(".think-label");
    const t0 = Date.now();
    let i = 0;
    const paint = () => {
      const s = Math.floor((Date.now() - t0) / 1000);
      let text;
      if (s >= 25) { text = T("This is taking longer than usual. The AI service may be slow."); el.classList.add("slow"); }
      else if (s >= 8) text = T("Still working…") + " " + s + "s";
      else text = T(phases[i % phases.length]);
      if (label.textContent !== text) label.textContent = text;
    };
    paint();
    const phaseTimer = setInterval(() => { i++; paint(); }, 2200);
    const tick = setInterval(paint, 1000);
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;
    return {
      el,
      seconds: () => Math.floor((Date.now() - t0) / 1000),
      stop() { clearInterval(phaseTimer); clearInterval(tick); if (el.parentNode) el.parentNode.removeChild(el); },
    };
  }

  // Reveals `text` inside `el` progressively (at most ~maxMs in total, so a long answer is never slow to read).
  function type(el, text, opts) {
    opts = opts || {};
    const maxMs = opts.maxMs || 2600, cps = opts.cps || 140;
    return new Promise((resolve) => {
      const full = String(text);
      const draw = (s) => { if (opts.render) el.innerHTML = opts.render(s); else el.textContent = s; };
      if (reduced() || window.WG_NO_ANIM || full.length < 4) { draw(full); resolve(); return; }
      const total = Math.min(maxMs, (full.length / cps) * 1000);
      const t0 = performance.now();
      el.classList.add("typing");
      const box = el.parentNode;
      const step = (now) => {
        const p = Math.min(1, (now - t0) / total);
        const n = Math.max(1, Math.floor(full.length * p));
        draw(full.slice(0, n));
        if (box) box.scrollTop = box.scrollHeight;
        if (p < 1) requestAnimationFrame(step);
        else { draw(full); el.classList.remove("typing"); resolve(); }
      };
      requestAnimationFrame(step);
    });
  }

  // fetch with a hard client-side limit, so a hung connection ends in an error message rather than an endless spinner
  async function withTimeout(promiseFactory, ms) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), ms || 75000);
    try { return await promiseFactory(ctl.signal); }
    catch (e) { if (e && e.name === "AbortError") { const err = new Error("The AI service did not respond in time. Nothing was lost; please try again."); err.timeout = true; throw err; } throw e; }
    finally { clearTimeout(timer); }
  }

  window.WGThinking = { start, type, withTimeout, PHASES };
})();
