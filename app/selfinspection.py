"""Self-inspection report modelled on CSRC Suitability Measures Art. 30 (a periodic self-check report) and Art. 32 (record keeping)."""
from collections import Counter

from app.security import audit

ARTICLE_URL = "https://www.gov.cn/gongbao/content/2023/content_5742209.htm"

DUTIES = [
    ("第六条", "Know the investor (collect information)", "了解投资者信息",
     "Adaptive questionnaire; only unknown facts are asked", "自适应问卷，只询问未知信息"),
    ("第十八条", "Match product risk level to the investor", "产品风险等级与投资者匹配",
     "Rules R1-R5 and R8 run on every draft before it is shown", "每份草案展示前都经过R1-R5和R8检查"),
    ("第二十条", "Special care when selling high-risk products to ordinary investors",
     "向普通投资者销售高风险产品的特别注意义务", "Complex or high-risk products are blocked (R1, R3, R5) and the reason is explained",
     "复杂或高风险产品被拦截（R1、R3、R5）并说明原因"),
    ("第二十一条", "Update classification when information changes", "信息变化时调整分类",
     "Answers invalidate the stored profile; behaviour data can only lower capacity", "回答会使已存画像失效；行为数据只会降低能力评分"),
    ("第二十二条", "No certainty promises or misleading sales conduct", "禁止确定性承诺和误导性销售",
     "R7 rejects guaranteed wording in English and Chinese, also on chat replies", "R7在中英文中拒绝保证性措辞，聊天回复同样适用"),
    ("第二十三条", "Disclose risks (including principal loss) before selling", "销售前告知风险（含本金亏损）",
     "R6 requires the risk warning, fee summary and past-performance disclaimer", "R6要求包含风险提示、费用说明和过往业绩声明"),
    ("第二十四条", "Warnings must be true, complete and easy to understand", "告知警示须真实完整、通俗易懂",
     "R9 checks sentence length, readability and unexplained jargon", "R9检查句子长度、可读性和未解释的术语"),
    ("第三十二条", "Keep records of suitability work", "妥善保存适当性履职记录",
     "Append-only SHA-256 hash-chained audit log, verifiable on demand", "只追加的SHA-256哈希链审计日志，可随时校验"),
]

GAPS = [
    ("第八条/第十一条/第十二条", "Professional-investor classification and conversion is not implemented; every client is treated as an ordinary investor.",
     "未实现专业投资者的认定与转化；所有客户均按普通投资者处理。"),
    ("第二十五条", "Recording or video of disclosures is not applicable to a web demo.", "录音录像要求不适用于网页演示。"),
    ("第三十四条", "Dispute and complaint handling has no workflow.", "没有纠纷与投诉处理流程。"),
    ("第三十条", "Reports are generated on demand; there is no half-yearly schedule or filing with the regulator.",
     "报告按需生成；没有每半年的定期安排，也不向监管机构报送。"),
]

TEXT = {
    "en": {
        "title": "Self-inspection report (modelled on CSRC Suitability Measures Art. 30)",
        "scope_all": "All sessions in this deployment", "scope_client": "One client only",
        "no_activity": "No activity is recorded yet, so there is nothing to inspect.",
        "blocked": "{blocked} of {total} advice drafts were blocked by the compliance engine before the client saw them ({rules}). "
                   "Only drafts that passed every rule were shown.",
        "all_passed": "All {total} checked drafts passed every rule on the first attempt.",
        "reply_blocked": "{n} chat replies were replaced because they contained prohibited certainty wording (Art. 22).",
        "injection": "{n} instruction-like texts were flagged and quoted back to the user (sources: {sources}).",
        "t3": "{n} forbidden actions were refused and logged ({tools}).",
        "invalid": "{n} tool calls were refused for unknown tools or invalid arguments.",
        "approvals": "{a} approvals and {r} rejections were made by explicit client clicks; {x} approval attempts were refused.",
        "refused_approvals": "{n} approval attempts were refused (wrong client, already handled, or not compliance-approved). Review them.",
        "fallback": "The language model was unavailable {n} times and the offline mock answered; review reliability.",
        "chain_ok": "The audit chain verifies over {n} entries (head {head}...).",
        "chain_bad": "The audit chain is BROKEN at entry {at}. Treat the record as compromised and report it (Art. 30).",
        "ledger": "{n} purchase-history commands were proposed; {c} were confirmed by the client and {r} rejected.",
    },
    "zh": {
        "title": "自查报告（参照证监会《证券期货投资者适当性管理办法》第三十条）",
        "scope_all": "本部署中的全部会话", "scope_client": "仅限单个客户",
        "no_activity": "目前没有记录到任何活动，无需检查。",
        "blocked": "{total}份建议草案中有{blocked}份在客户看到之前被合规引擎拦截（{rules}）。只有通过全部规则的草案才会展示。",
        "all_passed": "全部{total}份已检查的草案均一次性通过所有规则。",
        "reply_blocked": "有{n}条聊天回复因含有被禁止的确定性措辞而被替换（第二十二条）。",
        "injection": "有{n}段类似指令的文本被标记并向用户引用提示（来源：{sources}）。",
        "t3": "有{n}次禁止操作被拒绝并记录（{tools}）。",
        "invalid": "有{n}次工具调用因未知工具或参数无效被拒绝。",
        "approvals": "客户通过明确点击完成了{a}次批准和{r}次拒绝；有{x}次批准尝试被拒绝。",
        "refused_approvals": "有{n}次批准尝试被拒绝（客户不符、已处理或未通过合规批准），请复核。",
        "fallback": "语言模型有{n}次不可用，由离线模拟回答；请复核可靠性。",
        "chain_ok": "审计哈希链校验通过，共{n}条记录（链头 {head}...）。",
        "chain_bad": "审计哈希链在第{at}条记录处断裂。应视为记录已被破坏并上报（第三十条）。",
        "ledger": "共提出{n}条购买记录指令；客户确认{c}条，拒绝{r}条。",
    },
}


