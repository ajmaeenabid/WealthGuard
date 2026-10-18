"""Vector store, knowledge base over the real CSRC regulation, regulatory basis for rules, and the search API/tool."""
import json
import os

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import knowledge, vectorstore
from app.agent.tools import Ctx
from app.compliance import banned_phrases
from app.main import app
from app.security import tiers

c = TestClient(app)
REAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "data", "real")


def refs(hits):
    return [h["ref"] for h in hits]


# ------------------------------------------------------------------------------------------ embedder and store
def test_tokens_are_deterministic_and_handle_both_scripts():
    assert vectorstore.tokens("Complex products") == vectorstore.tokens("complex PRODUCTS")
    t = vectorstore.tokens("适当性管理")
    assert "适当" in t and "适当性" in t and "管理" in t
    assert "product" in vectorstore.tokens("products") and vectorstore.tokens("a b") == []   # plural stripped, 1-char skipped


def test_build_search_persist_and_filters():
    items = [{"id": f"x{i}", "source": "a" if i % 2 else "b", "ref": f"r{i}", "lang": "en", "title": t, "text": t, "url": ""}
             for i, t in enumerate(["gold prices rise with inflation", "bond yields and interest rates",
                                    "equity index crash in 2008", "cash deposit rate in China"])]
    assert vectorstore.build(items, "fp1") == 4 and vectorstore.count() == 4 and vectorstore.fingerprint() == "fp1"
    hits = vectorstore.search("interest rate on bonds", k=2)
    assert hits[0]["ref"] == "r1" and len(hits) == 2 and hits[0]["score"] >= hits[1]["score"]
    assert all(h["source"] == "a" for h in vectorstore.search("interest rate", k=4, source="a"))
    vectorstore._CACHE.clear()                       # force a reload from SQLite: the vectors really persisted
    assert vectorstore.search("2008 crash", k=1)[0]["ref"] == "r2"
    assert vectorstore.search("", k=3) == [] and vectorstore.search("zzzzqqq", k=3, min_score=0.5) == []
    assert vectorstore.build(items[:2], "fp2") == 2 and vectorstore.count() == 2      # rebuild replaces, never duplicates


def test_stored_vectors_are_unit_length_float32():
    knowledge.ensure_index()
    rows, mat, idf = vectorstore._load()
    assert mat.dtype == np.float32 and mat.shape == (len(rows), vectorstore.DIM)
    assert np.allclose(np.linalg.norm(mat, axis=1), 1.0, atol=1e-4)


# ------------------------------------------------------------------------------------------ knowledge base contents
def test_index_contains_every_source_and_is_idempotent():
    assert knowledge.ensure_index() == 61
    assert knowledge.ensure_index() == 61 and vectorstore.count() == 61
    for src, n in {"csrc_suitability": 43, "data_sources": 4, "market_episodes": 6, "wealthguard_rules": 8}.items():
        assert vectorstore.count(src) == n, src


def test_stale_index_is_rebuilt(monkeypatch):
    knowledge.ensure_index()
    monkeypatch.setattr(knowledge, "_fingerprint", lambda its: "changed")
    knowledge.ensure_index()
    assert vectorstore.fingerprint() == "changed" and vectorstore.count() == 61


@pytest.mark.parametrize("query,expected,top1", [
    ("Can a retail customer buy a complex structured product?", "第十六条", False),
    ("What must the firm disclose about losing principal?", "第二十三条", True),
    ("Is it allowed to promise guaranteed returns?", "第二十二条", True),
    ("What if the client insists on buying something above their risk tolerance?", "第十九条", True),
    ("elderly investors special protection", "第七条", True),
    ("penalties for firms that break the rules", "第三十七条", True),
    ("什么情况下可以转化为专业投资者", "第十一条", True),
])
def test_english_and_chinese_questions_reach_the_right_article(query, expected, top1):
    hits = knowledge.search(query, k=3, source="csrc_suitability")
    assert (refs(hits)[0] == expected) if top1 else (expected in refs(hits)), (query, refs(hits))


def test_non_regulation_questions_reach_data_sources_and_episodes():
    assert knowledge.search("where does the 2008 crash number come from", k=1)[0]["ref"] == "crash_2008"
    top = knowledge.search("which license applies to the Shiller data", k=1)[0]
    assert top["ref"] == "shiller_monthly.csv" and "PDDL" in top["text"]


def test_glossary_expands_only_matching_english_phrases():
    assert "适当性" in knowledge.expand("suitability rules") and "专业投资者" in knowledge.expand("Professional investor")
    assert knowledge.expand("zzz qqq") == "zzz qqq"


def test_article_numbers_convert():
    assert [knowledge.article_number(x) for x in ["第一条", "第九条", "第十条", "第十六条", "第二十条", "第三十七条", "第四十三条"]] == \
           [1, 9, 10, 16, 20, 37, 43]


# ------------------------------------------------------------------------------------------ regulatory basis for rules
@pytest.mark.parametrize("rule,article_no", [("R1", 18), ("R3", 16), ("R4", 16), ("R5", 20), ("R6", 23), ("R7", 22)])
def test_rules_link_to_the_supporting_article(rule, article_no):
    b = knowledge.basis_for_rule(rule)
    assert b["article_no"] == article_no and b["url"].startswith("https://www.gov.cn/") and b["snippet"]


