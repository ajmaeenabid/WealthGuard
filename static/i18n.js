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
    sc1: "股票 -20%", sc2: "利率 +2 个百分点", sc3: "2008 式崩盘", sc4: "通胀飙升",
    thTime: "时间", thActor: "角色", thTier: "层级", thAction: "操作", thHash: "哈希",
    "approved by compliance": "已通过合规批准", "all checks passed": "全部检查通过", "BLOCKED": "已拦截",
    "chain valid": "哈希链有效", "CHAIN BROKEN": "哈希链已断裂",
    "Product": "产品", "Weight": "占比", "Amount": "金额", "Why this": "推荐理由",
    "Approve": "批准", "Reject": "拒绝", "sandbox": "沙盒",
    "Required disclosures:": "必须披露：", "Draft log": "草稿记录",
    "Risk tolerance": "风险承受意愿", "Risk capacity": "风险承受能力",
    "Final bucket = the lower of the two:": "最终风险档位 = 两者中较低者：",
  };
  const ZH_RULES = { R1: "适当性", R2: "集中度", R3: "复杂性", R4: "流动性", R5: "脆弱客户", R6: "披露", R7: "用语", R8: "最低金额" };
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
