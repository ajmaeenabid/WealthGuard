import { spawn } from "node:child_process";
import fs from "node:fs";

const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const OUT = process.argv[2];
const PORT = process.argv[3] || "8771";
const proc = spawn(EDGE, ["--headless=new", "--disable-gpu", "--remote-debugging-port=9353", "--hide-scrollbars",
  "--user-data-dir=" + OUT + "/profile13", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let targets;
for (let i = 0; i < 40; i++) { try { targets = await (await fetch("http://localhost:9353/json")).json(); if (targets.length) break; } catch {} await sleep(300); }
const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0; const pending = new Map(); const errors = [];
ws.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
  if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text);
  if (d.method === "Runtime.consoleAPICalled" && d.params.type === "error") errors.push("console: " + d.params.args.map((a) => a.value || a.description).join(" "));
};
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, awaitPromise: true, returnByValue: true }); return r.result.result.value ?? r.result.exceptionDetails?.exception?.description; };
const viewport = (w, h, mobile = false) => send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile });
const shot = async (name) => { const r = await send("Page.captureScreenshot", { format: "png" }); fs.writeFileSync(`${OUT}/${name}.png`, Buffer.from(r.result.data, "base64")); };
await send("Runtime.enable"); await send("Page.enable");
await viewport(1440, 900);
await send("Page.navigate", { url: `http://localhost:${PORT}/` });
await sleep(3500);
const log = [];
const step = async (n, e, w = 900) => { const v = await ev(e); await sleep(w); log.push([n, v]); };
const chat = (m) => `document.getElementById('chatInput').value=${JSON.stringify(m)}; document.getElementById('chatForm').requestSubmit(); 'sent'`;


const type = (id, v) => `(()=>{const e=document.getElementById('${id}'); e.value=${JSON.stringify(v)}; e.dispatchEvent(new Event('input',{bubbles:true})); return 'ok'})()`;

const loginAs = async (u, p) => { await step("login " + u, type("authUser", u) + ";" + type("authPass", p) + ";document.getElementById('authGo').click(); 'x'", 3500); };

const setv = (id, v) => `(()=>{const e=document.getElementById('${id}'); e.value=${JSON.stringify(v)}; e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true})); return 'ok'})()`;
const click = (sel) => `(()=>{const e=document.querySelector(${JSON.stringify(sel)}); if(!e) return 'NOT FOUND ${sel}'; e.click(); return 'clicked'})()`;
const submit = (sel) => `(()=>{const f=document.querySelector(${JSON.stringify(sel)}); f.requestSubmit(); return 'submitted'})()`;
const ask = (m) => setv("finInput", m) + ";document.getElementById('finForm').requestSubmit(); 'sent'";
const lastBot = `[...document.querySelectorAll('#finMsgs .m.bot')].pop()?.textContent.slice(0,230)`;
const typeIn = (id, v) => `(()=>{const e=document.getElementById('${id}'); e.value=${JSON.stringify(v)}; e.dispatchEvent(new Event('input',{bubbles:true})); return 'ok'})()`;


const run = async (e, wait = 700) => { const v = await ev(e); await sleep(wait); return v; };
const until = async (expr, ms = 8000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await ev(expr)) return true; await sleep(250); } return false; };
let failed = 0;
const check = (n, ok, d = "") => { console.log((ok ? "PASS  " : "FAIL  ") + n + (d ? "  -> " + String(d).slice(0, 150) : "")); if (!ok) failed++; };
const j = (e) => ev(e);
const text = (sel) => ev(`(document.querySelector(${JSON.stringify(sel)})||{}).textContent||''`);
await loginAs("admin", "123");
check("admin view shown, advisor hidden", await ev(`!document.getElementById('adminView').hidden && getComputedStyle(document.querySelector('.chat')).display==='none'`));
await sleep(1200);
check("stats load from the database without clicking", (await ev(`document.querySelectorAll('#adminStats .kpi').length`)) === 5, await text("#adminStats"));
check("member list is closed at first", await ev(`getComputedStyle(document.getElementById('adminUsers')).display==='none'`));
await run(click("#adminManage"), 1500);
check("Manage accounts opens a table from the database", (await ev(`document.querySelectorAll('#adminUsers tbody tr[data-u]').length`)) >= 2, await ev(`document.querySelectorAll('#adminUsers tbody tr[data-u]').length`));
check("button now reads Hide accounts", (await text("#adminManage")) === "Hide accounts");
await shot("admin_01_portal");

