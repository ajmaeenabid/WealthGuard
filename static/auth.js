// Sign in / sign up page, bearer token on every /api call, user box and the Settings dialog (change password).
// Loaded before every other script: it wraps fetch so the rest of the UI never has to think about tokens.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const T = (x) => (window.WGI18n ? window.WGI18n.t(x) : x);
  let token = "";
  // The sign-in lives in sessionStorage: closing the tab or browser ends it, so opening the site again always asks for a login.
  try { localStorage.removeItem("wg-token"); token = sessionStorage.getItem("wg-token") || ""; } catch (e) { /* private mode: sign-in lasts until reload */ }
  let user = null, mode = "login", started = false;
  const waiting = [];

  const rawFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = typeof input === "string" ? input : input.url;
    const path = new URL(url, location.href).pathname;
    const own = new URL(url, location.href).origin === location.origin && path.startsWith("/api/");
    if (own && token) {
      const h = new Headers((init && init.headers) || undefined);
      h.set("Authorization", "Bearer " + token);
      init = Object.assign({}, init, { headers: h });
    }
    return rawFetch(input, init).then((r) => {
      if (r.status === 401 && own && user && !/\/api\/auth\/(login|signup)$/.test(path)) forget(true);   // token expired or revoked
      return r;
    });
  };

  function save(t) { token = t; try { t ? sessionStorage.setItem("wg-token", t) : sessionStorage.removeItem("wg-token"); } catch (e) { /* ignore */ } }
  function forget(reload) { save(""); user = null; if (reload) location.reload(); }

  async function call(path, body, method) {
    const r = await window.fetch(path, body === undefined && !method ? {} : { method: method || "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    let data = null;
    try { data = await r.json(); } catch (e) { /* not JSON */ }
    if (!r.ok) throw Object.assign(new Error((data && typeof data.detail === "string" && data.detail) || r.statusText || "Request failed"), { status: r.status });
    return data;
  }

  function show(el, on) { el.hidden = !on; document.body.classList.toggle("locked", !$("auth").hidden); }

  function setMode(m) {
    mode = m;
    $("tabLogin").setAttribute("aria-selected", String(m === "login"));
    $("tabSignup").setAttribute("aria-selected", String(m === "signup"));
    $("authConfirmRow").hidden = m !== "signup";
    $("authPass").autocomplete = m === "signup" ? "new-password" : "current-password";
    const go = $("authGo");
    go.setAttribute("data-i18n", m === "signup" ? "signUp" : "signIn");
    go.textContent = T(m === "signup" ? "Create account" : "Sign in");
    $("authErr").hidden = true;
  }

  function err(el, msg) { el.textContent = msg; el.hidden = !msg; }

  function applyUser() {
    $("userBox").hidden = false;
    $("userName").textContent = user.display_name || user.username;
    $("userRole").textContent = user.role === "admin" ? T("Administrator") : "@" + user.username;
    $("avatar").textContent = (user.display_name || user.username).replace(/^(Ms|Mr)\.\s*/i, "").charAt(0).toUpperCase();
    $("setWho").textContent = (user.display_name || user.username) + " (@" + user.username + ")";
  }

  function begin(u) {
    user = u;
    show($("auth"), false);
    applyUser();
    if (!started) { started = true; waiting.splice(0).forEach((fn) => fn(user)); }
  }

  async function boot() {
    setMode("login");
    if (token) {
      try { begin(await call("/api/auth/me")); return; } catch (e) { save(""); }
    }
    show($("auth"), true);
    $("authUser").focus();
  }

  $("tabLogin").onclick = () => setMode("login");
  $("tabSignup").onclick = () => setMode("signup");
  $("authForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const username = $("authUser").value.trim(), password = $("authPass").value;
    if (mode === "signup" && password !== $("authPass2").value) { err($("authErr"), T("The two passwords do not match.")); return; }
    $("authGo").disabled = true;
    try {
      const out = await call(mode === "signup" ? "/api/auth/signup" : "/api/auth/login", { username, password });
      save(out.token);
      try { localStorage.removeItem("wg-mode"); } catch (e) { /* ignore */ }      // a fresh sign-in starts on the default screen
      $("authPass").value = ""; $("authPass2").value = ""; err($("authErr"), "");
      begin(out.user);
    } catch (e) { err($("authErr"), e.message); }
    $("authGo").disabled = false;
  });

  // ---------------------------------------------------------------- settings: change password
  const openSettings = () => { show($("settings"), true); $("setWho").hidden = false; $("pwOld").focus(); };
  const closeSettings = () => { show($("settings"), false); $("pwForm").reset(); err($("pwMsg"), ""); };
  $("settingsBtn").onclick = openSettings;
  $("setClose").onclick = closeSettings;
  $("settings").addEventListener("click", (ev) => { if (ev.target === $("settings")) closeSettings(); });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !$("settings").hidden) closeSettings(); });
  $("pwForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const msg = $("pwMsg");
    msg.classList.remove("ok");
    if ($("pwNew").value !== $("pwNew2").value) { err(msg, T("The two passwords do not match.")); return; }
    try {
      await call("/api/auth/password", { old_password: $("pwOld").value, new_password: $("pwNew").value });
      $("pwForm").reset();
      msg.classList.add("ok");
      err(msg, T("Password changed. Other devices were signed out."));
    } catch (e) { err(msg, e.message); }
  });

  $("logoutBtn").onclick = async () => {
    try { await call("/api/auth/logout", {}); } catch (e) { /* the token is dropped locally either way */ }
    forget(true);
  };

  window.WGAuth = {
    get user() { return user; },
    onReady(fn) { if (started) fn(user); else waiting.push(fn); },
  };
  boot();
})();
