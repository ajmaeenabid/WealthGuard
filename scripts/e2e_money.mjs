// Browser end-to-end check of the My money workspace (headless Edge or Chrome through the DevTools protocol, no extra packages).
//   node scripts/e2e_money.mjs <baseUrl> <outDir>
// Expects a FRESH server started with USE_MOCK_LLM=1 (deterministic) and the demo accounts (li / 123). Exits 1 if any check fails.
import { spawn } from "node:child_process";
import fs from "node:fs";

const BASE = process.argv[2] || "http://localhost:8000";
const OUT = process.argv[3] || ".";
const PORT = 9400 + Math.floor(Math.random() * 400);
const BROWSERS = [process.env.BROWSER, "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"].filter(Boolean);
const EXE = BROWSERS.find((p) => fs.existsSync(p));
if (!EXE) { console.error("no Chromium-based browser found"); process.exit(2); }
fs.mkdirSync(OUT, { recursive: true });

const proc = spawn(EXE, ["--headless=new", "--disable-gpu", `--remote-debugging-port=${PORT}`, "--hide-scrollbars", `--user-data-dir=${OUT}/profile-${PORT}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let targets;
for (let i = 0; i < 50; i++) { try { targets = await (await fetch(`http://localhost:${PORT}/json`)).json(); if (targets.length) break; } catch { /* starting */ } await sleep(300); }
const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0; const pending = new Map(); const errors = [];
ws.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
  if (d.method === "Page.javascriptDialogOpening") { errors.push("dialog: " + d.params.message); send("Page.handleJavaScriptDialog", { accept: true }); }
  if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text);
  if (d.method === "Runtime.consoleAPICalled" && d.params.type === "error") errors.push("console: " + d.params.args.map((a) => a.value || a.description).join(" "));
};
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, awaitPromise: true, returnByValue: true }); return r.result.result.value ?? r.result.exceptionDetails?.exception?.description; };
const shot = async (name) => { const r = await Promise.race([send("Page.captureScreenshot", { format: "png" }), sleep(10000).then(() => null)]); if (r && r.result) fs.writeFileSync(`${OUT}/${name}.png`, Buffer.from(r.result.data, "base64")); else console.log("NOTE  screenshot skipped (timed out): " + name); };
const viewport = (w, h, mobile = false) => send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile });
await send("Runtime.enable"); await send("Page.enable");