def test_rules_without_a_matching_article_show_no_basis():
    assert knowledge.basis_for_rule("R2") is None and knowledge.basis_for_rule("R8") is None
    assert knowledge.basis_for_rule("nope") is None


# ------------------------------------------------------------------------------------------ data hygiene
def test_regulation_text_is_clean_and_complete():
    d = json.load(open(os.path.join(REAL, "suitability_zh.json"), encoding="utf-8"))
    a = d["articles"]
    assert a[-1]["text"] == "本办法自2017年7月1日起施行。"
    assert not any(x in art["text"] for art in a for x in ("链接", "附件", "相关稿件", "政府网"))


def test_quoting_the_regulation_never_trips_the_language_rule():
    d = json.load(open(os.path.join(REAL, "suitability_zh.json"), encoding="utf-8"))
    assert [art["article"] for art in d["articles"] if banned_phrases(art["text"])] == []   # Art. 4 denies a guarantee
    assert banned_phrases("这款产品保证收益") and banned_phrases("我们保证收益，产品本身不代表任何保证。")


# ------------------------------------------------------------------------------------------ API, tool, chat, state
def test_search_api_returns_results_and_is_audited():
    cid = c.post("/api/session", json={"persona_id": "persona_li"}).json()["client_id"]
    r = c.get("/api/knowledge/search", params={"q": "risk warning disclosure", "k": 2, "client_id": cid})
    assert r.status_code == 200 and len(r.json()["results"]) == 2
    assert "knowledge_search" in [e["action"] for e in c.get("/api/audit", params={"client_id": cid}).json()]
    assert c.get("/api/audit/verify").json()["valid"]


@pytest.mark.parametrize("params,code", [
    ({"q": "x"}, 422), ({"q": "risk", "k": 9}, 422), ({"q": "risk", "source": "secrets"}, 422),
    ({"q": "risk", "client_id": "nope"}, 404), ({}, 422),
])
def test_search_api_validation(params, code):
    assert c.get("/api/knowledge/search", params=params).status_code == code


def test_search_tool_is_t0_and_validates_arguments():
    ctx = Ctx("client_x")
    assert tiers.tier_of("search_knowledge") == "T0"
    ok = tiers.execute("search_knowledge", {"query": "complex products", "k": 2}, ctx)
    assert len(ok["results"]) == 2 and ok["results"][0]["url"]
    for bad in [{"query": "x"}, {"query": "ok query", "k": 99}, {"query": "ok query", "source": "secrets"},
                {"query": "ok query", "extra": 1}]:
        assert tiers.execute("search_knowledge", bad, ctx).get("refused") is True


def test_chat_answers_regulation_questions_with_a_citation():
    cid = c.post("/api/session", json={"persona_id": "persona_li"}).json()["client_id"]
    out = c.post("/api/chat", json={"client_id": cid, "message":
                 "What does the CSRC regulation say the firm must disclose about principal loss?"}).json()
    assert "第二十三条" in out["reply"] and "Not real financial advice" in out["reply"]
    assert any(t["tool"] == "search_knowledge" and t["tier"] == "T0" for t in out["trace"])


def test_chat_quoting_the_article_that_denies_guarantees_is_not_blocked():
    cid = c.post("/api/session", json={"persona_id": "persona_li"}).json()["client_id"]
    out = c.post("/api/chat", json={"client_id": cid, "message":
                 "Under the regulation, does the firm's advice guarantee returns, and who bears the investment risk?"}).json()
    assert "can't share that wording" not in out["reply"] and "第四条" in out["reply"]   # Art. 4 quoted, not blocked


def test_state_includes_regulatory_basis_after_compliance():
    cid = c.post("/api/session", json={"persona_id": "persona_li"}).json()["client_id"]
    c.post("/api/profile", json={"client_id": cid, "answers": {"loss_reaction": "sell_some", "income_stability": "stable",
                                                                "liquidity_need_pct": 10}})
    c.post("/api/allocation", json={"client_id": cid})
    basis = c.get("/api/state", params={"client_id": cid}).json()["regulatory_basis"]
    assert basis["R3"]["article_no"] == 16 and basis["R6"]["article_no"] == 23 and "R2" not in basis
    assert all(v["url"].startswith("https://") and v["snippet"] for v in basis.values())


def test_ui_has_the_search_card_and_basis_hook():
    html = c.get("/").text
    for el in ['id="kbCard"', 'id="kbQuery"', 'id="kbSource"', 'id="kbGo"', 'id="kbResults"']:
        assert el in html
    assert "basisHtml" in c.get("/static/app.js").text


def test_chat_regulation_questions_are_answered_from_the_regulation_not_our_rule_notes():
    cid = c.post("/api/session", json={"persona_id": "persona_li"}).json()["client_id"]
    out = c.post("/api/chat", json={"client_id": cid, "message": "What does the law say about elderly investors?"}).json()
    assert "CSRC Suitability Management Measures" in out["reply"]
