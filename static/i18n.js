// English / Chinese UI. Static labels come from a fixed dictionary; engine- or model-generated text (rationales,
// compliance details, ...) is translated by /api/translate, which re-checks the result (R7) and falls back to English.
(function () {
  const ZH = {
    banner: "教育演示，产品均为合成数据，不构成真实的投资建议。",
    footer: "教育演示，产品均为合成数据，不构成真实的投资建议。所有数据均为合成数据。",
    tagline: "合规优先的财富顾问", client: "客户", start: "开始会话", send: "发送",
    chatTitle: "顾问对话", chatPh: "给 WealthGuard 发消息…",
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
    "How is this calculated?": "这个数字是怎么算的？", "expected return": "预期收益", "volatility": "波动率",
    "portfolio change": "组合变动", "goal probability": "目标概率", "historical share": "历史窗口占比", "Formula": "公式", "Inputs": "输入", "Datasets": "数据集", "Recomputed": "重新计算",
    "matches": "一致", "does NOT match": "不一致", "Close": "关闭", "independent check from the raw CSV": "基于原始CSV的独立核对",
    hP: "用你的资金重演历史", rpHint: "用已批准的配置亲历一次真实的市场行情，并在难受时做决定。我们会把你的行为与你的回答对比。",
    rpEquity: "仅股票市场（测试心态）", rpMine: "我的配置", rpStart: "开始重演", "Hold and wait": "持有等待",
    "Sell some (25% to cash)": "卖出一部分（25%转为现金）", "Sell everything to cash": "全部卖出转为现金",
    "Buy more (add 10% of the starting amount)": "加仓（追加起始金额的10%）", "Apply to my profile": "应用到我的画像",
    veAuto: "语音：自动", veBrowser: "浏览器", veLabel: "引擎", vlLabel: "语言",
    navFlow: "咨询流程", navTools: "洞察", navTrust: "信任与证据",
    nProfile: "风险画像", nAlloc: "建议配置", nComp: "合规检查", nStress: "压力测试", nApprove: "审批", nLedger: "购买记录",
    nReplay: "历史重演", nSearch: "法规检索", nReceipt: "建议回执", nRedteam: "红队演示", nSelf: "自查报告", nDocs: "上传文档", nAudit: "审计日志",
    heroTitle: "可以验证的建议。", heroSub: "在独立合规引擎批准之前，不会向你展示任何内容；每一步都有记录。",
    "Start with": "开始：",
    tagline2: "每条建议都经过核查，每一步都有记录。", newChat: "新对话", navChats: "对话记录", noChats: "还没有对话。",
    authLead: "登录后继续你的理财咨询。", signIn: "登录", signUp: "创建账户", username: "用户名", password: "密码",
    confirmPassword: "确认密码", authHint: "演示账户：admin、li、chen、wang，密码均为 123（请在设置中修改）。",
    settings: "设置", changePassword: "修改密码", currentPassword: "当前密码", newPassword: "新密码", savePassword: "保存密码",
    hMem: "我记得的内容", memHint: "仅为你的账户保存，新对话可以接着上次继续。可以随时修改或删除。", memFacts: "你的资料", memNotes: "备注",
    memNotePh: "添加我应该记住的事情", memAdd: "添加", memChats: "过往对话", memDemoH: "演示资料", memDemoHint: "载入一个现成的客户资料用于演示，这会替换你已保存的资料。",
    memLoad: "载入演示资料", memClear: "忘掉所有内容", nMemory: "记忆", helloPrefix: "你好，",
    adminTitle: "管理后台", adminLead: "暂停账户、更改角色，并为每个账户单独开启或关闭功能。聊天内容只属于其主人；这里的每个操作都会写入审计日志。",
    "I remember {n} things from your earlier chats. Open Memory to review them.": "我记得之前对话中的 {n} 件事。打开“记忆”可以查看。",
    "Nothing saved yet. Answers you give in a chat appear here.": "还没有保存内容。你在对话中给出的回答会显示在这里。",
    "No notes yet. Tell me things like \"remember that I prefer low fees\".": "还没有备注。可以对我说“记住我偏好低费率”。",
    "Short summaries of your chats appear here.": "你的对话摘要会显示在这里。",
    "Saved. New chats will use it.": "已保存，新对话会使用它。", "Saved.": "已保存。", "Forget this": "忘掉这条",
    "Demo profile loaded. New chats start with it.": "演示资料已载入，新对话将使用它。",
    "Forget everything saved about you?": "确定忘掉所有关于你的已保存内容？", "Everything was forgotten.": "已全部忘掉。",
    "Chat is switched off for your account.": "管理员已关闭你账户的聊天功能。",
    "Member": "成员", "Suspended": "已暂停", "Role": "角色", "chats": "个对话", "Restore access": "恢复访问", "Suspend account": "暂停账户",
    "Reset password": "重置密码", "New password for": "新密码，账户", "at least 6 characters": "至少 6 个字符",
    "Administrators have every feature.": "管理员拥有全部功能。", "Role updated.": "角色已更新。", "Account restored.": "账户已恢复。",
    "Account suspended.": "账户已暂停。", "Access updated.": "权限已更新。",
    "Password reset. The account was signed out everywhere.": "密码已重置，该账户已在所有设备退出登录。",
    "Advice chat": "咨询聊天", "Order tickets and reports": "订单与报告", "Purchase history": "购买记录", "History replay": "历史重演",
    "Document upload": "文档上传", "Voice input": "语音输入", "Regulation search": "法规搜索", "Advice receipt": "建议凭证",
    "Red-team arena and self-inspection": "红队演练与自查",
    "New chat": "新对话", "AI usage (30 days)": "AI 用量（30天）", "Calls": "调用次数", "Tokens": "令牌数", "Estimated cost": "预计费用", "Failed calls": "失败调用", "Average latency": "平均延迟", "By purpose": "按用途", "Delete chat": "删除对话", "Delete this chat?": "删除这段对话？", "Administrator": "管理员",
    "The two passwords do not match.": "两次输入的密码不一致。", "Password changed. Other devices were signed out.": "密码已修改，其他设备已退出登录。", "Session started.": "会话已开始。", "Starting a session for the selected client first.": "先为所选客户开始会话。", "Advice approved by compliance": "建议已通过合规批准", "Open allocation": "查看配置",
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
    if (b) { (b.querySelector("span") || b).textContent = lang === "zh" ? "English" : "中文"; b.setAttribute("aria-pressed", String(lang === "zh")); }
  }

  window.WGI18n = { t, tr, ruleName, setLang, applyDynamic, applyStatic, get lang() { return lang; }, ZH };
})();
