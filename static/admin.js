// Administration portal.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const PAGE = 12;
  const st = { users: [], features: {}, summary: null, me: null, q: "", role: "", status: "", sort: "name", page: 1, open: false, loading: false };

  async function api(path, body, method) {
    const opt = body === undefined && !method ? {} : { method: method || "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const r = await fetch("/api/admin" + path, opt);
    let data = null;
    try { data = await r.json(); } catch (e) { }
    if (!r.ok) {
      const d = data && data.detail;
      throw Object.assign(new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => x.msg).join("; ") : r.statusText || "Request failed"), { status: r.status });
    }
    return data;
  }
  const say = (msg, bad) => { const m = $("adminMsg"); m.textContent = msg || ""; m.classList.toggle("bad", !!bad); };
  function ago(iso) {
    if (!iso) return "never";
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + " min ago";
    if (s < 86400) return Math.floor(s / 3600) + " h ago";
    if (s < 86400 * 30) return Math.floor(s / 86400) + " d ago";
    return iso.slice(0, 10);
  }
  const initial = (u) => (u.display_name || u.username).replace(/^(Ms|Mr)\.\s*/i, "").charAt(0).toUpperCase();

  async function load() {
    st.loading = true;
    if (st.open) renderPortal();
    try {
      const out = await api("/users", undefined, "GET");
      st.users = out.users; st.features = out.features; st.summary = out.summary;
      say("");
    } catch (e) { say("Could not load accounts: " + e.message, true); }
    st.loading = false;
    renderStats();
    if (st.open) renderPortal();
    $("adminCount").textContent = st.summary ? `${st.summary.total} accounts` : "";
  }

  async function loadAi() {
    try {
      const u = await api("/ai-usage", undefined, "GET");
      const box = $("adminAi");
      const purposes = Object.entries(u.by_purpose).map(([k, v]) => `${esc(k)}: ${v.calls} calls`).join(" · ") || "no calls yet";
      box.hidden = false;
      box.innerHTML = `<h3>AI usage (30 days) <span class="tag">${esc(u.model)}</span></h3><div class="kv">
        <div><b>Calls</b>${u.calls}</div><div><b>Tokens</b>${(u.prompt_tokens + u.completion_tokens).toLocaleString("en-US")}</div>
        <div><b>Estimated cost</b>$${Number(u.est_cost_usd).toFixed(4)}</div><div><b>Failed calls</b>${u.failed_calls}</div>
        <div><b>Average latency</b>${u.avg_latency_ms} ms</div><div><b>By purpose</b>${purposes}</div></div>
        <p class="small muted">${esc(u.note)} Counts only, never message text.</p>`;
    } catch (e) { }
  }

  function renderStats() {
    const s = st.summary;
    const box = $("adminStats");
    if (!s) { box.innerHTML = ""; return; }
    const card = (l, v, d) => `<div class="fcard kpi"><div class="l">${l}</div><div class="v">${v}</div>${d ? `<div class="d">${d}</div>` : ""}</div>`;
    box.innerHTML = card("Accounts", s.total, `${s.members} members · ${s.admins} administrators`) + card("Active", s.active, s.suspended ? `${s.suspended} suspended` : "none suspended") +
      card("Signed in (24 h)", s.signed_in_24h, `${s.active_sessions} live sessions`) + card("New (7 days)", s.new_7_days, `${s.never_signed_in} never signed in`) + card("Saved chats", s.chats, "counts only");
  }

  function visible() {
    const q = st.q.trim().toLowerCase();
    let list = st.users.filter((u) => (!q || u.username.includes(q) || (u.display_name || "").toLowerCase().includes(q)) &&
      (!st.role || (st.role === "admin" ? u.role === "admin" : u.role !== "admin")) && (!st.status || (st.status === "suspended" ? u.banned : !u.banned)));
    const by = { name: (a, b) => a.username.localeCompare(b.username), newest: (a, b) => b.created.localeCompare(a.created),
      login: (a, b) => (b.last_login || "").localeCompare(a.last_login || ""), chats: (a, b) => b.chats - a.chats };
    return list.sort(by[st.sort] || by.name);
  }

  function renderPortal() {
    const box = $("adminUsers");
    box.hidden = !st.open;
    if (!st.open) return;
    const list = visible();
    const pages = Math.max(1, Math.ceil(list.length / PAGE));
    st.page = Math.min(st.page, pages);
    const rows = list.slice((st.page - 1) * PAGE, st.page * PAGE);
    box.innerHTML = `
      <div class="fin-toolbar">
        <input id="apQ" class="grow" type="search" placeholder="Search by username or name…" value="${esc(st.q)}" aria-label="Search accounts">
        <select id="apRole" aria-label="Role"><option value="">All roles</option><option value="member" ${st.role === "member" ? "selected" : ""}>Members</option><option value="admin" ${st.role === "admin" ? "selected" : ""}>Administrators</option></select>
        <select id="apStatus" aria-label="Status"><option value="">Any status</option><option value="active" ${st.status === "active" ? "selected" : ""}>Active</option><option value="suspended" ${st.status === "suspended" ? "selected" : ""}>Suspended</option></select>
        <select id="apSort" aria-label="Sort">${[["name", "Name"], ["newest", "Newest"], ["login", "Last sign-in"], ["chats", "Most chats"]].map(([v, l]) => `<option value="${v}" ${st.sort === v ? "selected" : ""}>${l}</option>`).join("")}</select>
        <button type="button" id="apRefresh">Refresh</button><button type="button" id="apAdd" class="primary">Add account</button>
      </div>
      ${st.loading ? `<p class="muted" role="status">Loading from the database…</p>` : ""}
      <div class="table-wrap"><table class="ftable"><caption class="sr-only">Accounts</caption>
        <thead><tr><th>Account</th><th>Role</th><th>Status</th><th>Last sign-in</th><th class="num">Sign-ins</th><th class="num">Chats</th><th class="num">Sessions</th><th></th></tr></thead>
        <tbody>${rows.map((u) => `<tr data-u="${esc(u.username)}" tabindex="0">
          <td data-label="Account"><span class="who-cell"><span class="avatar sm" aria-hidden="true">${esc(initial(u))}</span><span><b>${esc(u.display_name)}</b><br><span class="muted small">@${esc(u.username)}${u.username === st.me.username ? " (you)" : ""}</span></span></span></td>
          <td data-label="Role"><span class="chip ${u.role === "admin" ? "warning" : ""}">${u.role === "admin" ? "Administrator" : "Member"}</span></td>
          <td data-label="Status"><span class="chip ${u.banned ? "over" : "ok"}">${u.banned ? "Suspended" : "Active"}</span></td>
          <td data-label="Last sign-in">${esc(ago(u.last_login))}</td><td class="num" data-label="Sign-ins">${u.login_count}</td><td class="num" data-label="Chats">${u.chats}</td><td class="num" data-label="Sessions">${u.active_sessions}</td>
          <td><button type="button" data-manage="${esc(u.username)}">Manage</button></td></tr>`).join("") || `<tr><td colspan="8" class="muted">No account matches these filters.</td></tr>`}</tbody></table></div>
      <div class="pager"><span>${list.length} of ${st.users.length} accounts · page ${st.page} of ${pages}</span><span><button type="button" id="apPrev" ${st.page <= 1 ? "disabled" : ""}>Previous</button> <button type="button" id="apNext" ${st.page >= pages ? "disabled" : ""}>Next</button></span></div>`;
    let timer;
    $("apQ").oninput = () => { clearTimeout(timer); timer = setTimeout(() => { st.q = $("apQ").value; st.page = 1; renderPortal(); const i = $("apQ"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }, 250); };
    $("apRole").onchange = () => { st.role = $("apRole").value; st.page = 1; renderPortal(); };
    $("apStatus").onchange = () => { st.status = $("apStatus").value; st.page = 1; renderPortal(); };
    $("apSort").onchange = () => { st.sort = $("apSort").value; renderPortal(); };
    $("apRefresh").onclick = load;
    $("apAdd").onclick = addForm;
    $("apPrev").onclick = () => { st.page--; renderPortal(); };
    $("apNext").onclick = () => { st.page++; renderPortal(); };
    box.querySelectorAll("[data-manage]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); manage(b.dataset.manage); }));
    box.querySelectorAll("tr[data-u]").forEach((r) => { r.onclick = () => manage(r.dataset.u); r.onkeydown = (e) => { if (e.key === "Enter") manage(r.dataset.u); }; });
  }

  function dialog(title, html) {
    $("adminModalTitle").textContent = title;
    $("adminModalBody").innerHTML = html;
    $("adminModal").hidden = false;
    const first = $("adminModalBody").querySelector("input, select, button");
    if (first) first.focus();
  }
  const closeDialog = () => { $("adminModal").hidden = true; $("adminModalBody").innerHTML = ""; };
  const err = (id, m) => { const e = $(id); if (e) { e.textContent = m; e.hidden = !m; } };

  async function act(path, body, done, errId) {
    try { await api(path, body); say(done); await load(); return true; }
    catch (e) { if (errId) err(errId, e.message); else say(e.message, true); return false; }
  }

  function manage(username) {
    const u = st.users.find((x) => x.username === username);
    if (!u) return;
    const self = u.username === st.me.username;
    const perms = u.role === "admin" ? `<p class="muted small">Administrators have every feature.</p>` :
      `<div class="u-perms">${Object.entries(st.features).map(([f, label]) => `<label class="perm"><input type="checkbox" data-perm="${esc(f)}" ${u.permissions[f] !== false ? "checked" : ""}><span>${esc(label)}</span></label>`).join("")}</div>`;
    dialog(`${u.display_name} (@${u.username})`, `
      <div class="kv" style="margin-bottom:12px"><div><b>Created</b>${esc(u.created.slice(0, 10))}</div><div><b>Last sign-in</b>${esc(ago(u.last_login))}</div><div><b>Sign-ins</b>${u.login_count}</div><div><b>Live sessions</b>${u.active_sessions}</div><div><b>Saved chats</b>${u.chats}</div><div><b>Finance records</b>${u.finance_transactions}</div></div>
      <div class="fin-form">
        <h3 class="mini">Role and access</h3>
        <div class="row2"><label>Role<select id="amRole" ${self ? "disabled" : ""}><option value="client" ${u.role !== "admin" ? "selected" : ""}>Member</option><option value="admin" ${u.role === "admin" ? "selected" : ""}>Administrator</option></select></label>
          <label>Status<button type="button" id="amBan" class="${u.banned ? "primary" : "warn"}" ${self ? "disabled" : ""}>${u.banned ? "Restore access" : "Suspend account"}</button></label></div>
        <h3 class="mini">Features this account may use</h3>${perms}
        <h3 class="mini">Security</h3>
        <div class="row2"><button type="button" id="amOut" ${u.active_sessions ? "" : "disabled"}>Sign out everywhere (${u.active_sessions})</button><span></span></div>
        <div class="row2"><label>New password<input id="amPw" type="text" autocomplete="off" placeholder="at least 6 characters"></label><label>&nbsp;<button type="button" id="amPwGo">Reset password</button></label></div>
        <h3 class="mini">Danger zone</h3>
        <div class="row2"><label>Type <b>${esc(u.username)}</b> to delete<input id="amDelTxt" autocomplete="off" ${self ? "disabled" : ""}></label><label>&nbsp;<button type="button" id="amDel" class="warn" ${self ? "disabled" : ""}>Delete account</button></label></div>
        <p class="muted small">Deleting removes the account with its chats, memory and finance data. This cannot be undone. The audit log keeps a record of who deleted it.</p>
        <div class="fin-err" id="amErr" role="alert" hidden></div>
      </div>`);
    $("amRole").onchange = async () => { if (await act(`/users/${u.username}/role`, { role: $("amRole").value }, `Role updated for @${u.username}.`, "amErr")) manage(u.username); else $("amRole").value = u.role === "admin" ? "admin" : "client"; };
    $("amBan").onclick = async () => { if (await act(`/users/${u.username}/ban`, { banned: !u.banned }, u.banned ? `@${u.username} restored.` : `@${u.username} suspended and signed out.`, "amErr")) manage(u.username); };
    document.querySelectorAll("#adminModalBody [data-perm]").forEach((cb) => (cb.onchange = async () => {
      if (!(await act(`/users/${u.username}/permissions`, { permissions: { [cb.dataset.perm]: cb.checked } }, `Access updated for @${u.username}.`, "amErr"))) cb.checked = !cb.checked;
    }));
    $("amOut").onclick = async () => { if (await act(`/users/${u.username}/signout`, {}, `@${u.username} was signed out on every device.`, "amErr")) manage(u.username); };
    $("amPwGo").onclick = async () => { if (await act(`/users/${u.username}/password`, { new_password: $("amPw").value }, `Password reset for @${u.username}; they were signed out everywhere.`, "amErr")) closeDialog(); };
    $("amDel").onclick = async () => {
      if (!window.confirm(`Permanently delete @${u.username} and all of their data?`)) return;
      if (await act(`/users/${u.username}/delete`, { confirm: $("amDelTxt").value }, `@${u.username} was deleted.`, "amErr")) closeDialog();
    };
  }

  function addForm() {
    const gen = () => { const a = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"; const r = new Uint32Array(12); crypto.getRandomValues(r); return [...r].map((n) => a[n % a.length]).join(""); };
    dialog("Add account", `<form class="fin-form" id="adForm">
      <div class="row2"><label>Username<input id="adUser" required maxlength="32" autocomplete="off" spellcheck="false" autocapitalize="none"></label><label>Display name<input id="adName" maxlength="40" autocomplete="off"></label></div>
      <div class="row2"><label>Temporary password<input id="adPw" type="text" required autocomplete="off" value="${esc(gen())}"></label><label>Role<select id="adRole"><option value="client">Member</option><option value="admin">Administrator</option></select></label></div>
      <p class="muted small">Share the password securely; the person can change it in Settings. Usernames: 3-32 letters, numbers, dot, dash or underscore.</p>
      <div class="fin-err" id="adErr" role="alert" hidden></div><button type="submit" class="primary">Create account</button></form>`);
    $("adForm").onsubmit = async (ev) => {
      ev.preventDefault();
      const ok = await act("/users", { username: $("adUser").value, password: $("adPw").value, display_name: $("adName").value, role: $("adRole").value }, `Account @${$("adUser").value.trim().toLowerCase()} created.`, "adErr");
      if (ok) closeDialog();
    };
  }

  async function activity() {
    const box = $("adminActivity");
    box.hidden = !box.hidden;
    if (box.hidden) return;
    box.innerHTML = `<p class="muted" role="status">Loading…</p>`;
    try {
      const out = await api("/activity?limit=40", undefined, "GET");
      const text = (e) => {
        const d = e.detail, a = e.action;
        return a === "login" ? `@${d.username} signed in` : a === "account_created" ? `@${d.username} created an account` : a === "password_changed" ? `@${d.username} changed their password` :
          a === "admin_suspend" ? `@${d.admin} suspended @${d.target}` : a === "admin_restore" ? `@${d.admin} restored @${d.target}` : a === "admin_role" ? `@${d.admin} set @${d.target} to ${d.role}` :
          a === "admin_permissions" ? `@${d.admin} changed features for @${d.target}` : a === "admin_password_reset" ? `@${d.admin} reset the password of @${d.target}` :
          a === "admin_user_created" ? `@${d.admin} created @${d.target}` : a === "admin_signout" ? `@${d.admin} signed @${d.target} out (${d.sessions} sessions)` :
          a === "admin_user_deleted" ? `@${d.admin} deleted @${d.target}` : a.replace(/_/g, " ");
      };
      box.innerHTML = `<div class="fcard"><h3>Recent activity <span class="tag">tamper-evident log</span></h3>${out.entries.length ? `<ul class="flist">${out.entries.map((e) => `<li class="frow"><div class="main"><b>${esc(text(e))}</b><span>${esc(e.ts.replace("T", " ").slice(0, 16))} UTC</span></div></li>`).join("")}</ul>` : `<p class="empty">Nothing yet.</p>`}</div>`;
    } catch (e) { box.innerHTML = `<div class="fin-err">${esc(e.message)}</div>`; }
  }

  function init(user) {
    if (user.role !== "admin") return;
    st.me = user;
    document.body.classList.add("is-admin");
    $("adminView").hidden = false;
    $("adminManage").onclick = async () => {
      st.open = !st.open;
      $("adminManage").setAttribute("aria-expanded", String(st.open));
      $("adminManage").textContent = st.open ? "Hide accounts" : "Manage accounts";
      if (st.open) await load(); else renderPortal();
    };
    $("adminActivityBtn").onclick = activity;
    $("adminModalClose").onclick = closeDialog;
    $("adminModal").addEventListener("click", (e) => { if (e.target === $("adminModal")) closeDialog(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("adminModal").hidden) closeDialog(); });
    load();
    loadAi();
    fetch("/api/health").then((r) => r.json()).then((h) => { $("llmBadge").textContent = h.mock_llm ? "mock LLM" : "live LLM"; }).catch(() => {});
    setInterval(() => { if (!document.hidden) { api("/users", undefined, "GET").then((o) => { st.users = o.users; st.summary = o.summary; renderStats(); if (st.open && $("adminModal").hidden) renderPortal(); }).catch(() => {}); } }, 60000);
  }
  if (window.WGAuth) window.WGAuth.onReady(init);
  window.WGAdmin = { reload: load };
})();