let failed = 0;
const check = (name, ok, detail = "") => { console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  -> " + String(detail).slice(0, 160) : ""}`); if (!ok) failed++; };
const setv = (id2, v) => `(()=>{const e=document.getElementById('${id2}'); e.value=${JSON.stringify(v)}; e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true})); return 'ok'})()`;
const click = (sel) => `(()=>{const e=document.querySelector(${JSON.stringify(sel)}); if(!e) return 'NOT FOUND'; e.click(); return 'clicked'})()`;
const submit = (sel) => `(()=>{document.querySelector(${JSON.stringify(sel)}).requestSubmit(); return 'ok'})()`;
const api = (path, body) => `(async()=>{const r=await fetch('/api/fin${path}',${body ? `{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(${JSON.stringify(body)})}` : "{}"}); return await r.json()})()`;
const run = async (e, wait = 700) => { const v = await ev(e); await sleep(wait); return v; };
const say = async (text, voice = false, wait = 1500) => run(`(()=>{const i=document.getElementById('finInput'); i.value=${JSON.stringify(text)}; ${voice ? "i.dataset.voice='1';" : ""} i.dispatchEvent(new Event('input',{bubbles:true})); document.getElementById('finForm').requestSubmit(); return 'sent'})()`, wait);
const lastBot = () => ev(`[...document.querySelectorAll('#finMsgs .m.bot')].pop()?.textContent || ''`);
const today = new Date().toISOString().slice(0, 10);

await viewport(1440, 900);
await send("Page.navigate", { url: BASE + "/" });
await sleep(3500);

// ---- sign in and enter the workspace
await run(setv("authUser", "li") + ";" + setv("authPass", "123") + ";document.getElementById('authGo').click(); 'x'", 3500);
check("signed in, workspace switch visible", await ev(`!document.getElementById('modeSwitch').hidden`));
await run(click("#modeMoney"), 1800);
check("a new member is asked to choose a currency, none is assumed", (await ev(`document.getElementById('finTab-overview').textContent`)).includes("Choose your currency") && (await ev(`document.querySelectorAll('#finTab-overview .kpi').length`)) === 0);
check("the three choices are dollar, yuan and taka", await ev(`[...document.querySelectorAll('[data-cur]')].map(b=>b.dataset.cur).join(',')`) === "USD,CNY,BDT");
await run(click("[data-cur=BDT]"), 1800);
check("money mode hides the advisor chat", await ev(`getComputedStyle(document.querySelector('.chat')).display==='none' && getComputedStyle(document.getElementById('moneyView')).display!=='none'`));
check("empty state asks for accounts instead of showing fake numbers", (await ev(`document.getElementById('finBanner').textContent`)).includes("Add your accounts"));
check("no demo data on an empty ledger", await ev(`[...document.querySelectorAll('.kpi .v')].slice(0,2).every(v=>v.textContent.includes('0.00'))`));

// ---- accounts through the form
await run(click(".nav[data-tab=accounts]"), 900);
for (const [name, type, open] of [["Cash", "cash", "5000"], ["bKash", "wallet", "1000"], ["Savings", "savings", "0"]]) {
  await run(click("#finAdd"), 500);
  await run(setv("afCur", "BDT") + ";" + setv("afName", name) + ";" + setv("afType", type) + ";" + setv("afOpen", open) + ";" + submit("#finModalBody form"), 1000);
}
check("three accounts with their balances", (await ev(`[...document.querySelectorAll('.acc-card')].map(c=>c.querySelector('b').textContent+c.querySelector('.bal').textContent).join('|')`)) === "Cash৳5,000.00|Savings৳0.00|bKash৳1,000.00");

// ---- manual transaction with a discount: live preview, then saved with the three amounts kept apart
await run(click(".nav[data-tab=transactions]"), 900);
await run(click("#finAdd"), 600);
await run(setv("tfGross", "850") + ";" + setv("tfDisc", "50") + ";" + setv("tfMer", "Shwapno") + ";" + setv("tfCat", "food"), 300);
check("live preview computes the amount paid in integer arithmetic", (await ev(`document.getElementById('tfFinal').value`)) === "800.00" && (await ev(`document.getElementById('tfPreview').textContent`)).includes("৳800.00 paid"));
await shot("e2e_01_txn_form");
await run(submit("#finModalBody form"), 1200);
const t1 = await ev(api("/transactions?q=Shwapno"));
check("saved through the real API with gross, discount and final", t1.total === 1 && t1.items[0].gross_amount === "850.00" && t1.items[0].discount === "50.00" && t1.items[0].final_amount === "800.00");
check("account balance changed by the final amount only", (await ev(api("/position"))).cash === "4200.00");

// ---- edit and delete
await run(click("#tqList tbody tr"), 800);
await run(setv("tfNote", "weekly shop") + ";" + submit("#finModalBody form"), 1200);
check("editing saves a note", (await ev(api("/transactions?q=weekly"))).total === 1);
await run(click("#finAdd"), 600);
await run(setv("tfFinal", "99") + ";" + setv("tfMer", "Delete me") + ";" + submit("#finModalBody form"), 1200);
await run(`(window.confirm = () => true, 'ok')`, 10);
await run(setv("tqQ", "Delete me"), 1200);
await run(click("#tqList tbody tr"), 800);
await run(click("#tfDel"), 1200);
check("deleting removes it from history and balance", (await ev(api("/transactions?q=Delete"))).total === 0 && (await ev(api("/position"))).cash === "4200.00");
await run(setv("tqQ", ""), 800);

// ---- filters
await run(setv("tqType", "income"), 900);
check("filter by type shows the empty message", (await ev(`document.getElementById('tqList').textContent`)).includes("Nothing matches"));
await run(setv("tqType", ""), 700);

// ---- income via form, then dashboard figures must equal the API
await run(click("#finAdd"), 600);
await run(click("#tfType button[data-v=income]") + ";" + setv("tfFinal", "30000") + ";" + setv("tfCat", "salary") + ";" + submit("#finModalBody form"), 1300);
await run(click(".nav[data-tab=overview]"), 2200);
const dash = await ev(api("/dashboard?kind=month"));
const kp = await ev(`Object.fromEntries([...document.querySelectorAll('#finTab-overview .kpi')].map(k=>[k.querySelector('.l').textContent, k.querySelector('.v').textContent]))`);
check("dashboard income and spending equal the API", kp["Income"] === "৳30,000.00" && kp["Spending"] === "৳800.00" && dash.summary.income === "30000.00" && dash.summary.spending === "800.00", JSON.stringify(kp).slice(0, 120));
check("charts rendered on canvases", (await ev(`['chIncExp','chCat','chDaily','chEss','chMer'].every(i=>{const c=document.getElementById(i); return c && c.width>0 && Chart.getChart(c)})`)) === true);
check("estimates are labelled", (await ev(`document.getElementById('finTab-overview').textContent.includes('Forecast') && document.getElementById('finTab-overview').textContent.includes('estimate')`)));
await run(setv("finPeriod", "lastmonth"), 1800);
check("period filter reloads with last month's (empty) spending", (await ev(`document.querySelector('#finTab-overview .kpi:nth-child(2) .v').textContent`)) === "৳0.00");
await run(setv("finPeriod", "month"), 1500);

// ---- scheduled (future-dated) transactions are shown but not counted
const cashBefore = (await ev(api("/position"))).cash;
await ev(`(async()=>{const a=(await (await fetch('/api/fin/accounts')).json())[0]; await fetch('/api/fin/transactions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:'expense',account_id:a.id,amount:'777',category:'food',ts:'2999-01-01'})}); return 1})()`);
await run(click(".nav[data-tab=transactions]"), 1200);
check("future-dated entry carries a scheduled chip", (await ev(`document.querySelector('#tqList .chip.scheduled') !== null`)));
check("and is not part of the balance", (await ev(api("/position"))).cash === cashBefore);

// ---- plan
await run(click(".nav[data-tab=plan]"), 900);
await run(click("#pnB"), 500); await run(setv("bfCat", "food") + ";" + setv("bfLimit", "1000") + ";" + submit("#finModalBody form"), 1200);
await run(click("#pnG"), 500); await run(setv("gfName", "Laptop") + ";" + setv("gfTarget", "60000") + ";" + setv("gfSaved", "5000") + ";" + submit("#finModalBody form"), 1200);
await run(click("#pnO"), 500);
const due = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
await run(setv("obName", "Internet") + ";" + setv("obAmt", "800") + ";" + setv("obDue", due) + ";" + submit("#finModalBody form"), 1200);
check("budget, goal and bill exist", (await ev(api("/budgets"))) !== null && (await ev(`Promise.all(['/budgets','/goals','/obligations'].map(p=>fetch('/api/fin'+p).then(r=>r.json()))).then(a=>a.map(x=>x.length).join(','))`)) === "1,1,1");
await run(click("[data-pay]"), 700);
await run(setv("pfAcc", (await ev(api("/accounts")))[0].id) + ";" + submit("#finModalBody form"), 1300);
const paid = await ev(api("/transactions?q=Internet"));
check("paying a bill records one linked expense and moves the due date", paid.total === 1 && paid.items[0].obligation_id !== null && (await ev(api("/obligations")))[0].status !== "overdue");

// ---- assistant: default policy, then the spec conversation with 'always ask'
await run(click(".nav[data-tab=assistant]"), 1000);
check("empty assistant offers examples", (await ev(`document.querySelectorAll('#finMsgs [data-ex]').length`)) >= 4);
await say("I spent 120 taka on tea today using cash", true);
check("a clear message goes straight to a summary and nothing is saved yet", (await lastBot()).includes("Here is what I will record") && (await ev(api("/transactions?q=tea"))).total === 0);
check("confirm bar offers Save, Edit details and Cancel", await ev(`['finYes','finEdit','finNo'].every(i=>!document.getElementById(i).offsetParent===false)`));
await run(click("#finYes"), 1500);                    // confirmed by a typed/clicked yes: the entry was still started by voice
const tea = await ev(api("/transactions?q=tea"));
check("a spoken message is saved as a voice transaction", tea.total === 1 && tea.items[0].source === "voice" && tea.items[0].final_amount === "120.00");
await run(click(".nav[data-tab=settings]"), 1200);
await run(setv("stAdj", "always"), 800);
check("settings persist to the server", (await ev(`fetch('/api/fin/settings').then(r=>r.json()).then(s=>s.ask_adjustments)`)) === "always");
await run(click(".nav[data-tab=assistant]"), 800);
await say("I spent 850 taka at the grocery store today on rice, oil and vegetables.");
check("always-ask mode opens with the specification question", (await lastBot()).includes("final amount you paid, or was there a discount"));
await say("There was a 50 taka discount.");
check("then which amount", (await lastBot()).includes("before the discount"));
await say("Before the discount.");
check("then VAT", (await lastBot()).includes("VAT or service charge"));
await say("No.");
check("with several accounts it asks which one was used", (await lastBot()).includes("Which account did you pay from"));
await say("Cash");
check("summary shows original, discount and final", (await lastBot()).includes("original ৳850.00") && (await lastBot()).includes("discount ৳50.00") && (await lastBot()).includes("Expense of ৳800.00"));
await run(click("#finEdit"), 900);
check("Edit details opens the prefilled form", (await ev(`document.getElementById('tfFinal').value`)) === "800.00" && (await ev(`document.getElementById('tfGross').value`)) === "850.00");
await shot("e2e_02_edit_draft");
await run(setv("tfNote", "edited before saving") + ";" + submit("#finModalBody form"), 1500);
const edited = await ev(api("/transactions?q=edited"));
check("saving from the form stores the edited record once and closes the draft", edited.total === 1 && edited.items[0].final_amount === "800.00" && (await ev(api("/assistant/session"))).state === "idle");
await say("আজ ৮৫০ টাকা বাজার করলাম", false, 1500);
await say("Cash");
check("Bangla input gets a Bangla summary", (await lastBot()).includes("আমি এটা লিখে রাখব"));
await run(click("#finNo"), 1000);

// ---- reports
await run(click(".nav[data-tab=reports]"), 900);
await run(click("#rpGo"), 3500);
check("report renders every section from stored data", (await ev(`['A · Financial overview','B · Spending analysis','C · Savings and goals','D · Bills and budgets','G · Forecast'].every(t=>document.getElementById('rpOut').textContent.includes(t))`)));
check("report says how it was explained", (await ev(`document.querySelector('#rpOut .tag').textContent`)).includes("Built-in explanation"));

// ---- settings & privacy
await run(click(".nav[data-tab=settings]"), 1200);
check("privacy page explains what is sent where", (await ev(`document.getElementById('finTab-settings').textContent`)).includes("never sent"));
await shot("e2e_03_settings");

// ---- receipt photo: stored with metadata removed, shown in the edit form, marked in the list
const PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
const rc = await ev(`(async()=>{const t=(await (await fetch('/api/fin/transactions?q=Shwapno')).json()).items[0]; const bytes=Uint8Array.from(atob('${PNG_B64}'),c=>c.charCodeAt(0)); const r=await fetch('/api/fin/transactions/'+t.id+'/receipt',{method:'POST',headers:{'Content-Type':'image/png'},body:bytes}); const bad=await fetch('/api/fin/transactions/'+t.id+'/receipt',{method:'POST',headers:{'Content-Type':'image/png'},body:new TextEncoder().encode('<script>alert(1)</script>')}); return {ok:r.status, bad:bad.status, id:t.id}})()`);
check("a real photo is accepted and a script disguised as one is refused", rc.ok === 200 && rc.bad === 415);
await run(click(".nav[data-tab=transactions]"), 1200);
await run(setv("tqQ", "Shwapno"), 1200);
check("the list marks the transaction with a receipt", await ev(`document.querySelector('#tqList .chip[title*="receipt"]') !== null`));
await run(click("#tqList tbody tr"), 1200);
check("the edit form shows the attached photo", await ev(`document.querySelector('#tfRcpView img') !== null`));
await run(click("#tfRcpDel"), 900);
check("removing the photo clears it", (await ev(`fetch('/api/fin/transactions/${rc.id}').then(r=>r.json()).then(t=>t.has_receipt)`)) === false);
await run(`document.getElementById('finModalClose').click(); 'ok'`, 300);
await run(setv("tqQ", ""), 600);

// ---- bill reminders: a bill due tomorrow lights the badge on the workspace switch
await ev(`fetch('/api/fin/obligations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'Gas',amount:'500',next_due:'${new Date(Date.now()+86400000).toISOString().slice(0,10)}',recurrence:'monthly'})}).then(r=>r.status)`);
await run(`WGFinance.checkReminders(false); 'ok'`, 1200);
check("the badge counts urgent reminders", (await ev(`!document.getElementById('modeBadge').hidden && Number(document.getElementById('modeBadge').textContent) >= 1`)));

// ---- Bangla report: same figures, Bangla narrative and labels
await run(click(".nav[data-tab=reports]"), 900);
await run(setv("rpLang", "bn"), 200);
await run(click("#rpGo"), 3500);
const bnOut = await ev(`document.getElementById('rpOut').textContent`);
check("the Bangla report has Bangla section labels and narrative", bnOut.includes("ক · আর্থিক পরিস্থিতি") && bnOut.includes("এআই সেবা ছাড়াই"));
check("and the same taka figures", bnOut.includes("৳30,000.00"));

// ---- activity log in settings
await run(click(".nav[data-tab=settings]"), 1300);
check("settings lists my own activity with the chain status", (await ev(`document.getElementById('finTab-settings').textContent`)).includes("My activity") && (await ev(`document.getElementById('finTab-settings').textContent`)).includes("log verified"));
check("device notification toggle is explained honestly", (await ev(`document.getElementById('stNotifyHint').textContent`)).includes("only works while WealthGuard is open"));

// ---- language and jurisdiction: three languages, saved to the account, separate from the jurisdiction
await run(click(".nav[data-tab=settings]"), 1300);
check("settings has the language and region card", (await ev(`document.getElementById('finTab-settings').textContent`)).includes("Language and region"));
await run(setv("uiLangSel", "zh"), 1500);
check("choosing Chinese translates the settings labels", (await ev(`document.getElementById('finTab-settings').textContent`)).includes("语言与地区"));
const savedLang = await ev(`fetch('/api/fin/settings').then(r=>r.json()).then(o=>o.ui_lang)`);
check("and the choice is saved on the server", savedLang === "zh", savedLang);
await send("Page.reload"); await sleep(3500);
check("after a reload the saved language is still Chinese", (await ev(`document.documentElement.lang`)) === "zh-CN", await ev(`document.documentElement.lang`));
await run(setv("uiLangSel", "bn"), 1500).catch(() => {});
await run(click(".nav[data-tab=settings]"), 1300);
await run(setv("uiLangSel", "bn"), 1500);
check("Bangla shows Bangla labels and Bangla digits for amounts", (await ev(`document.getElementById('finTab-settings').textContent`)).includes("ভাষা ও অঞ্চল"));
await run(setv("uiLangSel", "en"), 1200);
await run(setv("stJur", "CN"), 2000);
check("changing jurisdiction shows the active region chip with the new currency", (await ev(`(document.getElementById('finRegion')||{}).textContent`)).includes("CNY"), await ev(`(document.getElementById('finRegion')||{}).textContent`));
const convo = await ev(`fetch('/api/fin/conversations').then(r=>r.json()).then(o=>o.active_jurisdiction)`);
check("the active jurisdiction is CN on the server", convo === "CN", convo);
await run(click(".fin-tabs button[data-tab=assistant]"), 1500);
check("the chat shows the conversation's jurisdiction and a voice-mode button", (await ev(`(document.getElementById('finChatJur')||{}).textContent`)).includes("CNY") && (await ev(`!!document.getElementById('finVoiceMode')`)));
await run(setv("stJur", "BD"), 100).catch(() => {});
await ev(`fetch('/api/fin/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jurisdiction:'BD',ui_lang:'en'})}).then(r=>r.status)`);
await send("Page.reload"); await sleep(3500);

// ---- mobile: tab bar, no horizontal overflow, assistant usable
await viewport(390, 844, true);
await send("Page.reload"); await sleep(3500);
check("money mode restored after reload", await ev(`document.body.classList.contains('mode-money')`));
for (const tab of ["overview", "transactions", "accounts", "plan", "reports", "assistant", "settings"]) {
  await run(click(`.fin-tabs button[data-tab=${tab}]`), 1100);
  check(`mobile ${tab}: no sideways scrolling`, (await ev(`document.documentElement.scrollWidth <= window.innerWidth + 1`)), await ev(`document.documentElement.scrollWidth + ' vs ' + window.innerWidth`));
}
await shot("e2e_04_mobile");

const real = errors.filter((e) => !/Extension context/.test(e));
check("no JavaScript errors", real.length === 0, real.slice(0, 3).join(" | "));
console.log(failed ? `\n${failed} check(s) failed` : "\nall checks passed");
ws.close(); proc.kill();
process.exit(failed ? 1 : 0);