def _count(entries, pred):
    return sum(1 for e in entries if pred(e))


def metrics(entries: list[dict]) -> dict:
    act = Counter(e["action"] for e in entries)
    checks = [e for e in entries if e["action"] == "compliance_check"]
    failed_rules = Counter(r for e in checks for r in (e["payload"].get("failed_rules") or []))
    blocked = sum(1 for e in checks if not e["payload"].get("passed", True))
    t3 = Counter(e["action"].split(":", 1)[1] for e in entries if e["action"].startswith("refused_forbidden:"))
    inj = Counter(e["payload"].get("source") if e["payload"].get("source") in ("chat", "ledger_command") else "document"
                  for e in entries if e["action"] == "injection_flagged")
    return {
        "entries": len(entries),
        "first_ts": entries[0]["ts"] if entries else None, "last_ts": entries[-1]["ts"] if entries else None,
        "sessions": act["session_started"], "chat_messages": act["chat_message"],
        "profile_answers": act["profile_answer"], "profiles_invalidated": act["profile_invalidated_by_behaviour"],
        "compliance_checks": len(checks), "drafts_blocked": blocked, "drafts_passed": len(checks) - blocked,
        "blocked_by_rule": dict(sorted(failed_rules.items())),
        "replies_blocked_language": act["reply_blocked_language"],
        "injections_flagged": sum(inj.values()), "injection_sources": dict(inj),
        "t3_refusals": sum(t3.values()), "t3_by_tool": dict(t3),
        "invalid_or_unknown_tool_refusals": _count(entries, lambda e: e["action"].startswith(("refused_invalid_args:", "refused_unknown_tool"))),
        "approvals": act["approve_order"] + act["approve_report"], "rejections": act["reject_ticket"],
        "refused_approvals": _count(entries, lambda e: e["action"].startswith("refused_approve")),
        "ledger_commands": act["ledger_command"], "ledger_confirmed": act["ledger_confirm"],
        "ledger_rejected": act["ledger_reject"],
        "translations": act["translate"], "knowledge_searches": act["knowledge_search"],
        "llm_fallbacks": act["llm_fallback_to_mock"], "documents_uploaded": act["document_uploaded"],
    }


