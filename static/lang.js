// Three interface languages (English, Simplified Chinese, Bangla), kept apart from the financial jurisdiction (Bangladesh / China).
// One place owns the language: the saved preference comes from the server (/api/fin/settings), localStorage is only a first-paint cache,
// and any text without a translation falls back to English. Stored amounts, dates and currency codes are never translated: only the
// way they are shown (digits, grouping) changes.
(function () {
  const LANGS = ["en", "zh", "bn"];
  const NAMES = { en: "English", zh: "简体中文", bn: "বাংলা" };
  const HTML_LANG = { en: "en", zh: "zh-CN", bn: "bn-BD" };
  const BTN = { en: "中文", zh: "বাংলা", bn: "English" };           // the language button shows the NEXT language
  const SPEECH = { en: "en-US", zh: "zh-CN", bn: "bn-BD" };

  // English text -> translation. Matched on the whole trimmed text of an element, so sentences are never half-translated.
  const P = {
    zh: {
      "My money": "我的资金", "Overview": "概览", "Transactions": "交易", "Accounts": "账户", "Plan": "计划", "Reports": "报告", "Assistant": "助手", "Settings": "设置",
      "Language and region": "语言与地区", "Interface language": "界面语言", "Financial jurisdiction": "金融辖区", "Active jurisdiction": "当前辖区", "Currency": "币种",
      "Bangladesh": "孟加拉国", "China (mainland)": "中国大陆", "Automatic": "自动", "Save": "保存", "Saved.": "已保存。", "Cancel": "取消", "Delete": "删除", "Edit": "编辑", "Create": "创建",
      "Add bill": "添加账单", "Add budget": "添加预算", "Add goal": "添加目标", "Add savings": "添加储蓄", "Amount": "金额", "Date": "日期", "Category": "类别", "Subcategory": "子类别",
      "Account": "账户", "Description": "说明", "Note": "备注", "Type": "类型", "Status": "状态", "Name": "名称", "Period": "期间", "Goal": "目标", "Goals": "目标", "Limit": "限额",
      "Actual balance": "实际余额", "Liquid now": "当前可用", "Money in": "收入", "Money out": "支出", "Forecast": "预测", "Projected month-end": "预计月末", "Upcoming bills": "即将到期的账单",
      "Recent transactions": "最近交易", "Spending by category": "按类别的支出", "Income vs spending": "收入与支出", "Budget vs actual": "预算与实际", "Daily spending": "每日支出",
      "Top categories": "主要类别", "Top merchants": "主要商家", "Data quality": "数据质量", "What stands out": "值得注意", "Needs attention": "需要关注", "Nothing recorded yet.": "暂无记录。",
      "Tell me about your money.": "和我聊聊你的资金吧。", "Download CSV": "下载 CSV", "Import CSV": "导入 CSV", "Export CSV": "导出 CSV", "Generate report": "生成报告", "Earlier reports": "以往报告",
      "AI preferences": "AI 偏好", "AI status and use": "AI 状态与用量", "What is sent where": "数据发送去向", "My activity": "我的操作记录", "Your data": "你的数据",
      "Assistant language": "助手语言", "Read assistant replies aloud": "朗读助手回复", "Main currency": "主要币种", "Clear history": "清除历史", "Erase all my finance data": "删除我的全部财务数据",
      "Essential": "必要", "Discretionary": "非必要", "Monthly": "每月", "Weekly": "每周", "Yearly": "每年", "High": "高", "Low": "低", "Medium": "中",
      "Voice mode": "语音模式", "Start voice mode": "开启语音模式", "Stop voice mode": "结束语音模式", "Listening…": "正在聆听…", "Processing…": "处理中…", "Speaking…": "正在朗读…",
      "Say something": "请说话", "Back to text chat": "返回文字聊天", "Voice preferences": "语音偏好", "Enable voice mode": "启用语音模式", "Speech language": "语音语言",
      "Read replies aloud automatically": "自动朗读回复", "Large text": "大号文字", "Microphone": "麦克风", "Conversations": "对话记录", "New conversation": "新对话", "Resume": "继续",
      "Recorded": "已记录", "Estimate": "估算", "Pending": "待确认", "Forecasted": "预测值", "Scheduled": "已安排",
      "Compliance-first wealth advice": "合规优先的财富顾问", "New chat": "新对话", "Chats": "对话", "No chats yet.": "暂无对话。",
      "Food": "餐饮", "Transport": "交通", "Housing": "住房", "Utilities": "水电费", "Health": "医疗健康", "Education": "教育", "Shopping": "购物", "Entertainment": "娱乐", "Savings": "储蓄",
      "Salary": "工资", "Other": "其他", "Cash": "现金", "Bank": "银行", "Card": "银行卡"
    },
    bn: {
      "My money": "আমার টাকা", "Overview": "সারসংক্ষেপ", "Transactions": "লেনদেন", "Accounts": "অ্যাকাউন্ট", "Plan": "পরিকল্পনা", "Reports": "প্রতিবেদন", "Assistant": "সহকারী", "Settings": "সেটিংস",
      "Language and region": "ভাষা ও অঞ্চল", "Interface language": "ইন্টারফেসের ভাষা", "Financial jurisdiction": "আর্থিক এখতিয়ার", "Active jurisdiction": "বর্তমান এখতিয়ার", "Currency": "মুদ্রা",
      "Bangladesh": "বাংলাদেশ", "China (mainland)": "চীন (মূল ভূখণ্ড)", "Automatic": "স্বয়ংক্রিয়", "Save": "সংরক্ষণ", "Saved.": "সংরক্ষিত হয়েছে।", "Cancel": "বাতিল", "Delete": "মুছুন", "Edit": "সম্পাদনা", "Create": "তৈরি করুন",
      "Add bill": "বিল যোগ করুন", "Add budget": "বাজেট যোগ করুন", "Add goal": "লক্ষ্য যোগ করুন", "Add savings": "সঞ্চয় যোগ করুন", "Amount": "পরিমাণ", "Date": "তারিখ", "Category": "বিভাগ", "Subcategory": "উপবিভাগ",
      "Account": "অ্যাকাউন্ট", "Description": "বিবরণ", "Note": "নোট", "Type": "ধরন", "Status": "অবস্থা", "Name": "নাম", "Period": "সময়কাল", "Goal": "লক্ষ্য", "Goals": "লক্ষ্যসমূহ", "Limit": "সীমা",
      "Actual balance": "প্রকৃত ব্যালেন্স", "Liquid now": "এখন হাতে আছে", "Money in": "আয়", "Money out": "ব্যয়", "Forecast": "পূর্বাভাস", "Projected month-end": "মাস শেষে আনুমানিক", "Upcoming bills": "আসন্ন বিল",
      "Recent transactions": "সাম্প্রতিক লেনদেন", "Spending by category": "বিভাগ অনুযায়ী খরচ", "Income vs spending": "আয় বনাম খরচ", "Budget vs actual": "বাজেট বনাম প্রকৃত", "Daily spending": "দৈনিক খরচ",
      "Top categories": "শীর্ষ বিভাগ", "Top merchants": "শীর্ষ দোকান", "Data quality": "তথ্যের মান", "What stands out": "লক্ষণীয় বিষয়", "Needs attention": "মনোযোগ দরকার", "Nothing recorded yet.": "এখনও কিছু লেখা হয়নি।",
      "Tell me about your money.": "আপনার টাকার কথা বলুন।", "Download CSV": "CSV ডাউনলোড", "Import CSV": "CSV আমদানি", "Export CSV": "CSV রপ্তানি", "Generate report": "প্রতিবেদন তৈরি", "Earlier reports": "আগের প্রতিবেদন",
      "AI preferences": "এআই পছন্দ", "AI status and use": "এআই অবস্থা ও ব্যবহার", "What is sent where": "কোথায় কী পাঠানো হয়", "My activity": "আমার কার্যকলাপ", "Your data": "আপনার তথ্য",
      "Assistant language": "সহকারীর ভাষা", "Read assistant replies aloud": "সহকারীর উত্তর জোরে পড়ুন", "Main currency": "প্রধান মুদ্রা", "Clear history": "ইতিহাস মুছুন", "Erase all my finance data": "আমার সব আর্থিক তথ্য মুছুন",
      "Essential": "প্রয়োজনীয়", "Discretionary": "ঐচ্ছিক", "Monthly": "মাসিক", "Weekly": "সাপ্তাহিক", "Yearly": "বার্ষিক", "High": "বেশি", "Low": "কম", "Medium": "মাঝারি",
      "Voice mode": "ভয়েস মোড", "Start voice mode": "ভয়েস মোড চালু করুন", "Stop voice mode": "ভয়েস মোড বন্ধ করুন", "Listening…": "শুনছি…", "Processing…": "প্রক্রিয়া চলছে…", "Speaking…": "বলছি…",
      "Say something": "কিছু বলুন", "Back to text chat": "টেক্সট চ্যাটে ফিরুন", "Voice preferences": "ভয়েস পছন্দ", "Enable voice mode": "ভয়েস মোড চালু রাখুন", "Speech language": "কথার ভাষা",
      "Read replies aloud automatically": "উত্তর নিজে থেকে পড়ে শোনান", "Large text": "বড় লেখা", "Microphone": "মাইক্রোফোন", "Conversations": "কথোপকথন", "New conversation": "নতুন কথোপকথন", "Resume": "আবার শুরু",
      "Recorded": "লিপিবদ্ধ", "Estimate": "আনুমানিক", "Pending": "অপেক্ষমাণ", "Forecasted": "পূর্বাভাসিত", "Scheduled": "নির্ধারিত",
      "Compliance-first wealth advice": "নিয়ম মেনে সম্পদ পরামর্শ", "New chat": "নতুন চ্যাট", "Chats": "চ্যাট", "No chats yet.": "এখনও কোনো চ্যাট নেই।",
      "Risk profile": "ঝুঁকির প্রোফাইল", "Allocation": "বিনিয়োগ বণ্টন", "Compliance": "নিয়ম পালন", "Stress test": "চাপ পরীক্ষা", "Approvals": "অনুমোদন", "Purchase history": "কেনাকাটার ইতিহাস",
      "Memory": "স্মৃতি", "Audit log": "অডিট লগ", "Advice receipt": "পরামর্শের রসিদ",
      "Food": "খাবার", "Transport": "যাতায়াত", "Housing": "বাসস্থান", "Utilities": "ইউটিলিটি", "Health": "স্বাস্থ্য", "Education": "শিক্ষা", "Shopping": "কেনাকাটা", "Entertainment": "বিনোদন", "Savings": "সঞ্চয়",
      "Salary": "বেতন", "Other": "অন্যান্য", "Cash": "নগদ", "Bank": "ব্যাংক", "Card": "কার্ড"
    }
  };
  // The advisor screens already have a key-based Chinese dictionary (i18n.js); Bangla for those comes from the English-text map above.

  const BN_DIGITS = "০১২৩৪৫৬৭৮৯";
  const toBn = (s) => String(s).replace(/[0-9]/g, (d) => BN_DIGITS[+d]);
  const SKIP = new Set(["SCRIPT", "STYLE", "TEXTAREA", "INPUT", "SELECT", "CODE", "PRE"]);
  const orig = new WeakMap();           // text node -> original English
  const origAttr = new WeakMap();       // element -> {attr: english}
  let lang = "en", observer = null, queued = false, server = null;

  const dict = () => P[lang] || null;
  const looksNumeric = (s) => /[0-9]/.test(s) && !/[A-Za-z一-鿿]/.test(s);

  function tr(text) {
    const d = dict();
    if (!d) return text;
    const k = text.trim();
    if (k in d) return text.replace(k, d[k]);
    return text;
  }
  function t(en) { const d = dict(); return (d && d[en]) || en; }

  function xlateNode(n) {
    if (!orig.has(n)) orig.set(n, n.nodeValue);
    const o = orig.get(n);
    let v = o;
    if (lang !== "en") {
      v = tr(o);
      if (v === o && lang === "bn" && looksNumeric(o)) v = toBn(o);        // display-only: the stored value is untouched
    }
    if (n.nodeValue !== v) n.nodeValue = v;
  }
  const ATTRS = ["placeholder", "aria-label", "title"];
  function xlateAttrs(el) {
    let rec = origAttr.get(el);
    for (const a of ATTRS) {
      const cur = el.getAttribute && el.getAttribute(a);
      if (cur == null) continue;
      if (!rec) { rec = {}; origAttr.set(el, rec); }
      if (!(a in rec)) rec[a] = cur;
      const v = lang === "en" ? rec[a] : tr(rec[a]);
      if (v !== cur) el.setAttribute(a, v);
    }
  }
  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) { if (root.nodeValue.trim()) xlateNode(root); return; }
    if (root.nodeType !== 1 || SKIP.has(root.tagName) || (root.closest && root.closest("[data-notr]"))) return;
    xlateAttrs(root);
    for (const c of root.childNodes) walk(c);
  }
  function schedule() {
    if (queued) return;
    queued = true;
    (window.requestAnimationFrame || setTimeout)(() => { queued = false; observer && observer.disconnect(); walk(document.body); observe(); });
  }
  function observe() {
    if (!observer) observer = new MutationObserver((muts) => { if (lang !== "en" || muts.some((m) => m.type === "childList")) schedule(); });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  function fmtNumber(value, currencyCode) {
    const n = Number(value);
    if (!isFinite(n)) return String(value);
    const loc = { en: "en-US", zh: "zh-CN", bn: "bn-BD" }[lang];
    try {
      const s = new Intl.NumberFormat(loc, { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: true }).format(n);
      return currencyCode ? s + " " + currencyCode : s;
    } catch (e) { return String(value); }
  }
  function fmtDate(iso) {
    const d = new Date(String(iso).slice(0, 10) + "T00:00:00");
    if (isNaN(d)) return String(iso);
    try { return new Intl.DateTimeFormat({ en: "en-GB", zh: "zh-CN", bn: "bn-BD" }[lang], { year: "numeric", month: "short", day: "numeric" }).format(d); } catch (e) { return String(iso); }
  }

  function cacheGet() { try { const v = localStorage.getItem("wg_lang"); return LANGS.includes(v) ? v : null; } catch (e) { return null; } }
  function cacheSet(l) { try { localStorage.setItem("wg_lang", l); } catch (e) { /* private mode */ } }

  // Applies a language everywhere: chrome (advisor keys), the phrase map for the rest, button label, <html lang> and the voice language.
  async function apply(l, opts) {
    opts = opts || {};
    lang = LANGS.includes(l) ? l : "en";
    document.documentElement.lang = HTML_LANG[lang];
    cacheSet(lang);
    const I = window.WGI18n;
    if (I && I.setLang) { try { await I.setLang(lang === "zh" ? "zh" : "en", opts.api, opts.clientId, opts.rerender); } catch (e) { /* advisor panel not mounted */ } }
    if (I && I.applyStatic) { /* applyStatic only knows zh/en; Bangla uses the phrase map below */ }
    walk(document.body);
    observe();
    const b = document.getElementById("langBtn");
    if (b) { (b.querySelector("span") || b).textContent = BTN[lang]; b.setAttribute("aria-pressed", String(lang !== "en")); }
    const sel = document.getElementById("uiLangSel");
    if (sel) sel.value = lang;
    const v = document.getElementById("voiceLang");
    if (v) { const want = SPEECH[lang]; if ([...v.options].some((o) => o.value === want)) v.value = want; }
    window.dispatchEvent(new CustomEvent("wg:lang", { detail: { lang } }));
    if (opts.persist !== false && server) { try { await server(lang); } catch (e) { /* kept in cache; retried on next change */ } }
  }
  function next() { return LANGS[(LANGS.indexOf(lang) + 1) % LANGS.length]; }

  window.WGLang = { LANGS, NAMES, SPEECH, P, get lang() { return lang; }, t, tr, toBn, apply, next, fmtNumber, fmtDate, cacheGet, walk, refresh: schedule,
                    bindServer(fn) { server = fn; }, speechCode(pref) { return pref && pref !== "auto" ? SPEECH[pref] : SPEECH[lang]; } };
  const post = async (patch) => {
    const r = await fetch("/api/fin/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
    if (!r.ok) throw new Error("settings");
    return r.json();
  };
  window.WGLang.saveSettings = post;
  window.WGLang.bindServer((l) => post({ ui_lang: l }));
  document.addEventListener("DOMContentLoaded", () => { const c = cacheGet(); if (c) apply(c, { persist: false }); });
  // After sign-in the SAVED preference wins over the browser cache, so the language follows the account across devices and logins.
  if (window.WGAuth && window.WGAuth.onReady) {
    window.WGAuth.onReady(async (u) => {
      if (!u || u.role === "admin") return;
      try {
        const r = await fetch("/api/fin/settings");
        if (!r.ok) return;
        const st = await r.json();
        window.WGLang.prefs = st;
        if (st.ui_lang && st.ui_lang !== lang) await apply(st.ui_lang, { persist: false });
        window.dispatchEvent(new CustomEvent("wg:prefs", { detail: st }));
      } catch (e) { /* the cached language stays */ }
    });
  }
})();
