// My money: dashboard, transactions, accounts, budgets/goals/bills, AI reports and the voice-enabled money assistant.
// Everything shown comes from /api/fin/* (the signed-in account's own ledger). Amounts arrive as strings and are only turned into
// numbers for drawing charts; money arithmetic happens on the server (and in integer minor units for the live preview below).
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const SYMBOLS = { BDT: "৳", CNY: "¥", USD: "$", EUR: "€", GBP: "£", INR: "₹" };
  const TITLES = { overview: "Overview", transactions: "Transactions", accounts: "Accounts", plan: "Budgets, goals and bills", reports: "Reports", assistant: "Money assistant", settings: "Settings and privacy" };
  const state = { tab: "overview", period: "month", mounted: false, charts: {}, meta: null, accounts: [], currency: "BDT", txn: { page: 1, q: "", type: "", category: "", account: "", start: "", end: "", sort: "ts", dir: "desc" }, report: null };
  let me = null;

  // ------------------------------------------------------------------------------------------ helpers
  async function api(path, body, method) {
    const opt = body === undefined && !method ? {} : { method: method || "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const r = await fetch("/api/fin" + path, opt);
    let data = null;
    try { data = await r.json(); } catch (e) { /* not JSON */ }
    if (!r.ok) {
      const d = data && data.detail;
      const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => (x.loc ? x.loc.slice(1).join(".") + ": " : "") + x.msg).join("; ") : r.statusText;
      throw Object.assign(new Error(msg || "Request failed"), { status: r.status });
    }
    return data;
  }
  const sym = () => SYMBOLS[state.currency] || state.currency + " ";
  const money = (s, signed) => {
    const n = Number(s);
    if (s === null || s === undefined || !isFinite(n)) return "—";
    const body = sym() + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (n < 0 ? "-" : signed && n > 0 ? "+" : "") + body;
  };
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const pct = (x) => (x === null || x === undefined ? "—" : (x * 100).toFixed(1).replace(/\.0$/, "") + "%");
  const day = (d) => (d ? String(d).slice(0, 10) : "");
  const todayStr = () => new Date().toISOString().slice(0, 10);
  const uuid = () => (window.crypto && crypto.randomUUID ? crypto.randomUUID() : "r" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10));
  const toast = (m) => { if (window.WGUI && window.WGUI.toast) window.WGUI.toast(m); };
  function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
  function toMinor(str) {                        // "1,234.5" -> 123450 without floating point; NaN when it is not an amount
    const t = String(str ?? "").replace(/,/g, "").trim();
    if (!/^-?\d+(\.\d{1,2})?$/.test(t)) return NaN;
    const neg = t.startsWith("-");
    const [a, b = ""] = t.replace("-", "").split(".");
    const v = parseInt(a, 10) * 100 + parseInt((b + "00").slice(0, 2), 10);
    return neg ? -v : v;
  }
  const fromMinor = (n) => (n < 0 ? "-" : "") + Math.floor(Math.abs(n) / 100) + "." + String(Math.abs(n) % 100).padStart(2, "0");
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const palette = () => [css("--accent"), css("--brass"), "#7a8cff", "#e58fa6", "#59c3e6", "#b7a2f0", "#9ad06b", "#f0a56a", "#8a96a6"];

  function destroyCharts() { Object.values(state.charts).forEach((c) => { try { c.destroy(); } catch (e) { /* already gone */ } }); state.charts = {}; }
  function chart(id, cfg) {
    const cv = $(id);
    if (!cv || !window.Chart) return;
    cfg.options = Object.assign({ responsive: true, maintainAspectRatio: false }, cfg.options || {});
    state.charts[id] = new Chart(cv, cfg);
  }
  const axis = () => ({ ticks: { color: css("--muted") }, grid: { color: css("--line") } });
  const moneyTip = { callbacks: { label: (c) => `${c.dataset.label || c.label}: ${money(c.parsed.y ?? c.parsed.x ?? c.parsed)}` } };
  const emptyHtml = (t) => `<p class="empty">${esc(t)}</p>`;
  const chartBox = (id, label, tall) => `<div class="chart-box${tall ? " tall" : ""}"><canvas id="${id}" role="img" aria-label="${esc(label)}"></canvas></div>`;

  function banner(msg) { const b = $("finBanner"); b.hidden = !msg; b.textContent = msg || ""; }

  // ------------------------------------------------------------------------------------------ period and tabs
  function periodQuery() {
    const t = new Date();
    const iso = (d) => d.toISOString().slice(0, 10);
    const p = state.period;
    if (p === "lastmonth") { const d = new Date(t.getFullYear(), t.getMonth() - 1, 1, 12); return `kind=month&ref=${iso(d)}`; }
    if (p === "custom") return `kind=custom&start=${$("finFrom").value || todayStr()}&end=${$("finTo").value || todayStr()}`;
    return `kind=${p}&ref=${todayStr()}`;
  }

  function showTab(name) {
    state.tab = name;
    document.querySelectorAll(".fin-tab").forEach((t) => (t.hidden = t.id !== "finTab-" + name));
    document.querySelectorAll('.nav[data-tab], .fin-tabs button').forEach((b) => {
      const on = b.dataset.tab === name;
      b.setAttribute(b.classList.contains("nav") ? "aria-pressed" : "aria-selected", String(on));
    });
    $("finTitle").textContent = TITLES[name];
    $("finPeriod").hidden = !["overview", "reports"].includes(name);
    $("finCustom").hidden = $("finPeriod").hidden || state.period !== "custom";
    const add = $("finAdd");
    add.hidden = ["reports", "assistant", "settings"].includes(name);
    add.querySelector("span").textContent = { overview: "Add transaction", transactions: "Add transaction", accounts: "Add account", plan: "Add…" }[name] || "Add";
    destroyCharts();
    ({ overview: loadOverview, transactions: loadTxns, accounts: loadAccounts, plan: loadPlan, reports: loadReports, assistant: loadAssistant, settings: loadSettings }[name])().catch(fail);
    if (window.matchMedia("(max-width: 900px)").matches && $("sidebar").classList.contains("open") && $("scrim")) $("scrim").click();
  }

  function fail(e) { banner(e.message || "Something went wrong."); }

  async function refreshAccounts() {
    state.accounts = await api("/accounts", undefined, "GET");
    return state.accounts;
  }

  // ------------------------------------------------------------------------------------------ OVERVIEW
  const cmpHtml = (c, goodWhenDown) => {
    if (!c || c.change_pct === null || c.change_pct === undefined) return `<div class="d">no earlier period to compare</div>`;
    const up = Number(c.change) > 0, flat = Number(c.change) === 0;
    const cls = flat ? "" : (up !== !!goodWhenDown ? "good" : "bad");
    return `<div class="d ${cls}">${flat ? "no change" : (up ? "▲ " : "▼ ") + pct(Math.abs(c.change_pct))} vs previous period</div>`;
  };

  async function loadOverview() {
    const root = $("finTab-overview");
    root.innerHTML = `<p class="muted">Loading…</p>`;
    const d = await api("/dashboard?" + periodQuery(), undefined, "GET");
    state.currency = d.position.currency || state.currency;
    const s = d.summary, pos = d.position, cmp = d.comparison;
    $("finSub").textContent = `${s.start} to ${s.end} · amounts in ${state.currency} · actual records only` + (s.excluded.future_dated ? ` · ${s.excluded.future_dated} scheduled (future-dated) not counted yet` : "");
    banner(pos.accounts.length ? "" : "Add your accounts and their opening balances first (Accounts tab). Until then balances and net worth cannot be shown, and nothing is estimated for you.");
    const kpi = (l, v, d2, cls) => `<div class="fcard kpi ${cls || ""}"><div class="l">${l}</div><div class="v">${v}</div>${d2 || ""}</div>`;
    const rate = s.savings_rate_implied;
    const alerts = d.alerts.length ? `<div class="fcard" style="margin-bottom:14px"><h3>Needs attention</h3><ul class="flist">${d.alerts.slice(0, 5).map((a) => `<li class="frow"><div class="main"><b>${esc(a.title)}</b><span>${esc(a.body)}</span></div><span class="chip ${a.severity === "high" ? "over" : a.severity === "medium" ? "warning" : ""}">${esc(a.severity)}</span></li>`).join("")}</ul></div>` : "";
    root.innerHTML = alerts + `
      <div class="fin-grid fin-kpis">
        ${kpi("Income", money(s.income), cmpHtml(cmp.income, false))}
        ${kpi("Spending", money(s.spending), cmpHtml(cmp.spending, true))}
        ${kpi("Net cash flow", money(s.net_cash_flow, true), cmpHtml(cmp.net_cash_flow, false))}
        ${kpi("Savings rate", rate === null || rate === undefined ? "—" : pct(rate), `<div class="d">${s.savings_rate_actual === null || s.savings_rate_actual === undefined ? "income needed to compute" : "moved to savings: " + pct(s.savings_rate_actual)}</div>`)}
        ${kpi("Liquid funds", pos.accounts.length ? money(pos.liquid) : "—", `<div class="d">cash ${money(pos.cash)} · bank ${money(pos.bank)} · wallets ${money(pos.wallet)}</div>`)}
        ${kpi("Net worth", pos.accounts.length ? money(pos.net_worth) : "—", `<div class="d">${pos.liabilities !== "0.00" ? "owes " + money(pos.liabilities) : "no liabilities recorded"}</div>`)}
      </div>
      <div class="fin-grid fin-cols">
        <div class="fcard"><h3>Income vs spending</h3>${chartBox("chIncExp", "Income versus spending, this period and the previous one")}</div>
        <div class="fcard"><h3>Spending by category</h3>${s.by_category.length ? chartBox("chCat", "Spending by category") : emptyHtml("No spending recorded in this period.")}</div>
      </div>
      <div class="fin-grid fin-cols">
        <div class="fcard"><h3>Daily spending</h3>${s.daily.some((x) => x.minor) ? chartBox("chDaily", "Daily spending with a 7-day average") : emptyHtml("No daily spending to chart yet.")}</div>
        <div class="fcard"><h3>Budget vs actual</h3>${d.budgets.length ? chartBox("chBudget", "Budget versus actual spending") : emptyHtml("No budgets yet. Create one in Budgets and goals.")}</div>
      </div>
      <div class="fin-grid fin-cols">
        <div class="fcard"><h3>Essential vs discretionary</h3>${s.expense_gross !== "0.00" ? chartBox("chEss", "Essential versus discretionary spending") : emptyHtml("Nothing to compare yet.")}<p class="estimate-note">Unclassified spending is shown separately; classify transactions to improve this.</p></div>
        <div class="fcard"><h3>Top merchants</h3>${s.by_merchant.length ? chartBox("chMer", "Spending by merchant") : emptyHtml("Add a merchant to transactions to see this.")}</div>
      </div>
      <div class="fin-grid fin-cols">
        <div class="fcard"><h3>Goals</h3>${goalsList(d.goals)}</div>
        <div class="fcard"><h3>Upcoming bills</h3>${billsList(d.upcoming)}</div>
      </div>
      <div class="fin-grid fin-cols">
        <div class="fcard"><h3>What stands out <span class="tag">from your records</span></h3>${insightsList(d.insights)}</div>
        <div class="fcard"><h3>Forecast <span class="tag">estimate</span></h3>${forecastCard(d.forecast)}</div>
      </div>
      <div class="fcard"><h3>Recent transactions</h3>${d.recent.length ? `<ul class="flist">${d.recent.map(txnRow).join("")}</ul>` : emptyHtml("No transactions yet. Add one, or tell the assistant what you spent.")}</div>`;
    drawOverviewCharts(d);
    root.querySelectorAll("[data-txn]").forEach((r) => (r.onclick = () => openTxn(r.dataset.txn)));
  }

  function txnRow(t) {
    const sign = t.type === "income" || t.type === "refund" || (t.type === "adjustment" && t.direction === "in") ? "in" : "out";
    const amt = t.type === "transfer" ? `↔ ${money(t.final_amount)}` : money(sign === "in" ? t.final_amount : "-" + t.final_amount, sign === "in");
    return `<li class="frow" data-txn="${esc(t.id)}" tabindex="0" style="cursor:pointer"><div class="main"><b>${esc(t.merchant || t.item_name || t.category || t.type)}</b><span>${esc(day(t.ts))}${t.scheduled ? " · scheduled" : ""} · ${esc(t.category || t.type)}${t.source === "voice" ? " · voice" : t.source === "assistant" ? " · assistant" : ""}</span></div><span class="amt ${sign}">${amt}</span></li>`;
  }
  function goalsList(gs) {
    if (!gs.length) return emptyHtml("No goals yet. A goal turns saving into something you can watch.");
    return `<ul class="flist">${gs.slice(0, 4).map((g) => `<li class="frow"><div class="main" style="flex:1"><b>${esc(g.name)}</b><span>${money(g.saved)} of ${money(g.target)} · ${g.reached ? "target reached" : g.on_track === true ? "on track" : g.on_track === false ? "behind schedule" : "no deadline set"}</span><div class="bar"><i style="width:${Math.round(g.progress_pct * 100)}%"></i></div></div></li>`).join("")}</ul>`;
  }
  function billsList(bs) {
    if (!bs.length) return emptyHtml("No upcoming bills. Add rent, internet or tuition in Budgets and goals.");
    return `<ul class="flist">${bs.slice(0, 6).map((b) => `<li class="frow"><div class="main"><b>${esc(b.name)}</b><span>due ${esc(b.due)} · ${b.days_until_due < 0 ? plural(Math.abs(b.days_until_due), "day") + " late" : b.days_until_due === 0 ? "today" : "in " + plural(b.days_until_due, "day")}</span></div><span class="amt">${money(b.amount)} <span class="chip ${esc(b.status)}">${esc(b.status)}</span></span></li>`).join("")}</ul>`;
  }
  function insightsList(ins) {
    if (!ins.length) return emptyHtml("No unusual patterns yet. Insights appear as you record more.");
    return `<div class="fin-grid">${ins.slice(0, 4).map((i) => `<div class="insight-card ${esc(i.severity)}"><b>${esc(i.title)}</b><div>${esc(i.pattern)}</div><div class="why">${esc(i.why)}</div><div class="act">→ ${esc(i.action)}</div>${i.impact ? `<div class="assume">Estimated impact ${money(i.impact)}. ${esc((i.assumptions || []).join(" "))}</div>` : ""}</div>`).join("")}</div>`;
  }
  function forecastCard(f) {
    return `<div class="kv"><div><b>Liquid now</b>${money(f.current_liquid)}</div><div><b>Expected daily spending</b>${money(f.expected_variable_spending)} over ${f.days_left} days</div><div><b>Bills before month end</b>${money(f.upcoming_bills)}</div><div><b>Projected month-end</b>${money(f.projected_end_balance)}</div></div>
      <p class="estimate-note">Range ${money(f.range_low)} to ${money(f.range_high)}. ${esc(f.assumptions.join(" "))}</p>`;
  }

  function drawOverviewCharts(d) {
    const s = d.summary, c = d.comparison, pal = palette();
    const n = (x) => Number(x);
    chart("chIncExp", { type: "bar", data: { labels: ["Previous period", "This period"], datasets: [
      { label: "Income", data: [n(c.income.previous), n(c.income.current)], backgroundColor: pal[0] }, { label: "Spending", data: [n(c.spending.previous), n(c.spending.current)], backgroundColor: pal[1] }] },
      options: { scales: { x: axis(), y: axis() }, plugins: { legend: { labels: { color: css("--ink-2") } }, tooltip: moneyTip } } });
    if (s.by_category.length) {
      const top = s.by_category.slice(0, 7), rest = s.by_category.slice(7).reduce((a, x) => a + x.minor, 0);
      const labels = top.map((x) => x.category).concat(rest ? ["other"] : []), data = top.map((x) => x.minor / 100).concat(rest ? [rest / 100] : []);
      chart("chCat", { type: "doughnut", data: { labels, datasets: [{ data, backgroundColor: pal, borderColor: css("--surface"), borderWidth: 2 }] },
        options: { cutout: "62%", plugins: { legend: { position: "right", labels: { color: css("--ink-2"), boxWidth: 12 } }, tooltip: { callbacks: { label: (x) => `${x.label}: ${money(x.parsed)}` } } } } });
    }
    if (s.daily.some((x) => x.minor)) {
      const vals = s.daily.map((x) => x.minor / 100);
      const avg = vals.map((_, i) => { const w = vals.slice(Math.max(0, i - 6), i + 1); return w.reduce((a, b) => a + b, 0) / w.length; });
      chart("chDaily", { type: "line", data: { labels: s.daily.map((x) => x.date.slice(5)), datasets: [
        { label: "Spending", data: vals, borderColor: pal[0], backgroundColor: pal[0] + "33", fill: true, tension: .25, pointRadius: 0 },
        { label: "7-day average", data: avg, borderColor: pal[1], borderDash: [5, 4], pointRadius: 0, tension: .25 }] },
        options: { scales: { x: Object.assign(axis(), { ticks: { color: css("--muted"), maxTicksLimit: 8 } }), y: axis() }, plugins: { legend: { labels: { color: css("--ink-2") } }, tooltip: moneyTip } } });
    }
    if (d.budgets.length) {
      chart("chBudget", { type: "bar", data: { labels: d.budgets.map((b) => b.name), datasets: [
        { label: "Spent", data: d.budgets.map((b) => n(b.spent)), backgroundColor: d.budgets.map((b) => (b.status === "over" ? css("--warn") : b.status === "warning" ? pal[1] : pal[0])) },
        { label: "Limit", data: d.budgets.map((b) => n(b.limit)), backgroundColor: css("--surface-3") }] },
        options: { indexAxis: "y", scales: { x: axis(), y: axis() }, plugins: { legend: { labels: { color: css("--ink-2") } }, tooltip: moneyTip } } });
    }
    if (s.expense_gross !== "0.00") {
      const e = s.essential_split;
      chart("chEss", { type: "doughnut", data: { labels: ["Essential", "Discretionary", "Unclassified"], datasets: [{ data: [e.essential.minor / 100, e.discretionary.minor / 100, e.unclassified.minor / 100], backgroundColor: [pal[0], pal[1], css("--surface-3")], borderColor: css("--surface"), borderWidth: 2 }] },
        options: { cutout: "62%", plugins: { legend: { position: "right", labels: { color: css("--ink-2"), boxWidth: 12 } }, tooltip: { callbacks: { label: (x) => `${x.label}: ${money(x.parsed)}` } } } } });
    }
    if (s.by_merchant.length) {
      chart("chMer", { type: "bar", data: { labels: s.by_merchant.slice(0, 6).map((m) => m.merchant), datasets: [{ label: "Spent", data: s.by_merchant.slice(0, 6).map((m) => m.minor / 100), backgroundColor: pal[2] }] },
        options: { indexAxis: "y", scales: { x: axis(), y: axis() }, plugins: { legend: { display: false }, tooltip: moneyTip } } });
    }
  }

  // ------------------------------------------------------------------------------------------ TRANSACTIONS
  async function loadTxns() {
    const root = $("finTab-transactions");
    if (!state.meta) state.meta = await api("/meta", undefined, "GET");
    await refreshAccounts();
    const f = state.txn;
    const cats = Object.keys(state.meta.expense_categories).concat(state.meta.income_categories);
    root.innerHTML = `
      <div class="fin-toolbar">
        <input id="tqQ" class="grow" type="search" placeholder="Search merchant, item, note, tag…" value="${esc(f.q)}" aria-label="Search">
        <select id="tqType" aria-label="Type"><option value="">All types</option>${state.meta.transaction_types.map((t) => `<option ${f.type === t ? "selected" : ""}>${t}</option>`).join("")}</select>
        <select id="tqCat" aria-label="Category"><option value="">All categories</option>${cats.map((c) => `<option ${f.category === c ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>
        <select id="tqAcc" aria-label="Account"><option value="">All accounts</option>${state.accounts.map((a) => `<option value="${esc(a.id)}" ${f.account === a.id ? "selected" : ""}>${esc(a.name)}</option>`).join("")}</select>
        <input id="tqFrom" type="date" value="${esc(f.start)}" aria-label="From date"><input id="tqTo" type="date" value="${esc(f.end)}" aria-label="To date">
        <select id="tqSort" aria-label="Sort"><option value="ts:desc">Newest first</option><option value="ts:asc">Oldest first</option><option value="amount:desc">Largest first</option><option value="amount:asc">Smallest first</option></select>
      </div>
      <div class="fin-toolbar"><button type="button" id="tqExport">Export CSV</button><label class="ghost" style="display:inline-flex;gap:6px;align-items:center;cursor:pointer;border:1px solid var(--line);border-radius:11px;padding:8px 14px;font-size:13.5px;font-weight:600">Import CSV<input id="tqImport" type="file" accept=".csv,text/csv" hidden></label><span class="muted small" id="tqMsg" role="status"></span></div>
      <div id="tqList"></div>`;
    $("tqSort").value = f.sort + ":" + f.dir;
    let timer;
    const reload = () => { f.q = $("tqQ").value; f.type = $("tqType").value; f.category = $("tqCat").value; f.account = $("tqAcc").value; f.start = $("tqFrom").value; f.end = $("tqTo").value; [f.sort, f.dir] = $("tqSort").value.split(":"); f.page = 1; drawTxnList().catch(fail); };
    $("tqQ").oninput = () => { clearTimeout(timer); timer = setTimeout(reload, 300); };
    ["tqType", "tqCat", "tqAcc", "tqFrom", "tqTo", "tqSort"].forEach((id) => ($(id).onchange = reload));
    $("tqExport").onclick = () => download("/api/fin/export/transactions.csv", "transactions.csv");
    $("tqImport").onchange = importCsv;
    await drawTxnList();
  }

  async function drawTxnList() {
    const f = state.txn;
    const p = new URLSearchParams({ page: f.page, size: 20, sort: f.sort, direction: f.dir });
    [["q", f.q], ["type", f.type], ["category", f.category], ["account_id", f.account], ["start", f.start], ["end", f.end]].forEach(([k, v]) => { if (v) p.set(k, v); });
    const res = await api("/transactions?" + p.toString(), undefined, "GET");
    const names = Object.fromEntries(state.accounts.map((a) => [a.id, a.name]));
    const box = $("tqList");
    if (!res.items.length) { box.innerHTML = `<div class="fcard">${emptyHtml(f.q || f.type || f.category || f.account || f.start || f.end ? "Nothing matches these filters." : "No transactions yet. Add one, import a CSV, or tell the assistant what you spent.")}</div>`; return; }
    box.innerHTML = `<div class="table-wrap"><table class="ftable"><caption class="sr-only">Transactions</caption><thead><tr><th>Date</th><th>Description</th><th>Category</th><th>Account</th><th class="num">Amount</th></tr></thead><tbody>${res.items.map((t) => {
      const inflow = t.type === "income" || t.type === "refund" || (t.type === "adjustment" && t.direction === "in");
      const amt = t.type === "transfer" ? `↔ ${money(t.final_amount)}` : money(inflow ? t.final_amount : "-" + t.final_amount, inflow);
      const detail = [t.item_name, t.discount !== "0.00" ? "discount " + money(t.discount) : "", t.tax !== "0.00" ? "VAT " + money(t.tax) : ""].filter(Boolean).join(" · ");
      return `<tr data-txn="${esc(t.id)}" tabindex="0"><td data-label="Date">${esc(day(t.ts))}${t.scheduled ? ` <span class="chip scheduled" title="Dated in the future: not part of any balance or total yet">scheduled</span>` : ""}</td><td data-label="Description"><b>${esc(t.merchant || t.item_name || t.type)}</b>${t.has_receipt ? ` <span class="chip" title="A receipt photo is attached">receipt</span>` : ""}${detail ? `<div class="muted small">${esc(detail)}</div>` : ""}</td><td data-label="Category">${esc(t.category || t.type)}${t.essential === true ? ` <span class="chip ok">essential</span>` : ""}</td><td data-label="Account">${esc(names[t.account_id] || "")}${t.to_account_id ? " → " + esc(names[t.to_account_id] || "") : ""}</td><td class="num amt ${inflow ? "in" : "out"}" data-label="Amount">${amt}</td></tr>`;
    }).join("")}</tbody></table></div>
      <div class="pager"><span>${res.total} transactions · page ${res.page} of ${res.pages}</span><span><button type="button" id="pgPrev" ${res.page <= 1 ? "disabled" : ""}>Previous</button> <button type="button" id="pgNext" ${res.page >= res.pages ? "disabled" : ""}>Next</button></span></div>`;
    box.querySelectorAll("tr[data-txn]").forEach((r) => { r.onclick = () => openTxn(r.dataset.txn); r.onkeydown = (e) => { if (e.key === "Enter") openTxn(r.dataset.txn); }; });
    const prev = $("pgPrev"), next = $("pgNext");
    if (prev) prev.onclick = () => { f.page--; drawTxnList().catch(fail); };
    if (next) next.onclick = () => { f.page++; drawTxnList().catch(fail); };
  }

  async function download(path, name) {
    try {
      const r = await fetch(path);
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "Download failed");
      const blob = await r.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } catch (e) { fail(e); }
  }

  async function importCsv(ev) {
    const file = ev.target.files[0];
    if (!file) return;
    const msg = $("tqMsg");
    try {
      const text = await file.text();
      const accs = state.accounts;
      const res = await api("/import/transactions", { csv: text, account_id: accs.length === 1 ? accs[0].id : null });
      msg.textContent = `Imported ${res.created}, skipped ${res.skipped_duplicates} already imported${res.error_count ? `, ${res.error_count} rows had problems (first: row ${res.errors[0].row}: ${res.errors[0].error})` : ""}.`;
      await drawTxnList();
    } catch (e) { msg.textContent = e.message; }
    ev.target.value = "";
  }

  // ---- the add / edit form
  function modal(title, build) {
    $("finModalTitle").textContent = title;
    const body = $("finModalBody");
    body.innerHTML = "";
    build(body);
    $("finModal").hidden = false;
    const first = body.querySelector("input, select, textarea, button");
    if (first) first.focus();
  }
  const closeModal = () => { $("finModal").hidden = true; $("finModalBody").innerHTML = ""; };

  async function openTxn(id) {
    if (!state.meta) state.meta = await api("/meta", undefined, "GET");
    await refreshAccounts();
    const t = id ? await api("/transactions/" + id, undefined, "GET") : null;
    txnForm(t);
  }

  function txnForm(t) {
    const edit = !!(t && t.id);                       // a draft handed over by the assistant has no id: it is a new record
    if (!state.accounts.length) { modal("Add an account first", (b) => { b.innerHTML = `<p>Transactions live in an account (cash, bank, bKash…). Add at least one, with its opening balance, so your balances are correct.</p>`; const go = el("button", "primary wide", "Add an account"); go.onclick = () => { closeModal(); openAccountForm(); }; b.appendChild(go); }); return; }
    const key = uuid();
    modal(edit ? "Edit transaction" : t ? "Review before saving" : "Add transaction", (body) => {
      const f = document.createElement("form");
      f.className = "fin-form";
      const accOpts = (sel) => state.accounts.map((a) => `<option value="${esc(a.id)}" ${sel === a.id ? "selected" : ""}>${esc(a.name)} (${esc(a.type)})</option>`).join("");
      f.innerHTML = `
        <div class="seg" id="tfType" role="group" aria-label="Type">${state.meta.transaction_types.map((x) => `<button type="button" data-v="${x}" aria-pressed="${(t ? t.type : "expense") === x}" ${edit && t.type !== x ? "disabled" : ""}>${x}</button>`).join("")}</div>
        <div class="row2"><label>Date<input id="tfDate" type="date" value="${esc(t ? day(t.ts) : todayStr())}" required></label>
          <label>Amount paid<input id="tfFinal" inputmode="decimal" placeholder="0.00" value="${esc(t ? t.final_amount : "")}" autocomplete="off"></label></div>
        <label id="tfAccL">Account<select id="tfAcc">${accOpts(t && t.account_id)}</select></label>
        <label id="tfToL" hidden>To account<select id="tfTo">${accOpts(t && t.to_account_id)}</select></label>
        <label id="tfDirL" hidden>Direction<select id="tfDir"><option value="in">Money in</option><option value="out">Money out</option></select></label>
        <details id="tfMore" ${t && (t.discount !== "0.00" || t.tax !== "0.00" || t.service_charge !== "0.00") ? "open" : ""}><summary>Discount, VAT and service charge</summary>
          <div class="fin-form" style="margin-top:8px"><div class="row2"><label>Before discount<input id="tfGross" inputmode="decimal" placeholder="optional" value="${esc(t && t.discount !== "0.00" ? t.gross_amount : "")}"></label><label>Discount<input id="tfDisc" inputmode="decimal" value="${esc(t && t.discount !== "0.00" ? t.discount : "")}"></label></div>
          <div class="row2"><label>VAT / tax<input id="tfTax" inputmode="decimal" value="${esc(t && t.tax !== "0.00" ? t.tax : "")}"></label><label>Service charge<input id="tfSvc" inputmode="decimal" value="${esc(t && t.service_charge !== "0.00" ? t.service_charge : "")}"></label></div>
          <div class="fin-preview" id="tfPreview">Fill “before discount” to calculate the amount paid automatically.</div></div></details>
        <div class="row2" id="tfCatRow"><label>Category<select id="tfCat"></select></label><label>Subcategory<select id="tfSub"></select></label></div>
        <div class="row2"><label>Merchant or shop<input id="tfMer" maxlength="80" value="${esc(t ? t.merchant || "" : "")}"></label><label>Item or purpose<input id="tfItem" maxlength="120" value="${esc(t ? t.item_name || "" : "")}"></label></div>
        <div class="row2"><label>Payment method<select id="tfPay"><option value="">—</option>${state.meta.payment_methods.map((m) => `<option ${t && t.payment_method === m ? "selected" : ""}>${esc(m)}</option>`).join("")}</select></label>
          <label>Needed or optional?<select id="tfEss"><option value="">Decide for me</option><option value="1" ${t && t.essential === true ? "selected" : ""}>Essential</option><option value="0" ${t && t.essential === false ? "selected" : ""}>Discretionary</option></select></label></div>
        <label class="check"><input id="tfRec" type="checkbox" ${t && t.recurring ? "checked" : ""}> Repeats regularly (subscription, bill)</label>
        <label>Tags (comma separated)<input id="tfTags" maxlength="200" value="${esc(t ? t.tags.join(", ") : "")}"></label>
        <label>Note<textarea id="tfNote" rows="2" maxlength="500">${esc(t ? t.note || "" : "")}</textarea></label>
        ${edit ? `<div class="fin-receipt" id="tfRcp"><span class="muted small">Receipt photo (JPEG, PNG or WebP, up to 2 MB; location data is removed)</span><div class="fin-toolbar" style="margin:6px 0 0"><input id="tfRcpFile" type="file" accept="image/jpeg,image/png,image/webp" aria-label="Receipt photo"><button type="button" id="tfRcpDel" hidden>Remove photo</button></div><div id="tfRcpView"></div></div>` : ""}
        <div class="fin-err" id="tfErr" role="alert" hidden></div>
        <div class="row2"><button type="submit" class="primary" id="tfSave">${edit ? "Save changes" : "Save transaction"}</button>${edit ? `<button type="button" class="warn" id="tfDel">Delete</button>` : `<button type="button" id="tfCancel">Cancel</button>`}</div>`;
      body.appendChild(f);
      let type = t ? t.type : "expense";
      const set = () => {
        $("tfToL").hidden = type !== "transfer"; $("tfDirL").hidden = type !== "adjustment";
        $("tfCatRow").hidden = type === "transfer" || type === "adjustment"; $("tfMore").hidden = !["expense", "refund"].includes(type);
        const cats = type === "income" ? state.meta.income_categories : Object.keys(state.meta.expense_categories);
        const cur = t && t.category && cats.includes(t.category) ? t.category : (type === "income" ? "salary" : "food");
        $("tfCat").innerHTML = cats.map((c) => `<option ${c === ($("tfCat").value || cur) ? "selected" : ""}>${esc(c)}</option>`).join("");
        subs();
        $("tfAccL").firstChild.textContent = type === "income" || type === "refund" ? "Received into" : type === "transfer" ? "From account" : "Account";
        $("tfFinal").parentElement.firstChild.textContent = type === "income" ? "Amount received" : type === "transfer" || type === "adjustment" ? "Amount" : "Amount paid";
      };
      const subs = () => { const list = (state.meta.expense_categories[$("tfCat").value] || []); $("tfSub").innerHTML = `<option value="">—</option>` + list.map((s2) => `<option ${t && t.subcategory === s2 ? "selected" : ""}>${esc(s2)}</option>`).join(""); };
      $("tfCat").onchange = subs;
      f.querySelectorAll("#tfType button").forEach((b) => (b.onclick = () => { if (edit) return; type = b.dataset.v; f.querySelectorAll("#tfType button").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); set(); }));
      set();
      if (t) { $("tfCat").value = t.category || $("tfCat").value; subs(); $("tfSub").value = t.subcategory || ""; if (t.direction) $("tfDir").value = t.direction; }
      const preview = () => {
        const g = toMinor($("tfGross").value), d = toMinor($("tfDisc").value || "0"), x = toMinor($("tfTax").value || "0"), sv = toMinor($("tfSvc").value || "0");
        const p = $("tfPreview");
        if ([g, d, x, sv].some(Number.isNaN)) { p.textContent = "Enter amounts like 850 or 850.50."; return; }
        if ($("tfGross").value.trim() === "") { p.textContent = "Fill “before discount” to calculate the amount paid automatically."; $("tfFinal").readOnly = false; return; }
        const fin = g - d + x + sv;
        p.textContent = `${money(fromMinor(g))} − ${money(fromMinor(d))} discount + ${money(fromMinor(x))} VAT + ${money(fromMinor(sv))} service = ${money(fromMinor(fin))} paid`;
        $("tfFinal").value = fromMinor(fin); $("tfFinal").readOnly = true;
      };
      ["tfGross", "tfDisc", "tfTax", "tfSvc"].forEach((id) => $(id).addEventListener("input", preview));
      preview();
      const err = (m) => { $("tfErr").textContent = m; $("tfErr").hidden = !m; };
      if (edit) wireReceipt(t);
      if ($("tfCancel")) $("tfCancel").onclick = closeModal;
      if ($("tfDel")) $("tfDel").onclick = async () => {
        if (!window.confirm("Delete this transaction? It will no longer count in any balance or report.")) return;
        try { await api(`/transactions/${t.id}/delete`, {}); closeModal(); toast("Transaction deleted"); afterChange(); } catch (e) { err(e.message); }
      };
      f.onsubmit = async (ev) => {
        ev.preventDefault();
        err("");
        const body2 = { type, account_id: $("tfAcc").value, ts: $("tfDate").value };
        const final = $("tfFinal").value.trim(), gross = $("tfGross").value.trim();
        if (gross && ["expense", "refund"].includes(type)) {
          body2.gross_amount = gross; body2.discount = $("tfDisc").value.trim() || "0"; body2.tax = $("tfTax").value.trim() || "0"; body2.service_charge = $("tfSvc").value.trim() || "0";
        } else {
          if (!final) { err("Enter the amount."); return; }
          body2.amount = final;
          if (["expense", "refund"].includes(type) && ($("tfDisc").value.trim() || $("tfTax").value.trim() || $("tfSvc").value.trim())) {
            body2.final_amount = final; delete body2.amount;
            body2.discount = $("tfDisc").value.trim() || "0"; body2.tax = $("tfTax").value.trim() || "0"; body2.service_charge = $("tfSvc").value.trim() || "0";
          }
        }
        if (type === "transfer") body2.to_account_id = $("tfTo").value;
        if (type === "adjustment") body2.direction = $("tfDir").value;
        if (type !== "transfer" && type !== "adjustment") { body2.category = $("tfCat").value; if ($("tfSub").value) body2.subcategory = $("tfSub").value; }
        if ($("tfMer").value.trim()) body2.merchant = $("tfMer").value.trim();
        if ($("tfItem").value.trim()) body2.item_name = $("tfItem").value.trim();
        if ($("tfPay").value) body2.payment_method = $("tfPay").value;
        if ($("tfEss").value !== "") body2.essential = $("tfEss").value === "1";
        body2.recurring = $("tfRec").checked;
        body2.tags = $("tfTags").value.split(",").map((x) => x.trim()).filter(Boolean);
        body2.note = $("tfNote").value.trim();
        if (!edit) body2.idempotency_key = key;                           // double-clicking Save can never create two records
        $("tfSave").disabled = true;
        try { await api(edit ? "/transactions/" + t.id : "/transactions", body2); if (t && t._draft) await api("/assistant/cancel", {}); closeModal(); toast(edit ? "Transaction updated" : "Transaction saved"); afterChange(); }
        catch (e2) { err(e2.message); $("tfSave").disabled = false; }
      };
    });
  }

  function afterChange() { showTab(state.tab); }

  // ---- receipt photo: the file is sent as raw bytes; the server decides the type from the content and strips metadata
  async function showReceipt(id) {
    const view = $("tfRcpView");
    try {
      const r = await fetch(`/api/fin/transactions/${id}/receipt`);
      if (!r.ok) { view.innerHTML = ""; $("tfRcpDel").hidden = true; return; }
      const url = URL.createObjectURL(await r.blob());
      view.innerHTML = `<a href="${url}" target="_blank" rel="noopener"><img src="${url}" alt="Receipt photo" style="max-width:100%;max-height:180px;border-radius:12px;margin-top:8px;border:1px solid var(--line)"></a>`;
      $("tfRcpDel").hidden = false;
    } catch (e) { view.innerHTML = ""; }
  }
  function wireReceipt(t) {
    if (t.has_receipt) showReceipt(t.id);
    $("tfRcpFile").onchange = async (ev) => {
      const f = ev.target.files[0];
      if (!f) return;
      if (f.size > 2000000) { $("tfErr").textContent = "That photo is over 2 MB. Take it at a lower resolution."; $("tfErr").hidden = false; ev.target.value = ""; return; }
      try {
        const r = await fetch(`/api/fin/transactions/${t.id}/receipt`, { method: "POST", headers: { "Content-Type": f.type || "application/octet-stream" }, body: f });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j.detail || "Upload failed");
        $("tfErr").hidden = true; toast("Receipt attached"); showReceipt(t.id);
      } catch (e) { $("tfErr").textContent = e.message; $("tfErr").hidden = false; }
      ev.target.value = "";
    };
    $("tfRcpDel").onclick = async () => { try { await api(`/transactions/${t.id}/receipt/delete`, {}); $("tfRcpView").innerHTML = ""; $("tfRcpDel").hidden = true; toast("Receipt removed"); } catch (e) { $("tfErr").textContent = e.message; $("tfErr").hidden = false; } };
  }

  // ------------------------------------------------------------------------------------------ ACCOUNTS
  async function loadAccounts() {
    const root = $("finTab-accounts");
    const [accs, pos] = await Promise.all([api("/accounts?include_archived=true", undefined, "GET"), api("/position", undefined, "GET")]);
    state.accounts = accs.filter((a) => !a.archived);
    state.currency = pos.currency;
    $("finSub").textContent = "Balances are your opening balance plus the transactions you recorded. Check them against your bank or wallet from time to time.";
    banner(accs.length ? "" : "Add the places your money lives (cash, bank, bKash…) with today's balance. That is the starting point for everything else.");
    root.innerHTML = `
      <div class="fin-grid fin-kpis">
        <div class="fcard kpi"><div class="l">Liquid funds</div><div class="v">${money(pos.liquid)}</div><div class="d">cash, bank, wallets, savings</div></div>
        <div class="fcard kpi"><div class="l">Liabilities</div><div class="v">${money(pos.liabilities)}</div><div class="d">cards and loans</div></div>
        <div class="fcard kpi"><div class="l">Net worth</div><div class="v">${money(pos.net_worth)}</div><div class="d">${pos.excluded_other_currency.length ? "excludes other-currency accounts: " + esc(pos.excluded_other_currency.join(", ")) : "accounts in " + esc(pos.currency)}</div></div>
      </div>
      <div class="fin-grid fin-cols">${accs.map((a) => `<div class="fcard acc-card" style="${a.archived ? "opacity:.55" : ""}"><h3>${esc(a.type.replace("_", " "))}${a.archived ? ` <span class="chip">archived</span>` : ""}</h3><div><b>${esc(a.name)}</b></div><div class="bal ${a.balance_minor < 0 ? "neg" : ""}">${money(a.balance)}</div><div class="muted small">opening ${money(a.opening_balance)} on ${esc(a.opening_date)}</div><div class="fin-toolbar" style="margin:6px 0 0"><button type="button" data-edit="${esc(a.id)}">Edit</button><button type="button" data-rec="${esc(a.id)}">Check balance</button></div></div>`).join("") || `<div class="fcard">${emptyHtml("No accounts yet.")}</div>`}</div>`;
    root.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => openAccountForm(accs.find((a) => a.id === b.dataset.edit))));
    root.querySelectorAll("[data-rec]").forEach((b) => (b.onclick = () => openReconcile(accs.find((a) => a.id === b.dataset.rec))));
  }

  async function openAccountForm(a) {
    if (!state.meta) state.meta = await api("/meta", undefined, "GET");
    modal(a ? "Edit account" : "Add account", (body) => {
      const f = document.createElement("form");
      f.className = "fin-form";
      f.innerHTML = `<label>Name<input id="afName" maxlength="60" required value="${esc(a ? a.name : "")}" placeholder="e.g. Cash, bKash, City Bank"></label>
        ${a ? "" : `<label>Type<select id="afType">${state.meta.account_types.map((t) => `<option value="${t}">${t.replace("_", " ")}</option>`).join("")}</select></label>`}
        <div class="row2"><label>${a ? "Opening balance" : "Balance today"}<input id="afOpen" inputmode="decimal" value="${esc(a ? a.opening_balance : "0")}"></label><label>As of<input id="afDate" type="date" value="${esc(a ? a.opening_date : todayStr())}"></label></div>
        <p class="muted small">For a credit card or loan, enter what you owe as a positive number. Leave 0 if you do not know yet; balances will then only reflect what you record from now on.</p>
        ${a ? `<label class="check"><input id="afArch" type="checkbox" ${a.archived ? "checked" : ""}> Archived (hidden, history kept)</label>` : ""}
        <div class="fin-err" id="afErr" role="alert" hidden></div><button type="submit" class="primary">${a ? "Save" : "Add account"}</button>`;
      body.appendChild(f);
      f.onsubmit = async (ev) => {
        ev.preventDefault();
        try {
          if (a) await api("/accounts/" + a.id, { name: $("afName").value, opening_balance: $("afOpen").value, opening_date: $("afDate").value, archived: $("afArch").checked });
          else await api("/accounts", { name: $("afName").value, type: $("afType").value, opening_balance: $("afOpen").value, opening_date: $("afDate").value });
          closeModal(); toast(a ? "Account updated" : "Account added"); afterChange();
        } catch (e) { $("afErr").textContent = e.message; $("afErr").hidden = false; }
      };
    });
  }

  function openReconcile(a) {
    modal("Check " + a.name, (body) => {
      body.innerHTML = `<form class="fin-form"><p>The ledger says <b>${money(a.balance)}</b>. Type what the account really holds (from your bank app, wallet or the cash in your hand).</p>
        <label>Actual balance<input id="rcActual" inputmode="decimal" required></label><div class="fin-preview" id="rcOut" hidden></div><div class="fin-err" id="rcErr" role="alert" hidden></div>
        <div class="row2"><button type="submit" class="primary">Compare</button><button type="button" id="rcApply" disabled>Fix with an adjustment</button></div></form>`;
      const f = body.querySelector("form");
      f.onsubmit = async (ev) => {
        ev.preventDefault();
        try {
          const r = await api(`/accounts/${a.id}/reconcile`, { actual: $("rcActual").value, apply: false });
          $("rcOut").hidden = false;
          $("rcOut").textContent = Number(r.difference) === 0 ? "They match. Nothing to fix." : `Difference ${money(r.difference, true)}. An adjustment will make the ledger match; it is not counted as income or spending.`;
          $("rcApply").disabled = Number(r.difference) === 0;
          $("rcErr").hidden = true;
        } catch (e) { $("rcErr").textContent = e.message; $("rcErr").hidden = false; }
      };
      $("rcApply").onclick = async () => { try { await api(`/accounts/${a.id}/reconcile`, { actual: $("rcActual").value, apply: true }); closeModal(); toast("Adjustment recorded"); afterChange(); } catch (e) { $("rcErr").textContent = e.message; $("rcErr").hidden = false; } };
    });
  }

  // ------------------------------------------------------------------------------------------ PLAN: budgets, goals, bills
  async function loadPlan() {
    const root = $("finTab-plan");
    if (!state.meta) state.meta = await api("/meta", undefined, "GET");
    const [budgets, goals, bills] = await Promise.all([api("/budgets", undefined, "GET"), api("/goals", undefined, "GET"), api("/obligations", undefined, "GET")]);
    await refreshAccounts();
    $("finSub").textContent = "Plans are not money moved: only transactions you record change balances and progress.";
    banner("");
    const budget = (b) => `<div class="fcard"><h3>${esc(b.name)} <span class="chip ${esc(b.status)}">${esc(b.status)}</span></h3><div><b>${money(b.spent)}</b> of ${money(b.limit)} · ${esc(b.period)}${b.active ? "" : " (paused)"}</div><div class="bar ${b.status === "over" ? "over" : b.status === "warning" ? "warn" : ""}"><i style="width:${Math.min(100, Math.round(b.utilization * 100))}%"></i></div><p class="muted small">${b.status === "over" ? "Over by " + money(b.over_by) : money(b.remaining) + " left"} · ${b.days_left} days left · ${b.projected_over ? "on pace to exceed it (estimate ≈ " + money(b.projected_total) + ")" : "projected " + money(b.projected_total)}</p><div class="fin-toolbar" style="margin:0"><button type="button" data-bedit="${esc(b.id)}">Edit</button><button type="button" data-bdel="${esc(b.id)}">Delete</button></div></div>`;
    const goal = (g) => `<div class="fcard"><h3>${esc(g.name)} <span class="chip ${g.status === "completed" ? "ok" : g.on_track === false ? "over" : ""}">${esc(g.status)}</span></h3><div><b>${money(g.saved)}</b> of ${money(g.target)} (${Math.round(g.progress_pct * 100)}%)</div><div class="bar"><i style="width:${Math.round(g.progress_pct * 100)}%"></i></div><p class="muted small">${g.reached ? esc(g.note) : g.estimated_completion ? `Estimated ${esc(g.estimated_completion)} (${esc(g.estimate_basis)})` : esc(g.estimate_basis || "")}${g.required_monthly ? ` · needs about ${money(g.required_monthly)} a month for ${esc(g.target_date)}` : ""}${g.monthly_target ? ` · plan ${money(g.monthly_target)} a month` : ""}</p><div class="fin-toolbar" style="margin:0"><button type="button" data-gadd="${esc(g.id)}">Add savings</button><button type="button" data-gedit="${esc(g.id)}">Edit</button><button type="button" data-gdel="${esc(g.id)}">Delete</button></div></div>`;
    const bill = (o) => `<li class="frow"><div class="main"><b>${esc(o.name)}</b><span>${esc(o.recurrence)} · next due ${esc(o.next_due)}${o.last_payment ? " · last paid for " + esc(o.last_payment.due_date) : ""}</span></div><span class="amt">${money(o.amount)} <span class="chip ${esc(o.status)}">${esc(o.status)}</span> ${o.active ? `<button type="button" data-pay="${esc(o.id)}">Pay</button> <button type="button" data-skip="${esc(o.id)}" title="Skip this due date">Skip</button>` : ""} <button type="button" data-oedit="${esc(o.id)}">Edit</button></span></li>`;
    root.innerHTML = `
      <div class="fin-toolbar"><button type="button" class="primary" id="pnB">Add budget</button><button type="button" class="primary" id="pnG">Add goal</button><button type="button" class="primary" id="pnO">Add bill</button></div>
      <h2 class="report-section" style="font:italic 500 22px var(--font-display);margin:6px 0 10px">Budgets</h2>
      <div class="fin-grid fin-cols">${budgets.map(budget).join("") || `<div class="fcard">${emptyHtml("No budgets yet. A budget gives a category a monthly limit and warns you before you pass it.")}</div>`}</div>
      <h2 class="report-section" style="font:italic 500 22px var(--font-display);margin:14px 0 10px">Goals</h2>
      <div class="fin-grid fin-cols">${goals.map(goal).join("") || `<div class="fcard">${emptyHtml("No goals yet.")}</div>`}</div>
      <h2 class="report-section" style="font:italic 500 22px var(--font-display);margin:14px 0 10px">Bills and recurring payments</h2>
      <div class="fcard">${bills.length ? `<ul class="flist">${bills.map(bill).join("")}</ul>` : emptyHtml("No bills yet. Add rent, electricity, tuition or a loan instalment and Pay records the real payment once.")}</div>`;
    $("pnB").onclick = () => budgetForm(); $("pnG").onclick = () => goalForm(); $("pnO").onclick = () => billForm();
    const by = (list, id) => list.find((x) => x.id === id);
    root.querySelectorAll("[data-bedit]").forEach((b) => (b.onclick = () => budgetForm(by(budgets, b.dataset.bedit))));
    root.querySelectorAll("[data-bdel]").forEach((b) => (b.onclick = async () => { if (window.confirm("Delete this budget?")) { await api(`/budgets/${b.dataset.bdel}/delete`, {}); afterChange(); } }));
    root.querySelectorAll("[data-gedit]").forEach((b) => (b.onclick = () => goalForm(by(goals, b.dataset.gedit))));
    root.querySelectorAll("[data-gdel]").forEach((b) => (b.onclick = async () => { if (window.confirm("Delete this goal? Linked transfers stay in your ledger.")) { await api(`/goals/${b.dataset.gdel}/delete`, {}); afterChange(); } }));
    root.querySelectorAll("[data-gadd]").forEach((b) => (b.onclick = () => contributeForm(by(goals, b.dataset.gadd))));
    root.querySelectorAll("[data-pay]").forEach((b) => (b.onclick = () => payForm(by(bills, b.dataset.pay))));
    root.querySelectorAll("[data-skip]").forEach((b) => (b.onclick = async () => { if (window.confirm("Skip this due date without recording a payment?")) { await api(`/obligations/${b.dataset.skip}/skip`, {}); afterChange(); } }));
    root.querySelectorAll("[data-oedit]").forEach((b) => (b.onclick = () => billForm(by(bills, b.dataset.oedit))));
  }

  function simpleForm(title, html, onSubmit, submitLabel) {
    modal(title, (body) => {
      const f = document.createElement("form");
      f.className = "fin-form";
      f.innerHTML = html + `<div class="fin-err" id="sfErr" role="alert" hidden></div><button type="submit" class="primary">${esc(submitLabel || "Save")}</button>`;
      body.appendChild(f);
      f.onsubmit = async (ev) => {
        ev.preventDefault();
        try { await onSubmit(); closeModal(); afterChange(); } catch (e) { $("sfErr").textContent = e.message; $("sfErr").hidden = false; }
      };
    });
  }
  const accSelect = (id, sel, types) => `<select id="${id}">${state.accounts.filter((a) => !types || types.includes(a.type)).map((a) => `<option value="${esc(a.id)}" ${sel === a.id ? "selected" : ""}>${esc(a.name)}</option>`).join("")}</select>`;

  function budgetForm(b) {
    const cats = Object.keys(state.meta.expense_categories);
    simpleForm(b ? "Edit budget" : "Add budget", `
      <label>Name<input id="bfName" maxlength="60" value="${esc(b ? b.name : "")}" placeholder="optional"></label>
      ${b ? "" : `<div class="row2"><label>Category<select id="bfCat"><option value="">All spending</option>${cats.map((c) => `<option>${esc(c)}</option>`).join("")}</select></label><label>Period<select id="bfPer"><option value="monthly">Monthly</option><option value="weekly">Weekly</option><option value="custom">Custom dates</option></select></label></div>
      <div class="row2" id="bfDates" hidden><label>From<input id="bfFrom" type="date"></label><label>To<input id="bfTo" type="date"></label></div>`}
      <div class="row2"><label>Limit<input id="bfLimit" inputmode="decimal" required value="${esc(b ? b.limit : "")}"></label><label>Warn me at (%)<input id="bfAlert" type="number" min="1" max="200" value="${b ? b.alert_pct : 80}"></label></div>
      ${b ? `<label class="check"><input id="bfActive" type="checkbox" ${b.active ? "checked" : ""}> Active</label>` : ""}`,
    async () => {
      if (b) await api("/budgets/" + b.id, { name: $("bfName").value || undefined, limit: $("bfLimit").value, alert_pct: Number($("bfAlert").value), active: $("bfActive").checked });
      else await api("/budgets", { name: $("bfName").value || null, category: $("bfCat").value || null, period: $("bfPer").value, limit: $("bfLimit").value, start_date: $("bfFrom").value || null, end_date: $("bfTo").value || null, alert_pct: Number($("bfAlert").value) });
    });
    if (!b) $("bfPer").onchange = () => ($("bfDates").hidden = $("bfPer").value !== "custom");
  }

  function goalForm(g) {
    simpleForm(g ? "Edit goal" : "Add goal", `
      <label>Goal<input id="gfName" maxlength="80" required value="${esc(g ? g.name : "")}" placeholder="e.g. New laptop, Emergency fund"></label>
      <div class="row2"><label>Target amount<input id="gfTarget" inputmode="decimal" required value="${esc(g ? g.target : "")}"></label><label>Already saved<input id="gfSaved" inputmode="decimal" value="${esc(g ? g.baseline_saved : "0")}"></label></div>
      <div class="row2"><label>Target date<input id="gfDate" type="date" value="${esc(g ? g.target_date || "" : "")}"></label><label>Plan per month<input id="gfMonthly" inputmode="decimal" value="${esc(g && g.monthly_target ? g.monthly_target : "")}" placeholder="optional"></label></div>
      <div class="row2"><label>Priority<select id="gfPrio"><option value="1" ${g && g.priority === 1 ? "selected" : ""}>High</option><option value="2" ${!g || g.priority === 2 ? "selected" : ""}>Medium</option><option value="3" ${g && g.priority === 3 ? "selected" : ""}>Low</option></select></label>
      ${g ? `<label>Status<select id="gfStatus">${["active", "paused", "completed"].map((x) => `<option ${g.status === x ? "selected" : ""}>${x}</option>`).join("")}</select></label>` : `<span></span>`}</div>
      <p class="muted small">The monthly plan is a plan only. Progress counts money you actually move with “Add savings”.</p>`,
    async () => {
      const body = { name: $("gfName").value, target: $("gfTarget").value, saved: $("gfSaved").value || "0", target_date: $("gfDate").value || null, monthly_target: $("gfMonthly").value || null, priority: Number($("gfPrio").value) };
      if (g) { body.status = $("gfStatus").value; await api("/goals/" + g.id, body); } else await api("/goals", body);
    });
  }

  function contributeForm(g) {
    const savings = state.accounts.filter((a) => ["savings", "investment", "bank", "wallet"].includes(a.type));
    simpleForm("Add savings to " + g.name, `
      <p>This records a real transfer between your accounts and links it to the goal. It is not counted as spending.</p>
      <div class="row2"><label>From<select id="cfFrom">${state.accounts.filter((a) => !a.liability).map((a) => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join("")}</select></label><label>To (savings)<select id="cfTo">${savings.map((a) => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join("")}</select></label></div>
      <div class="row2"><label>Amount<input id="cfAmt" inputmode="decimal" required></label><label>Date<input id="cfDate" type="date" value="${todayStr()}"></label></div>`,
    async () => { await api("/transactions", { type: "transfer", account_id: $("cfFrom").value, to_account_id: $("cfTo").value, amount: $("cfAmt").value, ts: $("cfDate").value, goal_id: g.id, note: "Savings for " + g.name, idempotency_key: uuid() }); toast("Savings recorded"); }, "Record transfer");
  }

  function billForm(o) {
    const cats = Object.keys(state.meta.expense_categories);
    simpleForm(o ? "Edit bill" : "Add bill", `
      <label>Name<input id="obName" maxlength="80" required value="${esc(o ? o.name : "")}" placeholder="e.g. Rent, Internet, Tuition"></label>
      <div class="row2"><label>Amount<input id="obAmt" inputmode="decimal" required value="${esc(o ? o.amount : "")}"></label><label>Next due<input id="obDue" type="date" required value="${esc(o ? o.next_due : todayStr())}"></label></div>
      <div class="row2"><label>Repeats<select id="obRec">${["monthly", "weekly", "yearly", "once"].map((x) => `<option ${o && o.recurrence === x ? "selected" : ""}>${x}</option>`).join("")}</select></label><label>Remind me (days before)<input id="obRem" type="number" min="0" max="60" value="${o ? o.reminder_days : 3}"></label></div>
      ${o ? `<label class="check"><input id="obActive" type="checkbox" ${o.active ? "checked" : ""}> Active</label>` : `<div class="row2"><label>Category<select id="obCat">${cats.map((c) => `<option ${c === "utilities" ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></label><label>Usually paid from<select id="obAcc"><option value="">Ask me when paying</option>${state.accounts.filter((a) => !a.liability).map((a) => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join("")}</select></label></div>`}`,
    async () => {
      if (o) await api("/obligations/" + o.id, { name: $("obName").value, amount: $("obAmt").value, next_due: $("obDue").value, recurrence: $("obRec").value, reminder_days: Number($("obRem").value), active: $("obActive").checked });
      else await api("/obligations", { name: $("obName").value, amount: $("obAmt").value, next_due: $("obDue").value, recurrence: $("obRec").value, reminder_days: Number($("obRem").value), category: $("obCat").value, account_id: $("obAcc").value || null });
    });
  }

  function payForm(o) {
    simpleForm("Pay " + o.name, `
      <p>This records one real expense and marks this due date (${esc(o.next_due)}) as paid, so the amount is counted once.</p>
      <div class="row2"><label>From account<select id="pfAcc">${state.accounts.filter((a) => !a.liability || true).map((a) => `<option value="${esc(a.id)}" ${o.account_id === a.id ? "selected" : ""}>${esc(a.name)}</option>`).join("")}</select></label><label>Amount actually paid<input id="pfAmt" inputmode="decimal" value="${esc(o.amount)}"></label></div>
      <label>Paid on<input id="pfDate" type="date" value="${todayStr()}"></label>`,
    async () => { await api(`/obligations/${o.id}/pay`, { account_id: $("pfAcc").value, amount: $("pfAmt").value, ts: $("pfDate").value }); toast("Payment recorded"); }, "Record payment");
  }

  // ------------------------------------------------------------------------------------------ REPORTS
  async function loadReports() {
    const root = $("finTab-reports");
    $("finSub").textContent = "Numbers are calculated from your records. The AI only explains them, and it cannot add figures of its own.";
    banner("");
    const past = await api("/reports", undefined, "GET");
    root.innerHTML = `
      <div class="fcard" style="margin-bottom:14px"><div class="fin-toolbar" style="margin:0">
        <select id="rpLang" aria-label="Report language"><option value="">Language: account default</option><option value="en">English</option><option value="bn">বাংলা</option></select>
        <select id="rpKind" aria-label="Report period"><option value="week">Weekly</option><option value="month" selected>Monthly</option><option value="year">Yearly</option><option value="custom">Custom range</option></select>
        <input id="rpFrom" type="date" aria-label="From" hidden><input id="rpTo" type="date" aria-label="To" hidden>
        <label class="check" style="display:inline-flex;gap:6px;align-items:center;font-size:13.5px"><input id="rpAi" type="checkbox" checked> Explain with AI</label>
        <button type="button" id="rpGo" class="primary">Generate report</button><span class="muted small" id="rpMsg" role="status"></span></div>
        ${past.length ? `<p class="muted small" style="margin:10px 0 4px">Earlier reports</p><div class="fin-toolbar" style="margin:0">${past.slice(0, 6).map((r) => `<button type="button" data-rep="${esc(r.id)}">${esc(r.kind)} ${esc(r.start)}${r.end !== r.start ? " → " + esc(r.end) : ""}</button>`).join("")}</div>` : ""}</div>
      <div id="rpOut">${state.report ? "" : `<div class="fcard">${emptyHtml("Choose a period and generate a report. It covers your balances, spending, savings, bills, behaviour, recommendations and a forecast.")}</div>`}</div>`;
    $("rpKind").onchange = () => { const c = $("rpKind").value === "custom"; $("rpFrom").hidden = !c; $("rpTo").hidden = !c; };
    $("rpGo").onclick = async () => {
      $("rpMsg").textContent = "Building your report…"; $("rpGo").disabled = true;
      try { const k = $("rpKind").value; state.report = await api("/reports", { kind: k, start: k === "custom" ? $("rpFrom").value : null, end: k === "custom" ? $("rpTo").value : null, ai: $("rpAi").checked, lang: $("rpLang").value || null }); $("rpMsg").textContent = ""; drawReport(state.report); }
      catch (e) { $("rpMsg").textContent = e.message; }
      $("rpGo").disabled = false;
    };
    root.querySelectorAll("[data-rep]").forEach((b) => (b.onclick = async () => { state.report = await api("/reports/" + b.dataset.rep, undefined, "GET"); drawReport(state.report); }));
    if (state.report) drawReport(state.report);
  }

  function drawReport(r) {
    const o = r.overview, n = r.narrative, sp = r.spending, sv = r.savings, ob = r.obligations, rec = r.recommendations;
    const mode = n.mode === "ai" ? `AI explanation · ${esc(n.model || "")} · figures checked against your data` : n.mode === "fallback" ? "Built-in explanation (the AI service was unavailable)" : "Built-in explanation";
    const kv = (a) => `<div class="kv">${a.map(([k, v]) => `<div><b>${esc(k)}</b>${v}</div>`).join("")}</div>`;
    $("rpOut").innerHTML = `
      <div class="fcard report-section"><h3>${esc(r.period.label)} <span class="tag">${mode}</span></h3>
        <h2>${esc(n.headline)}</h2><p>${esc(n.summary)}</p>
        <div class="fin-grid">${n.findings.map((f) => `<div class="insight-card"><b>${esc(f.title)}</b><div>${esc(f.what_we_saw)}</div><div class="why">Why it matters: ${esc(f.why_it_matters)}</div><div class="act">→ ${esc(f.suggested_action)}</div>${f.estimated_impact ? `<div class="assume">Estimated impact: ${esc(f.estimated_impact)}. ${esc((f.assumptions || []).join(" "))}</div>` : ""}</div>`).join("")}</div>
        ${n.caveats.length ? `<p class="estimate-note">${esc(n.caveats.join(" "))}</p>` : ""}
        <div class="fin-toolbar" style="margin:10px 0 0"><button type="button" id="rpMd">Download Markdown</button><button type="button" id="rpJson">Download JSON</button><button type="button" id="rpPrint">Print</button></div></div>
      <div class="fcard report-section"><h3>A · Financial overview <span class="tag">actual</span></h3>${kv([["Liquid funds at start", money(o.opening_liquid)], ["Liquid funds at end", money(o.closing_liquid)], ["Change", money(o.change_in_liquid, true)], ["Income", money(o.income)], ["Spending", money(o.spending)], ["Refunds", money(o.refunds)], ["Net cash flow", money(o.net_cash_flow, true)], ["Moved to savings (net)", money(o.savings_net)]])}
        <div class="table-wrap" style="margin-top:12px"><table class="ftable"><thead><tr><th>Account</th><th class="num">Opening</th><th class="num">Closing</th><th class="num">Change</th></tr></thead><tbody>${o.accounts.map((a) => `<tr><td>${esc(a.name)} <span class="muted small">${esc(a.type)} ${esc(a.currency)}</span></td><td class="num">${money(a.opening)}</td><td class="num">${money(a.closing)}</td><td class="num">${money(a.change, true)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">No accounts.</td></tr>`}</tbody></table></div><p class="estimate-note">${esc(o.basis.actual)}</p></div>
      <div class="fcard report-section"><h3>B · Spending analysis</h3>${kv([["Average per day", money(sp.average_daily)], ["Essential", money(sp.essential_split.essential.amount)], ["Discretionary", money(sp.essential_split.discretionary.amount)], ["Unclassified", money(sp.essential_split.unclassified.amount)], ["Recurring", money(sp.recurring_split.recurring.amount)], ["One-time", money(sp.recurring_split.one_time.amount)]])}
        <p style="margin:12px 0 4px"><b>Top categories</b> (change vs previous period)</p><ul class="flist">${sp.by_category.slice(0, 6).map((c) => { const ch = (sp.comparison.categories.find((x) => x.category === c.category) || {}); return `<li class="frow"><div class="main"><b>${esc(c.category)}</b><span>${c.count} transactions · ${pct(c.share)} of spending</span></div><span class="amt">${money(c.amount)} <span class="muted small">${ch.change_pct === null || ch.change_pct === undefined ? "new" : (ch.change_pct >= 0 ? "▲ " : "▼ ") + pct(Math.abs(ch.change_pct))}</span></span></li>`; }).join("") || `<li class="muted">No spending in this period.</li>`}</ul>
        ${sp.subscriptions.length ? `<p style="margin:12px 0 4px"><b>Recurring payments detected</b></p><ul class="flist">${sp.subscriptions.map((s2) => `<li class="frow"><div class="main"><b>${esc(s2.merchant)}</b><span>${s2.occurrences} payments, last ${esc(s2.last)}</span></div><span class="amt">${money(s2.amount)} / month</span></li>`).join("")}</ul>` : ""}</div>
      <div class="fcard report-section"><h3>C · Savings and goals</h3>${kv([["Savings rate (moved to savings)", sv.rate_actual === null ? "—" : pct(sv.rate_actual)], ["Savings rate (income − spending)", sv.rate_implied === null ? "—" : pct(sv.rate_implied)], ["Contributions", money(sv.contributions)], ["Withdrawals", money(sv.withdrawals)], ["Planned monthly for goals", money(sv.planned_monthly_total)]])}
        <p class="estimate-note">Actual = ${esc(sv.definitions.actual)}. Implied = ${esc(sv.definitions.implied)}.</p>${sv.goals.length ? `<ul class="flist">${sv.goals.map((g) => `<li class="frow"><div class="main"><b>${esc(g.name)}</b><span>${money(g.saved)} of ${money(g.target)} · ${g.on_track === true ? "on track" : g.on_track === false ? "behind" : "no deadline"}${g.estimated_completion ? " · est. " + esc(g.estimated_completion) : ""}</span></div><span class="amt">${Math.round(g.progress_pct * 100)}%</span></li>`).join("")}</ul>` : `<p class="muted">No goals yet.</p>`}</div>
      <div class="fcard report-section"><h3>D · Bills and budgets</h3>${kv([["Due in the next 30 days", money(ob.upcoming_total)], ["Overdue", String(ob.overdue.length)], ["Possible shortfall", ob.possible_shortfall ? money(ob.possible_shortfall) : "none expected"]])}<p class="estimate-note">${esc(ob.shortfall_basis)}</p>
        <ul class="flist">${ob.upcoming_30_days.slice(0, 8).map((u) => `<li class="frow"><div class="main"><b>${esc(u.name)}</b><span>due ${esc(u.due)}</span></div><span class="amt">${money(u.amount)} <span class="chip ${esc(u.status)}">${esc(u.status)}</span></span></li>`).join("")}${ob.budgets.map((b) => `<li class="frow"><div class="main"><b>${esc(b.name)}</b><span>${money(b.spent)} of ${money(b.limit)}</span></div><span class="chip ${esc(b.status)}">${esc(b.status)}</span></li>`).join("")}</ul></div>
      <div class="fcard report-section"><h3>E–F · Behaviour and recommendations</h3>${rec.actions.length ? `<div class="fin-grid">${rec.actions.map((a) => `<div class="insight-card"><b>${esc(a.title)}</b><div>${esc(a.pattern)}</div><div class="why">${esc(a.why)}</div><div class="act">→ ${esc(a.action)}</div>${a.estimated_impact ? `<div class="assume">Estimated impact ${money(a.estimated_impact)}. ${esc((a.assumptions || []).join(" "))}</div>` : ""}</div>`).join("")}</div>` : `<p class="muted">No patterns worth flagging yet.</p>`}
        ${rec.suggested_budgets.length ? `<p style="margin:12px 0 4px"><b>Suggested monthly budgets</b> <span class="muted small">${esc(rec.note)}</span></p><ul class="flist">${rec.suggested_budgets.map((s2) => `<li class="frow"><div class="main"><b>${esc(s2.category)}</b><span>${esc(s2.basis)}</span></div><span class="amt">${money(s2.suggested_monthly_limit)} <button type="button" data-mkb="${esc(s2.category)}|${esc(s2.suggested_monthly_limit)}">Create</button></span></li>`).join("")}</ul>` : ""}</div>
      <div class="fcard report-section"><h3>G · Forecast <span class="tag">estimate, not a balance</span></h3>${forecastCard(r.forecast)}${r.scenario ? `<p class="estimate-note"><b>Scenario:</b> cutting ${esc(Object.entries(r.scenario.scenario.reductions_pct).map(([k, v]) => k + " by " + v + "%").join(", "))} would save about ${money(r.scenario.scenario.estimated_saving)} and move the projected month-end to ${money(r.scenario.projected_end_balance)}.</p>` : ""}</div>
      ${r.data_quality.length ? `<div class="fcard report-section"><h3>Data quality</h3><ul class="flist">${r.data_quality.map((q) => `<li class="frow"><span>${esc(q)}</span></li>`).join("")}</ul></div>` : ""}`;
    if (r.lang === "bn") localizeReport($("rpOut"));
    $("rpMd").onclick = () => download(`/api/fin/reports/${r.id}/export?format=md`, `${r.id}.md`);
    $("rpJson").onclick = () => download(`/api/fin/reports/${r.id}/export?format=json`, `${r.id}.json`);
    $("rpPrint").onclick = () => window.print();
    $("rpOut").querySelectorAll("[data-mkb]").forEach((b) => (b.onclick = async () => { const [cat, lim] = b.dataset.mkb.split("|"); try { await api("/budgets", { category: cat, limit: lim, period: "monthly" }); b.disabled = true; b.textContent = "Created"; } catch (e) { b.textContent = e.message; } }));
  }

  // Bangla labels for the fixed parts of a report; the narrative, findings and recommendations already arrive in Bangla from the server
  const BN_LABELS = { "A · Financial overview": "ক · আর্থিক পরিস্থিতি", "B · Spending analysis": "খ · খরচের বিশ্লেষণ", "C · Savings and goals": "গ · সঞ্চয় ও লক্ষ্য",
    "D · Bills and budgets": "ঘ · বিল ও বাজেট", "E–F · Behaviour and recommendations": "ঙ–চ · অভ্যাস ও পরামর্শ", "G · Forecast": "ছ · পূর্বাভাস", "Data quality": "তথ্যের মান",
    "actual": "বাস্তব", "estimate, not a balance": "অনুমান, ব্যালান্স নয়", "estimate": "অনুমান", "Liquid funds at start": "শুরুতে তরল তহবিল", "Liquid funds at end": "শেষে তরল তহবিল",
    "Change": "পরিবর্তন", "Income": "আয়", "Spending": "খরচ", "Refunds": "ফেরত", "Net cash flow": "নিট নগদ প্রবাহ", "Moved to savings (net)": "সঞ্চয়ে গেছে (নিট)",
    "Account": "অ্যাকাউন্ট", "Opening": "শুরু", "Closing": "শেষ", "Average per day": "দিনে গড়", "Essential": "দরকারি", "Discretionary": "ঐচ্ছিক", "Unclassified": "অশ্রেণিবদ্ধ",
    "Recurring": "নিয়মিত", "One-time": "একবারের", "Top categories": "শীর্ষ খাত", "Savings rate (moved to savings)": "সঞ্চয়ের হার (সঞ্চয়ে পাঠানো)",
    "Savings rate (income − spending)": "সঞ্চয়ের হার (আয় − খরচ)", "Contributions": "জমা", "Withdrawals": "তোলা", "Planned monthly for goals": "লক্ষ্যের জন্য মাসিক পরিকল্পনা",
    "Due in the next 30 days": "পরবর্তী ৩০ দিনে প্রদেয়", "Overdue": "বকেয়া", "Possible shortfall": "সম্ভাব্য ঘাটতি", "none expected": "প্রত্যাশিত নয়",
    "Suggested monthly budgets": "প্রস্তাবিত মাসিক বাজেট", "Create": "তৈরি করুন", "Download Markdown": "Markdown নামান", "Download JSON": "JSON নামান", "Print": "প্রিন্ট",
    "Liquid now": "এখন তরল তহবিল", "Bills before month end": "মাস শেষের আগে বিল", "Projected month-end": "মাস শেষে আনুমানিক", "Expected daily spending": "প্রত্যাশিত দৈনিক খরচ" };
  const BN_PREFIX = { "Why it matters: ": "কেন গুরুত্বপূর্ণ: ", "Estimated impact: ": "আনুমানিক প্রভাব: ", "Scenario: ": "পরিস্থিতি: " };
  function localizeReport(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((n) => {
      const raw = n.nodeValue, tr = raw.trim();
      if (BN_LABELS[tr]) { n.nodeValue = raw.replace(tr, BN_LABELS[tr]); return; }
      for (const [en, bnTxt] of Object.entries(BN_PREFIX)) if (tr.startsWith(en)) { n.nodeValue = raw.replace(en, bnTxt); return; }
    });
  }

  // ------------------------------------------------------------------------------------------ ASSISTANT
  const A = { busy: false, pending: null, loaded: false };
  const EXAMPLES = ["I spent 850 taka at the grocery store today on rice, oil and vegetables", "আজ ৮৫০ টাকা বাজার করলাম", "ajk 300 taka rickshaw bhara dilam", "Received 25000 salary today", "How much did I spend on food this month?", "What is my balance?"];

  function addMsg(role, text) {
    const box = $("finMsgs");
    const empty = box.querySelector(".empty-state");
    if (empty) empty.remove();
    const m = el("div", "m " + role, text);
    box.appendChild(m);
    box.scrollTop = box.scrollHeight;
    return m;
  }

  function emptyChat() {
    const box = $("finMsgs");
    box.innerHTML = `<div class="empty-state"><b>Tell me about your money.</b>Say or type what you spent or received, in English, Bangla or Banglish. I will ask only what is missing, show you a summary, and save nothing until you say yes.<div class="fin-quick" style="justify-content:center;margin-top:12px">${EXAMPLES.map((x) => `<button type="button" data-ex="${esc(x)}">${esc(x)}</button>`).join("")}</div></div>`;
    box.querySelectorAll("[data-ex]").forEach((b) => (b.onclick = () => { $("finInput").value = b.dataset.ex; $("finInput").focus(); syncSend(); }));
  }

  function showState(r) {
    const quick = $("finQuick"), conf = $("finConfirm"), draft = $("finDraft");
    quick.innerHTML = ""; conf.hidden = true; draft.hidden = true;
    if (r.awaiting === "confirm") { conf.hidden = false; $("finEdit").hidden = !(r.draft && r.draft.type); }
    else if (r.question && r.question.options && r.question.options.length) {
      r.question.options.slice(0, 8).forEach((o) => { const b = el("button", "", o); b.type = "button"; b.onclick = () => sendMsg(o); quick.appendChild(b); });
    }
    const d = r.draft || {};
    const chips = [["amount", d.amount && money(d.amount)], ["date", d.date], ["merchant", d.merchant], ["category", d.category], ["discount", d.discount && money(d.discount)], ["VAT", d.tax && money(d.tax)]].filter((x) => x[1]);
    if (chips.length && r.state !== "completed" && r.state !== "cancelled" && r.state !== "idle") { draft.hidden = false; draft.innerHTML = chips.map(([k, v]) => `<span class="chip">${esc(k)}: ${esc(v)}</span>`).join(""); }
  }

  function aiLabel(mode) { return mode === "ai" ? "understood by AI (gpt-oss-20b)" : mode === "fallback" ? "AI unavailable: built-in rules used" : mode ? "understood by built-in rules" : ""; }

  function handleReply(r) {
    A.last = r;
    addMsg("bot", r.reply);
    $("finAi").textContent = aiLabel(r.ai);
    showState(r);
    if (r.transaction && r.state === "completed") { toast("Saved to your ledger"); }
    if (window.WGVoice && r.reply) window.WGVoice.speak(r.reply);
  }

  function syncSend() { $("finSend").disabled = A.busy || !$("finInput").value.trim(); }
  function setBusy(b) { A.busy = b; $("finInput").disabled = b; syncSend(); if (!b) $("finInput").focus(); }

  async function sendMsg(textArg, retry) {
    const input = $("finInput");
    const text = (textArg !== undefined ? textArg : input.value).trim();
    if (!text || A.busy) return;
    const source = textArg === undefined && input.dataset.voice === "1" ? "voice" : "text";
    // the same text keeps the same request id until it succeeds, so a retry after a lost response is never applied twice
    const id = A.pending && A.pending.text === text ? A.pending.id : uuid();
    A.pending = { id, text, source };
    if (!retry) addMsg("user", text);
    input.value = ""; input.dataset.voice = ""; input.style.height = "";
    setBusy(true);
    $("finQuick").innerHTML = ""; $("finConfirm").hidden = true;
    try {
      const r = await api("/assistant/chat", { text, request_id: id, source });
      A.pending = null;
      handleReply(r);
      if (r.transaction || r.deleted) { state.dirty = true; }
    } catch (e) {
      const m = addMsg("sys", e.message + (e.status ? "" : " The message was kept: "));
      const b = el("button", "", "Send again");
      b.type = "button"; b.style.marginLeft = "8px";
      b.onclick = () => { m.remove(); sendMsg(A.pending.text, true); };
      m.appendChild(b);
    } finally { setBusy(false); }
  }

  async function loadAssistant() {
    $("finSub").textContent = "Speak or type. Nothing is saved until you confirm the summary.";
    banner("");
    if (!state.accounts.length) { try { await refreshAccounts(); } catch (e) { /* the assistant can still create accounts */ } }
    if (A.loaded) return;
    A.loaded = true;
    const cur = await api("/assistant/session", undefined, "GET");
    $("finMsgs").innerHTML = "";
    if (cur.session_id && cur.messages.length) {
      cur.messages.forEach((m) => addMsg(m.role === "user" ? "user" : "bot", m.text));
      addMsg("sys", "Picked up where you left off.");
      showState(cur);
    } else emptyChat();
  }

  async function editDraft() {
    const r = A.last;
    if (!r || !r.draft) return;
    const d = r.draft, n = r.numbers || {};
    if (!state.meta) state.meta = await api("/meta", undefined, "GET");
    await refreshAccounts();
    txnForm({ _draft: true, id: null, type: d.type || "expense", ts: d.date || todayStr(), final_amount: n.final || d.amount || "", gross_amount: n.gross || "", discount: n.discount || "0.00",
      tax: n.tax || "0.00", service_charge: n.service || "0.00", merchant: d.merchant || "", item_name: d.item_name || "", category: d.category || null, subcategory: d.subcategory || null,
      payment_method: d.payment_method || null, account_id: d.account_id || null, to_account_id: d.to_account_id || null, note: d.note || "", essential: null, recurring: false, tags: [], direction: null });
  }

  function wireAssistant() {
    const input = $("finInput");
    input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 140) + "px"; syncSend(); });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("finForm").requestSubmit(); } });
    $("finForm").onsubmit = (e) => { e.preventDefault(); sendMsg(); };
    $("finYes").onclick = () => sendMsg("yes");
    $("finNo").onclick = () => sendMsg("cancel");
    $("finEdit").onclick = editDraft;
    setInterval(() => { if (state.tab === "assistant") syncSend(); }, 400);            // spoken text arrives without an input event in some browsers
  }

  // ------------------------------------------------------------------------------------------ SETTINGS AND PRIVACY
  async function loadSettings() {
    const root = $("finTab-settings");
    $("finSub").textContent = "How the assistant behaves, what is sent to AI services, and what you can delete.";
    banner("");
    const [st, usage, meta] = await Promise.all([api("/settings", undefined, "GET"), api("/ai-usage", undefined, "GET"), api("/meta", undefined, "GET")]);
    state.meta = meta;
    if (window.WGVoice && window.WGVoice.setSpeak) window.WGVoice.setSpeak(st.voice_replies);
    const accs = state.accounts.length ? state.accounts : await refreshAccounts();
    const row = (title, hint, control) => `<div class="row"><div class="what"><b>${esc(title)}</b><span>${esc(hint)}</span></div>${control}</div>`;
    const act = await api("/activity?limit=25", undefined, "GET").catch(() => null);
    root.innerHTML = `<div class="fin-set">
      <div class="fcard"><h3>AI preferences</h3>
        ${row("Explain reports with AI", "The AI only explains numbers calculated from your records. It cannot add figures, and a built-in explanation is used if it is off or unavailable.", `<label class="check" style="display:flex;gap:8px;align-items:center"><input id="stAi" type="checkbox" ${st.ai_reports ? "checked" : ""}> On</label>`)}
        ${row("Assistant language", "Auto follows the language you write in (English, Bangla or Banglish).", `<select id="stLang" aria-label="Assistant language">${st.options.assistant_lang.map((x) => `<option value="${x}" ${st.assistant_lang === x ? "selected" : ""}>${{ auto: "Automatic", en: "English", bn: "বাংলা (Bangla)" }[x]}</option>`).join("")}</select>`)}
        ${row("Questions about discounts, VAT and service charge", "Automatic asks only when something is unclear. Always asks every time. Never assumes the amount is what you paid.", `<select id="stAdj" aria-label="Ask about discounts">${st.options.ask_adjustments.map((x) => `<option value="${x}" ${st.ask_adjustments === x ? "selected" : ""}>${{ auto: "Automatic", always: "Always ask", never: "Never ask" }[x]}</option>`).join("")}</select>`)}
        ${row("Read assistant replies aloud", "Uses your browser's speech synthesis. Nothing is uploaded for this.", `<label class="check" style="display:flex;gap:8px;align-items:center"><input id="stVoice" type="checkbox" ${st.voice_replies ? "checked" : ""}> On</label>`)}
        ${row("Main currency", accs.length ? "Fixed once you have added accounts, so balances are never mislabelled." : "All totals are shown in this currency.", `<input id="stCur" maxlength="3" value="${esc(st.base_currency)}" style="width:90px" ${accs.length ? "disabled" : ""} aria-label="Main currency">`)}
        <p class="muted small" id="stMsg" role="status"></p></div>
      <div class="fcard"><h3>AI status and use <span class="tag">${meta.ai.enabled ? "on" : "off"}</span></h3>
        <p>${meta.ai.enabled ? `Language understanding and report explanations use <b>${esc(meta.ai.model)}</b> through Groq. The key stays on the server.` : "No AI key is configured, so the built-in rules understand your messages and explain your reports. Everything still works."}</p>
        <div class="kv"><div><b>Calls (30 days)</b>${usage.calls}</div><div><b>Tokens</b>${(usage.prompt_tokens + usage.completion_tokens).toLocaleString("en-US")}</div><div><b>Estimated cost</b>$${Number(usage.est_cost_usd).toFixed(4)}</div><div><b>Failed calls</b>${usage.failed_calls}</div></div>
        <p class="estimate-note">${esc(usage.note)}</p></div>
      <div class="fcard"><h3>What is sent where</h3>
        <ul class="flist"><li class="frow"><span>Messages to the assistant: your words, your account names and the draft being discussed go to the AI service. Card, account and phone numbers (10+ digits) are hidden first. Balances and other transactions are never sent.</span></li>
        <li class="frow"><span>Report explanations: summary figures only (totals, categories, goals), never individual transactions.</span></li>
        <li class="frow"><span>Voice: with the Whisper engine your recording goes to the transcription service; with the browser engine your browser vendor may process it. You always see and can edit the text before sending.</span></li>
        <li class="frow"><span>Guidance only: recommendations are informational, not professional financial advice, and nothing here guarantees a result.</span></li></ul></div>
      <div class="fcard"><h3>My activity <span class="tag">${act && act.chain.valid ? "log verified" : "check failed"}</span></h3>
        <p class="estimate-note">Changes to your money are written to a tamper-evident log (ids and amounts only, never names or notes). ${act ? act.chain.checked + " entries checked." : ""}</p>
        ${act && act.entries.length ? `<ul class="flist">${act.entries.slice(0, 12).map((e) => `<li class="frow"><div class="main"><b>${esc(e.action.replace(/^fin_/, "").replace(/_/g, " "))}</b><span>${esc(e.ts.replace("T", " ").slice(0, 16))} UTC${e.detail.final_minor ? " · " + money(fromMinor(e.detail.final_minor)) : ""}</span></div></li>`).join("")}</ul>` : `<p class="empty">Nothing recorded yet.</p>`}</div>
      <div class="fcard"><h3>Your data</h3>
        ${row("Keep assistant conversations for (days)", "Older finished conversations are removed automatically. Your transactions are not affected.", `<input id="stDays" type="number" min="${st.options.history_days[0]}" max="${st.options.history_days[1]}" value="${st.history_days}" aria-label="Days to keep conversations">`)}
        ${row("Download my transactions", "A CSV file you can open in a spreadsheet or import again.", `<button type="button" id="stDl">Download CSV</button>`)}
        ${row("Clear assistant history", "Deletes conversations and retry records. Your ledger stays.", `<button type="button" id="stClear">Clear history</button>`)}
        <div class="row"><div class="what"><b>Notify me on this device</b><span id="stNotifyHint">Shows a notification when a bill is due or a budget is nearly used up. It only works while WealthGuard is open in a browser tab; nothing is sent from a server.</span></div><label class="check" style="display:flex;gap:8px;align-items:center"><input id="stNotify" type="checkbox" ${notifyOn() ? "checked" : ""}> On</label></div>
        <div class="row danger"><div class="what"><b>Erase all my finance data</b><span>Deletes accounts, transactions, budgets, goals, bills, reports and conversations. This cannot be undone.</span></div><button type="button" class="warn" id="stErase">Erase everything…</button></div></div></div>`;
    const save = async (patch) => {
      try { const out = await api("/settings", patch); $("stMsg").textContent = "Saved."; if (window.WGVoice && window.WGVoice.setSpeak) window.WGVoice.setSpeak(out.voice_replies); }
      catch (e) { $("stMsg").textContent = e.message; }
    };
    $("stAi").onchange = () => save({ ai_reports: $("stAi").checked });
    $("stLang").onchange = () => save({ assistant_lang: $("stLang").value });
    $("stAdj").onchange = () => save({ ask_adjustments: $("stAdj").value });
    $("stVoice").onchange = () => save({ voice_replies: $("stVoice").checked });
    $("stCur").onchange = () => save({ base_currency: $("stCur").value });
    $("stDays").onchange = () => save({ history_days: Number($("stDays").value) });
    $("stDl").onclick = () => download("/api/fin/export/transactions.csv", "transactions.csv");
    $("stNotify").onchange = async () => {
      if ($("stNotify").checked) {
        if (!("Notification" in window)) { $("stNotifyHint").textContent = "This browser does not support notifications."; $("stNotify").checked = false; return; }
        const perm = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
        if (perm !== "granted") { $("stNotifyHint").textContent = "Permission was not given, so notifications stay off. You can allow them in the browser's site settings."; $("stNotify").checked = false; return; }
      }
      try { localStorage.setItem("wg-notify", $("stNotify").checked ? "1" : "0"); } catch (e) { /* ignore */ }
      if ($("stNotify").checked) checkReminders(true);
    };
    $("stClear").onclick = async () => { if (!window.confirm("Delete all assistant conversations? Your transactions stay.")) return; const r = await api("/privacy/clear-history", {}); A.loaded = false; $("stMsg").textContent = `Removed ${r.conversations_removed} conversations.`; };
    $("stErase").onclick = () => simpleForm("Erase all finance data", `
      <p>This permanently deletes everything you have recorded in My money. Download a CSV first if you may want it later.</p>
      <label>Type <b>DELETE MY FINANCE DATA</b> to confirm<input id="erPhrase" autocomplete="off" required></label>`,
    async () => { await api("/privacy/erase", { confirm: $("erPhrase").value }); state.accounts = []; state.meta = null; A.loaded = false; toast("All finance data erased"); }, "Erase everything");
  }

  // ------------------------------------------------------------------------------------------ reminders
  const notifyOn = () => { try { return localStorage.getItem("wg-notify") === "1" && "Notification" in window && Notification.permission === "granted"; } catch (e) { return false; } };
  function seenKeys() { try { return new Set(JSON.parse(localStorage.getItem("wg-seen") || "[]")); } catch (e) { return new Set(); } }
  async function checkReminders(force) {
    let alerts;
    try { alerts = await api("/alerts", undefined, "GET"); } catch (e) { return; }
    const urgent = alerts.filter((a) => a.severity !== "low");
    const badge = $("modeBadge");
    badge.hidden = !urgent.length;
    badge.textContent = String(urgent.length);
    badge.title = urgent.map((a) => a.title).join("; ");
    const planNav = document.querySelector('.nav[data-tab="plan"] .dot');
    if (planNav) planNav.classList.toggle("on", urgent.length > 0);
    if (!notifyOn()) return;
    const seen = seenKeys();
    const fresh = urgent.filter((a) => !seen.has(a.key));
    fresh.slice(0, 3).forEach((a) => { try { new Notification(a.title, { body: a.body, tag: a.key }); } catch (e) { /* the browser refused */ } });
    if (fresh.length) { try { localStorage.setItem("wg-seen", JSON.stringify([...seen, ...fresh.map((a) => a.key)].slice(-200))); } catch (e) { /* ignore */ } }
  }

  // ------------------------------------------------------------------------------------------ mode, wiring
  function setMode(mode) {
    const money_ = mode === "money";
    document.body.classList.toggle("mode-money", money_);
    $("moneyView").hidden = !money_;
    $("modeAdvisor").setAttribute("aria-selected", String(!money_));
    $("modeMoney").setAttribute("aria-selected", String(money_));
    try { localStorage.setItem("wg-mode", mode); } catch (e) { /* ignore */ }
    if (window.WGUI && window.WGUI.closePanel) window.WGUI.closePanel();
    if (money_) { if (!state.mounted) { state.mounted = true; mount(); } showTab(state.tab); }
  }

  async function mount() {
    try { state.meta = await api("/meta", undefined, "GET"); state.currency = state.meta.currency; } catch (e) { fail(e); return; }
    try { const st = await api("/settings", undefined, "GET"); if (window.WGVoice && window.WGVoice.setSpeak) window.WGVoice.setSpeak(st.voice_replies); } catch (e) { /* preferences are optional */ }
  }

  function init(u) {
    me = u;
    if (u.role === "admin" || (u.permissions && u.permissions.money === false)) return;
    $("modeSwitch").hidden = false;
    $("modeAdvisor").onclick = () => setMode("advisor");
    $("modeMoney").onclick = () => setMode("money");
    document.querySelectorAll(".nav[data-tab], .fin-tabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
    $("finPeriod").onchange = () => { state.period = $("finPeriod").value; $("finCustom").hidden = state.period !== "custom"; if (state.period !== "custom") showTab(state.tab); };
    $("finFrom").onchange = $("finTo").onchange = () => { if ($("finFrom").value && $("finTo").value) showTab(state.tab); };
    $("finAdd").onclick = () => {
      if (state.tab === "accounts") return openAccountForm();
      if (state.tab === "plan") return modal("Add…", (b) => { [["Budget", () => budgetForm()], ["Goal", () => goalForm()], ["Bill", () => billForm()]].forEach(([l, f]) => { const x = el("button", "wide", l); x.type = "button"; x.style.marginBottom = "8px"; x.onclick = () => { closeModal(); f(); }; b.appendChild(x); }); });
      return openTxn(null);
    };
    $("finModalClose").onclick = closeModal;
    $("finModal").addEventListener("click", (e) => { if (e.target === $("finModal")) closeModal(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("finModal").hidden) closeModal(); });
    wireAssistant();
    checkReminders(false);
    setInterval(() => { if (!document.hidden) checkReminders(false); }, 5 * 60 * 1000);
    let saved = "advisor";
    try { saved = localStorage.getItem("wg-mode") || "advisor"; } catch (e) { /* ignore */ }
    if (saved === "money") setMode("money");
  }

  if (window.WGAuth) window.WGAuth.onReady(init);
  window.WGFinance = { toMinor, fromMinor, money, setMode, checkReminders };
})();
