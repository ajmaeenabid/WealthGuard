// App shell behaviour: sidebar navigation, the sliding feature drawer, composer, theme, toasts and the advice-flow thread.
// It never touches business logic: app.js renders the cards and talks to the API; this file decides what is visible and how it moves.
(function () {
  const $ = (id) => document.getElementById(id);
  const q = (sel, root) => (root || document).querySelector(sel);
  const qa = (sel, root) => [...(root || document).querySelectorAll(sel)];
  const T = (s) => (window.WGI18n ? window.WGI18n.t(s) : s);
  const WIDE = () => window.matchMedia("(min-width: 1320px)").matches;
  const MOBILE = () => window.matchMedia("(max-width: 900px)").matches;

  const shell = $("shell"), drawer = $("drawer"), sidebar = $("sidebar"), scrim = $("scrim");
  let openId = null;

  // ------------------------------------------------------------------ drawer
  function syncScrim() {
    const need = (openId && !WIDE()) || sidebar.classList.contains("open");
    scrim.hidden = !need;
  }

  function openPanel(id) {
    const card = $(id);
    if (!card) return;
    qa(".panels .card").forEach((c) => c.classList.toggle("active", c === card));
    qa(".nav").forEach((b) => {
      const on = b.dataset.panel === id;
      b.setAttribute("aria-pressed", String(on));
      if (on) b.classList.remove("has-update");
    });
    openId = id;
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    shell.classList.add("drawer-open");
    q(".drawer-body", drawer).scrollTop = 0;
    if (MOBILE()) sidebar.classList.remove("open");
    syncScrim();
    // charts drawn while the card was hidden need to be told their size
    setTimeout(() => window.dispatchEvent(new Event("resize")), 480);
  }

  function closePanel() {
    openId = null;
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    shell.classList.remove("drawer-open");
    qa(".nav").forEach((b) => b.setAttribute("aria-pressed", "false"));
    syncScrim();
  }

  qa(".nav").forEach((b) => (b.onclick = () => (openId === b.dataset.panel ? closePanel() : openPanel(b.dataset.panel))));
  $("drawerClose").onclick = closePanel;
  scrim.onclick = () => { closePanel(); sidebar.classList.remove("open"); syncScrim(); };
  $("menuBtn").onclick = () => { sidebar.classList.toggle("open"); syncScrim(); };
  window.addEventListener("resize", syncScrim);
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    const pop = $("vsetPop");
    if (pop && !pop.hidden) { pop.hidden = true; $("vsetBtn").setAttribute("aria-expanded", "false"); return; }
    if (openId) closePanel(); else if (sidebar.classList.contains("open")) { sidebar.classList.remove("open"); syncScrim(); }
  });

  // ------------------------------------------------------------------ theme
  const themeBtn = $("themeBtn");
  const SUN = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/></svg>';
  const MOON = themeBtn.innerHTML;
  function currentTheme() {
    const t = document.documentElement.dataset.theme;
    if (t) return t;
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  function paintTheme() { themeBtn.innerHTML = currentTheme() === "light" ? MOON : SUN; }
  themeBtn.onclick = () => {
    const next = currentTheme() === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("wg-theme", next); } catch (e) { /* private mode */ }
    paintTheme();
  };
  paintTheme();

  // ------------------------------------------------------------------ composer
  const input = $("chatInput"), form = $("chatForm"), chat = q(".chat");
  function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 190) + "px";
  }
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing && !input.disabled) {
      ev.preventDefault();
      if (input.value.trim() && !$("sendBtn").disabled) form.requestSubmit();
    }
  });
  new MutationObserver(autosize).observe(input, { attributes: true, attributeFilter: ["value"] });
  form.addEventListener("submit", () => setTimeout(autosize, 0));
  // programmatic fills (voice, quick answers) do not fire "input": resize on focus and after sends
  input.addEventListener("focus", autosize);
  setInterval(() => { if (input.value !== input.dataset.last) { input.dataset.last = input.value; autosize(); } }, 250);

  const messages = $("messages");
  function markStarted() { chat.classList.toggle("started", messages.children.length > 0); }
  new MutationObserver(markStarted).observe(messages, { childList: true });
  markStarted();

  // typing indicator follows the send button's busy state
  const typing = $("typing");
  new MutationObserver(() => { typing.hidden = !($("sendBtn").disabled && input.disabled && chat.classList.contains("started") && !!input.dataset.sent); })
    .observe(input, { attributes: true, attributeFilter: ["disabled"] });
  form.addEventListener("submit", () => { input.dataset.sent = "1"; });
  new MutationObserver(() => { if (!input.disabled) { typing.hidden = true; messages.scrollTop = messages.scrollHeight; } })
    .observe(input, { attributes: true, attributeFilter: ["disabled"] });

  // voice settings popover
  const vbtn = $("vsetBtn"), vpop = $("vsetPop");
  vbtn.onclick = (ev) => { ev.stopPropagation(); vpop.hidden = !vpop.hidden; vbtn.setAttribute("aria-expanded", String(!vpop.hidden)); };
  document.addEventListener("click", (ev) => { if (!vpop.hidden && !vpop.contains(ev.target) && ev.target !== vbtn) { vpop.hidden = true; vbtn.setAttribute("aria-expanded", "false"); } });

  // ------------------------------------------------------------------ hero: pick a client
  async function buildHero() {
    try {
      const people = await (await fetch("/api/personas")).json();
      const box = $("heroCards");
      box.innerHTML = "";
      people.forEach((p) => {
        const b = document.createElement("button");
        b.type = "button"; b.className = "persona-card"; b.setAttribute("role", "listitem");
        b.innerHTML = `<span class="pc-name"></span><span class="pc-story"></span><span class="pc-go"></span>`;
        q(".pc-name", b).textContent = p.name;
        q(".pc-story", b).textContent = p.story;
        q(".pc-go", b).textContent = T("Start with") + " " + p.name.split(" ").pop();
        b.onclick = () => { $("persona").value = p.id; $("start").click(); };
        box.appendChild(b);
      });
    } catch (e) { /* the sidebar selector still works */ }
  }
  buildHero();

  // ------------------------------------------------------------------ model badge
  const badge = $("llmBadge");
  function paintBadge() {
    const t = (badge.textContent || "").toLowerCase();
    badge.classList.toggle("live", t.includes("live"));
    badge.classList.toggle("mock", t.includes("mock"));
  }
  new MutationObserver(paintBadge).observe(badge, { childList: true, characterData: true, subtree: true });
  paintBadge();

  // ------------------------------------------------------------------ advice-flow thread and update dots
  const FLOW = { profile: "profileCard", alloc: "allocCard", comp: "compCard", stress: "stressCard", approve: "approvalCard" };
  const done = { profile: false, alloc: false, comp: false, stress: false, approve: false };
  function progress(partial) {
    Object.assign(done, partial);
    Object.entries(FLOW).forEach(([k, cid]) => {
      const b = q(`.nav[data-panel="${cid}"]`);
      if (b) b.classList.toggle("done", !!done[k]);
    });
  }

  const HAS = {
    profileCard: () => q("#profile:not([data-i18n])"), allocCard: () => q("#allocation:not([data-i18n])"), compCard: () => q("#checks li"),
    stressCard: () => q("#stressOut:not([data-i18n])"), approvalCard: () => q("#tickets .ticket"), ledgerCard: () => q("#ledgerTable tbody tr td:not([colspan])"),
    rpCard: () => q("#rpResult > *"), kbCard: () => q("#kbResults > *"), rcCard: () => q("#rcOut > *"), rtCard: () => q("#rtOut table"),
    siCard: () => q("#siOut > *"), docCard: () => q("#docWarn > *"),
  };
  Object.entries(HAS).forEach(([cid, has]) => {
    const card = $(cid), nav = q(`.nav[data-panel="${cid}"]`);
    if (!card || !nav) return;
    new MutationObserver(() => { if (openId !== cid && has()) nav.classList.add("has-update"); })
      .observe(card, { childList: true, subtree: true, characterData: true });
  });

  // ------------------------------------------------------------------ toasts
  function toast(text, actionLabel, onAction) {
    const el = document.createElement("div");
    el.className = "toast";
    const span = document.createElement("span");
    span.textContent = text;
    el.appendChild(span);
    if (actionLabel) {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = actionLabel;
      b.onclick = () => { onAction(); dismiss(); };
      el.appendChild(b);
    }
    $("toasts").appendChild(el);
    const dismiss = () => { el.classList.add("out"); setTimeout(() => el.remove(), 380); };
    setTimeout(dismiss, 6500);
  }

  let lastAlloc = "";
  new MutationObserver(() => {
    const t = ($("allocTag").textContent || "").trim();
    if (t && t !== lastAlloc && openId !== "allocCard") toast(T("Advice approved by compliance"), T("Open allocation"), () => openPanel("allocCard"));
    lastAlloc = t;
  }).observe($("allocTag"), { childList: true, characterData: true, subtree: true });

  // ------------------------------------------------------------------ chart look and banner height
  const cv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  function styleCharts() {
    if (!window.Chart) return;
    Chart.defaults.color = cv("--muted");
    Chart.defaults.borderColor = cv("--line");
    Chart.defaults.font.family = cv("--font-ui");
    Chart.defaults.plugins.tooltip.backgroundColor = cv("--surface-3");
    Chart.defaults.plugins.tooltip.titleColor = cv("--ink");
    Chart.defaults.plugins.tooltip.bodyColor = cv("--ink-2");
    Chart.defaults.plugins.tooltip.borderColor = cv("--line-strong");
    Chart.defaults.plugins.tooltip.borderWidth = 1;
  }
  function syncBanner() { document.documentElement.style.setProperty("--banner-h", ($("shell").previousElementSibling.offsetHeight || 30) + "px"); }
  styleCharts();
  syncBanner();
  window.addEventListener("resize", syncBanner);
  themeBtn.addEventListener("click", () => setTimeout(() => { styleCharts(); if (window.WGApp) window.WGApp.redraw(); }, 30));

  window.WGUI = { openPanel, closePanel, progress, toast };
})();
