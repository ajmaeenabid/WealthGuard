// English / Chinese UI. Static labels come from a fixed dictionary; engine- or model-generated text (rationales,
// compliance details, ...) is translated by /api/translate, which re-checks the result (R7) and falls back to English.
(function () {
  const ZH = {
    banner: "教育演示，产品均为合成数据，不构成真实的投资建议。",
    footer: "教育演示，产品均为合成数据，不构成真实的投资建议。所有数据均为合成数据。",
    tagline: "合规的财富顾问智能体", client: "客户", start: "开始会话", send: "发送",
    chatTitle: "顾问对话", chatPh: "输入消息或回答…",
    h1: "1. 风险画像", h2: "2. 建议配置", h3: "3. 合规检查", h4: "4. 压力测试与目标概率", h5: "5. 审批队列 (T2)",
    h6: "6. 上传文档（不可信）", h7: "7. 审计日志", whyNotTitle: "为什么不选其他产品？",
    run: "运行", upload: "上传", attack: "加载攻击样本", verify: "验证日志", refresh: "刷新", exportJson: "导出 JSON",
    docPh: "粘贴宣传册文本…",
    ph_profile: "请在聊天中回答问题以生成画像。", ph_alloc: "合规引擎批准之前不会显示任何内容。",
    ph_stress: "需要先有合规的配置。", ph_tickets: "暂无待处理操作。请让智能体“创建订单”。",
    sc1: "股票 -20%（假设情景）", sc2: "利率冲击（真实2022年）", sc3: "2008年金融危机（真实）", sc4: "通胀飙升（真实1974年）",
    sc5: "互联网泡沫破裂（真实2000-02年）", sc6: "大萧条（真实1929-32年）",
    thTime: "时间", thActor: "角色", thTier: "层级", thAction: "操作", thHash: "哈希",
    "approved by compliance": "已通过合规批准", "all checks passed": "全部检查通过", "BLOCKED": "已拦截",
    "chain valid": "哈希链有效", "CHAIN BROKEN": "哈希链已断裂",
    "Product": "产品", "Weight": "占比", "Amount": "金额", "Why this": "推荐理由",
    "Approve": "批准", "Reject": "拒绝", "sandbox": "沙盒",
    "Required disclosures:": "必须披露：", "Draft log": "草稿记录",
    "Risk tolerance": "风险承受意愿", "Risk capacity": "风险承受能力",
    "Final bucket = the lower of the two:": "最终风险档位 = 两者中较低者：",
    "What would it take?": "需要满足什么条件？", "Allowed now": "目前允许", "Blocked now": "目前被拦截", "Only if": "只有在以下情况下才允许",
    "Impossible": "无法通过回答改变", "Rule check": "规则检查", "answer": "回答", "would be": "将是", "bucket": "风险档位",
    hC: "建议回执", rcHint: "已批准建议的封存记录：规则、法规条文、数据哈希和审计锚点。任何人都可以验证。", rcDownload: "下载回执",
    rcVerify: "验证回执文件", "Receipt is valid": "回执有效", "Receipt is NOT valid": "回执无效",
    hR: "红队攻击演示", rtHint: "对真实防线运行一批中英文攻击，显示每次攻击由哪一层拦截。不调用语言模型。",
    rtRun: "运行攻击", rtDl: "导出 JSON", "Defended": "已防御", "attacks": "次攻击",
    hS: "自查报告（第三十条）", siHint: "根据审计日志统计：被拦截、被拒绝和已批准的事项，按监管职责列出，并如实说明未覆盖事项。",
    siGen: "生成报告", siDl: "下载 Markdown", siClientOnly: "仅限当前客户", "Duties": "法定职责", "Findings": "发现", "Not covered": "未覆盖事项",
    hK: "法规与数据检索（向量库）", kbHint: "检索真实的证监会适当性管理办法（中文原文）、数据来源、历史情景和我们的规则。",
    kbPh: "例如：普通投资者可以购买复杂产品吗？", search: "搜索", kbAll: "全部来源", kbCsrc: "证监会法规", kbData: "数据来源",
    kbEp: "压力情景", kbRules: "我们的规则", kbHist: "真实历史卡片", "Regulatory basis": "监管依据", "Chinese original": "中文原文", "No results.": "没有结果。", "score": "相关度",
    hL: "购买记录与行为分析", ledgerHint: "说出或输入你买了什么、计划买什么或没买什么。确认之前不会有任何改动。",
    ledgerPh: "例如：买了耳机花了300元 / 取消笔记本", interpret: "解析", itemPh: "物品", impulse: "冲动消费", add: "添加",
    sampleBalanced: "加载示例记录", sampleHeavy: "加载高消费示例", thDate: "日期", thItem: "物品", thAmt: "金额", thStatus: "状态",
    "Confirm": "确认", "Discard": "放弃", "Cancel item": "标为没买", "Mark bought": "标为已买", "Delete": "删除",
    "bought": "已买", "planned": "计划中", "cancelled": "已取消", "Bought": "已买", "Planned": "计划中", "Cancelled": "已取消",
    "Pending change:": "待确认的更改：", "Bought total": "已买合计", "Planned (not counted)": "计划中（不计入）",
    "Cancelled (not counted)": "已取消（不计入）", "No entries yet.": "暂无记录。", "Start a session first.": "请先开始会话。", "Enter an item and an amount.": "请输入物品和金额。",
    "Review the change below, then confirm.": "请查看下方的更改，然后确认。",
  };
  const ZH_RULES = { R1: "适当性", R2: "集中度", R3: "复杂性", R4: "流动性", R5: "脆弱客户", R6: "披露", R7: "用语", R8: "最低金额", R9: "通俗易懂" };
  let lang = "en";
  const cache = new Map();

  const t = (en) => (lang === "zh" && ZH[en]) || en;
  const ruleName = (id, en) => (lang === "zh" && ZH_RULES[id]) || en;
  // Mark engine-generated text so it can be translated on demand; the English original is kept in data-en.
  const tr = (text, esc) => `<span data-en="${esc(text)}">${esc(text)}</span>`;

  function applyStatic() {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      if (!el.dataset.en0) el.dataset.en0 = el.textContent;
      el.textContent = lang === "zh" ? (ZH[el.dataset.i18n] || el.dataset.en0) : el.dataset.en0;
    });
    document.querySelectorAll("[data-i18n-ph]").forEach((el) => {
      if (!el.dataset.en0) el.dataset.en0 = el.placeholder;
      el.placeholder = lang === "zh" ? (ZH[el.dataset.i18nPh] || el.dataset.en0) : el.dataset.en0;
    });
    const v = document.getElementById("voiceLang");
    if (v) v.value = lang === "zh" ? "zh-CN" : "en-US";
  }

  async function applyDynamic(api, clientId) {
    const els = [...document.querySelectorAll("[data-en]")];
    if (!els.length) return;
    if (lang === "en") { els.forEach((el) => (el.textContent = el.dataset.en)); return; }
    const need = [...new Set(els.map((el) => el.dataset.en).filter((s) => !cache.has(s)))];
    for (let i = 0; i < need.length; i += 40) {
      const batch = need.slice(i, i + 40);
      try {
        const r = await api("/api/translate", { client_id: clientId || null, target: "zh", texts: batch });
        batch.forEach((s, j) => cache.set(s, r.texts[j]));
      } catch (e) { batch.forEach((s) => cache.set(s, s)); }
    }
    els.forEach((el) => (el.textContent = cache.get(el.dataset.en) || el.dataset.en));
  }

  async function setLang(l, api, clientId, rerender) {
    lang = l === "zh" ? "zh" : "en";
    applyStatic();
    if (rerender) await rerender();
    await applyDynamic(api, clientId);
    const b = document.getElementById("langBtn");
    if (b) { b.textContent = lang === "zh" ? "English" : "中文"; b.setAttribute("aria-pressed", String(lang === "zh")); }
  }

  window.WGI18n = { t, tr, ruleName, setLang, applyDynamic, applyStatic, get lang() { return lang; }, ZH };
})();