await run(setv("apQ", "zzzz-nobody"), 700);
check("search with no match shows an empty message", (await text("#adminUsers tbody")).includes("No account matches"));
await run(setv("apQ", ""), 700);
await run(setv("apRole", "admin"), 600);
check("role filter keeps only administrators", await ev(`[...document.querySelectorAll('#adminUsers tbody tr[data-u]')].every(r=>r.textContent.includes('Administrator'))`));
await run(setv("apRole", ""), 500);

await run(click("#apAdd"), 600);
await run(setv("adUser", "portal.test") + ";" + setv("adName", "Portal Test") + ";" + setv("adPw", "temp-pass-77") + ";" + submit("#adForm"), 1500);
check("a new account appears in the list after creating it", await until(`!!document.querySelector('#adminUsers tr[data-u="portal.test"]')`));
check("and the dialog closed", await until(`document.getElementById('adminModal').hidden`));

await run(click('#adminUsers [data-manage="portal.test"]'), 1500);
await shot("admin_02_manage");
check("the manage dialog shows its details", (await text("#adminModalTitle")).includes("@portal.test"));
await run(`document.querySelector('[data-perm=ledger]').click(); 'x'`, 1200);
const perms = await ev(`fetch('/api/admin/users').then(r=>r.json()).then(o=>o.users.find(u=>u.username==='portal.test').permissions.ledger)`);
check("toggling a feature writes to the database", perms === false);
await run(click("#amBan"), 1300);
check("suspending marks the account suspended in the list", (await ev(`fetch('/api/admin/users').then(r=>r.json()).then(o=>o.users.find(u=>u.username==='portal.test').banned)`)) === true);
check("and the stats card counts it", await until(`document.getElementById('adminStats').textContent.includes('1 suspended')`));
await run(click("#amBan"), 1300);
await run(setv("amPw", "another-pass-9") + ";" + click("#amPwGo"), 1300);
check("password reset closes the dialog", await ev(`document.getElementById('adminModal').hidden`));

await run(`window.confirm = () => true; 'ok'`, 10);
await run(click('#adminUsers [data-manage="portal.test"]'), 700);
await run(click("#amDel"), 900);
check("delete is refused without typing the username", (await text("#amErr")).includes("type its username"));
await run(setv("amDelTxt", "portal.test") + ";" + click("#amDel"), 1500);
check("after the typed confirmation the account is gone", await until(`!document.querySelector('#adminUsers tr[data-u="portal.test"]')`));

await run(click("#adminActivityBtn"), 1200);
const act = await text("#adminActivity");
check("recent activity lists the administrator's actions", act.includes("created @portal.test") && act.includes("deleted @portal.test") && act.includes("suspended @portal.test"), act.slice(0, 100));
check("no JavaScript errors", errors.filter(e=>!/Extension context/.test(e)).length === 0, errors.slice(0,2).join("|"));
await viewport(390, 844, true); await send("Page.reload"); await sleep(3500);
await run(click("#adminManage"), 1500);
check("mobile: no sideways scrolling", await ev(`document.documentElement.scrollWidth <= window.innerWidth + 1`));
await shot("admin_03_mobile");
console.log(failed ? failed + " failed" : "all passed");
ws.close(); proc.kill(); process.exit(failed ? 1 : 0);