def _findings(m: dict, chain: dict, lang: str) -> list[dict]:
    t = TEXT[lang]
    out = []

    def add(sev, text, article=None):
        out.append({"severity": sev, "text": text, "article": article})

    if not m["entries"]:
        add("info", t["no_activity"])
        return out
    if m["compliance_checks"]:
        if m["drafts_blocked"]:
            rules = ", ".join(f"{r} x{n}" for r, n in m["blocked_by_rule"].items()) or "-"
            add("ok", t["blocked"].format(blocked=m["drafts_blocked"], total=m["compliance_checks"], rules=rules), "第十八条")
        else:
            add("ok", t["all_passed"].format(total=m["compliance_checks"]), "第十八条")
    if m["replies_blocked_language"]:
        add("ok", t["reply_blocked"].format(n=m["replies_blocked_language"]), "第二十二条")
    if m["injections_flagged"]:
        src = ", ".join(f"{k} x{v}" for k, v in m["injection_sources"].items())
        add("ok", t["injection"].format(n=m["injections_flagged"], sources=src), None)
    if m["t3_refusals"]:
        tools = ", ".join(f"{k} x{v}" for k, v in m["t3_by_tool"].items())
        add("ok", t["t3"].format(n=m["t3_refusals"], tools=tools), None)
    if m["invalid_or_unknown_tool_refusals"]:
        add("ok", t["invalid"].format(n=m["invalid_or_unknown_tool_refusals"]), None)
    if m["approvals"] or m["rejections"] or m["refused_approvals"]:
        add("ok", t["approvals"].format(a=m["approvals"], r=m["rejections"], x=m["refused_approvals"]), None)
    if m["refused_approvals"]:
        add("review", t["refused_approvals"].format(n=m["refused_approvals"]), None)
    if m["ledger_commands"]:
        add("ok", t["ledger"].format(n=m["ledger_commands"], c=m["ledger_confirmed"], r=m["ledger_rejected"]), None)
    if m["llm_fallbacks"]:
        add("review", t["fallback"].format(n=m["llm_fallbacks"]), None)
    if chain.get("valid"):
        add("ok", t["chain_ok"].format(n=chain["checked"], head=chain["head"][:12]), "第三十二条")
    else:
        add("high", t["chain_bad"].format(at=chain.get("broken_at")), "第三十条")
    return out


def _evidence(m: dict, article: str) -> int | None:
    return {
        "第六条": m["profile_answers"], "第十八条": m["compliance_checks"], "第二十条": m["drafts_blocked"],
        "第二十一条": m["profiles_invalidated"] + m["profile_answers"], "第二十二条": m["replies_blocked_language"],
        "第二十三条": m["drafts_passed"], "第二十四条": m["drafts_passed"], "第三十二条": m["entries"],
    }.get(article)


def build(client_id: str | None = None, lang: str = "en") -> dict:
    lang = "zh" if lang == "zh" else "en"
    entries = audit.list_entries(client_id) if client_id else audit.list_entries()
    m = metrics(entries)
    chain = audit.verify()
    zh = lang == "zh"
    obligations = [{"article": art, "requirement": rz if zh else re_, "how": hz if zh else he, "evidence_count": _evidence(m, art)}
                   for art, re_, rz, he, hz in DUTIES]
    gaps = [{"article": a, "text": z if zh else e} for a, e, z in GAPS]
    return {
        "title": TEXT[lang]["title"], "lang": lang, "scope": TEXT[lang]["scope_client" if client_id else "scope_all"],
        "period": {"from": m["first_ts"], "to": m["last_ts"]}, "metrics": m,
        "chain": {"valid": chain["valid"], "entries_checked": chain.get("checked"), "head": chain.get("head"),
                  "broken_at": chain.get("broken_at")},
        "obligations": obligations, "findings": _findings(m, chain, lang), "gaps": gaps, "source": ARTICLE_URL,
    }


def to_markdown(r: dict) -> str:
    zh = r["lang"] == "zh"
    L = {"period": "期间" if zh else "Period", "scope": "范围" if zh else "Scope", "dut": "法定职责与本系统做法" if zh else "Duties and how the system addresses them",
         "ev": "证据数量" if zh else "Evidence", "find": "发现" if zh else "Findings", "gap": "未覆盖事项（如实说明）" if zh else "Not covered (stated honestly)"}
    out = [f"# {r['title']}", "", f"> {'教育演示，产品均为合成数据，不构成真实的投资建议。' if zh else 'Educational demo with synthetic products. Not real financial advice.'}", "",
           f"- {L['scope']}: {r['scope']}", f"- {L['period']}: {r['period']['from']} → {r['period']['to']}", f"- Source: {r['source']}", "",
           f"## {L['dut']}", "", f"| Art. | {'职责' if zh else 'Duty'} | {'做法' if zh else 'How'} | {L['ev']} |", "|---|---|---|---|"]
    for o in r["obligations"]:
        out.append(f"| {o['article']} | {o['requirement']} | {o['how']} | {o['evidence_count'] if o['evidence_count'] is not None else '-'} |")
    out += ["", f"## {L['find']}", ""] + [f"- [{f['severity']}] {f['text']}" + (f" ({f['article']})" if f["article"] else "") for f in r["findings"]]
    out += ["", f"## {L['gap']}", ""] + [f"- {g['article']}: {g['text']}" for g in r["gaps"]]
    return "\n".join(out) + "\n"
