"""Build the processed real-world datasets from the raw downloads in app/data/real/raw.

Run (dev only; needs `pip install xlrd` for the Damodaran .xls):  python -I scripts/build_real_data.py

Outputs (app/data/real/):
  returns_annual.csv          1928-2025 annual total returns, 7 US asset classes (Damodaran / NYU Stern)
  shiller_monthly.csv         monthly S&P 500, dividends, earnings, CPI, 10y rate since 1871 (Shiller, PDDL mirror)
  china_macro.csv             China CPI inflation, deposit/lending rate, GDP growth (World Bank, CC BY 4.0)
  suitability_zh.json         the 43 articles of the CSRC suitability measures (Chinese original, State Council Gazette)
  MANIFEST.json               source URL, license, retrieval date, sha256 of every raw and processed file

Raw files are untrusted data: they are only parsed here, never executed.
"""
import csv
import hashlib
import html
import json
import os
import re
from datetime import date

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "data", "real")
RAW = os.path.join(ROOT, "raw")
RETRIEVED = "2026-10-18"


def sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def write_csv(name: str, header: list, rows: list) -> str:
    path = os.path.join(ROOT, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


# ---------------------------------------------------------------------------------------------- Damodaran
def build_returns() -> str:
    import xlrd
    wb = xlrd.open_workbook(os.path.join(RAW, "damodaran", "histretSP.xls"))
    sh = wb.sheet_by_name("Returns by year")
    header = ["year", "sp500", "small_cap", "tbill_3m", "tbond_10y", "baa_corp", "real_estate", "gold"]
    rows = []
    for r in range(sh.nrows):
        v = sh.row_values(r)
        if isinstance(v[0], float) and 1928 <= v[0] <= 2100 and all(isinstance(x, float) for x in v[1:8]):
            rows.append([int(v[0])] + [round(x, 6) for x in v[1:8]])
    assert rows[0][0] == 1928 and len(rows) >= 98, "unexpected Damodaran layout"
    return write_csv("returns_annual.csv", header, rows)


# ---------------------------------------------------------------------------------------------- Shiller
def build_shiller() -> str:
    rows = []
    with open(os.path.join(RAW, "shiller_sp500", "data.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cpi, rate = float(r["Consumer Price Index"]), float(r["Long Interest Rate"])
            if cpi > 0 and rate > 0:  # the mirror appends price-only months at the end; keep complete months
                rows.append([r["Date"][:7], r["SP500"], r["Dividend"], r["Earnings"], r["Consumer Price Index"],
                             r["Long Interest Rate"]])
    return write_csv("shiller_monthly.csv", ["month", "sp500", "dividend", "earnings", "cpi", "long_rate"], rows)


# ---------------------------------------------------------------------------------------------- World Bank
def build_china() -> str:
    names = {"FP.CPI.TOTL.ZG": "cpi_inflation_pct", "FR.INR.DPST": "deposit_rate_pct",
             "FR.INR.LEND": "lending_rate_pct", "NY.GDP.MKTP.KD.ZG": "gdp_growth_pct"}
    table: dict[int, dict] = {}
    for ind, col in names.items():
        d = json.load(open(os.path.join(RAW, "worldbank_china", f"CHN_{ind}.json"), encoding="utf-8"))
        for r in d[1]:
            if r["value"] is not None:
                table.setdefault(int(r["date"]), {})[col] = round(float(r["value"]), 4)
    cols = list(names.values())
    rows = [[y] + [table[y].get(c, "") for c in cols] for y in sorted(table)]
    return write_csv("china_macro.csv", ["year"] + cols, rows)


# ---------------------------------------------------------------------------------------------- CSRC text
ART = re.compile(r"(?m)^(第[一二三四五六七八九十百]+条)\s*")


def build_suitability() -> str:
    t = open(os.path.join(RAW, "csrc", "gov_cn_gazette_2023_5_order202.html"), encoding="utf-8", errors="ignore").read()
    t = re.sub(r"(?is)<(script|style).*?</\1>", "", t)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    t = re.sub(r"[ \t　\xa0]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    start = t.index("证券期货投资者适当性管理办法\n（2016年5月26日")
    body = t[start:]
    end = body.index("中国政府网")  # page footer boilerplate follows the last article
    body = body[:end]
    parts = ART.split(body)
    articles = []
    for i in range(1, len(parts) - 1, 2):
        text = re.sub(r"\s+", " ", parts[i + 1]).strip()
        text = text.split(" 附件")[0].strip()  # the gazette page appends the next annex and site links after the last article
        articles.append({"article": parts[i], "text": text})
    assert len(articles) == 43 and articles[0]["article"] == "第一条" and articles[-1]["article"] == "第四十三条"
    doc = {"title": "证券期货投资者适当性管理办法", "title_en": "Measures for the Suitability Management of Securities and Futures Investors",
           "issuer": "中国证券监督管理委员会", "consolidated": "2016 (first issued), amended 2020-10-30 and 2022-08-12",
           "source_url": "https://www.gov.cn/gongbao/content/2023/content_5742209.htm", "articles": articles}
    path = os.path.join(ROOT, "suitability_zh.json")
    json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return path


SOURCES = {
    "returns_annual.csv": {
        "raw": "raw/damodaran/histretSP.xls", "title": "Historical Returns on Stocks, Bonds and Bills: 1928-2025",
        "author": "Aswath Damodaran, NYU Stern", "url": "https://www.stern.nyu.edu/~adamodar/pc/datasets/histretSP.xls",
        "page": "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histretSP.html",
        "license": "Not stated on the page: used with attribution for an educational demo; confirm before any redistribution",
        "used_for": "calibrate return, volatility and correlation of asset classes; real historical stress episodes"},
    "shiller_monthly.csv": {
        "raw": "raw/shiller_sp500/data.csv", "title": "S&P 500 monthly data incl. dividend, earnings, CPI and 10-year rate (Shiller)",
        "author": "Robert Shiller (Yale), via the Open Knowledge Foundation datasets mirror",
        "url": "https://raw.githubusercontent.com/datasets/s-and-p-500/main/data/data.csv",
        "page": "https://datahub.io/core/s-and-p-500", "license": "ODC-PDDL-1.0 (public domain dedication)",
        "used_for": "real inflation and interest-rate episodes for the rate and inflation stress scenarios; valuation context"},
    "china_macro.csv": {
        "raw": "raw/worldbank_china/", "title": "China: CPI inflation, deposit rate, lending rate, GDP growth (annual)",
        "author": "World Bank Open Data", "url": "https://api.worldbank.org/v2/country/CHN/indicator/{FP.CPI.TOTL.ZG,FR.INR.DPST,FR.INR.LEND,NY.GDP.MKTP.KD.ZG}",
        "page": "https://data.worldbank.org/country/china", "license": "CC BY 4.0",
        "used_for": "China-specific inflation and cash-return context in explanations and the inflation scenario"},
    "suitability_zh.json": {
        "raw": "raw/csrc/gov_cn_gazette_2023_5_order202.html",
        "title": "Measures for the Suitability Management of Securities and Futures Investors (consolidated, Chinese original)",
        "author": "China Securities Regulatory Commission (CSRC Order No. 130, amended by Order No. 202)",
        "url": "https://www.gov.cn/gongbao/content/2023/content_5742209.htm", "page": "https://www.gov.cn/gongbao/content/2023/content_5742209.htm",
        "license": "PRC laws and regulations are not protected by copyright (PRC Copyright Law, Art. 5); official State Council Gazette text",
        "used_for": "knowledge base for retrieval: compliance explanations cite the real article"},
}


def main():
    outs = {"returns_annual.csv": build_returns(), "shiller_monthly.csv": build_shiller(),
            "china_macro.csv": build_china(), "suitability_zh.json": build_suitability()}
    manifest = {"retrieved": RETRIEVED, "generated": date.today().isoformat(),
                "note": "Real, public data used to calibrate and ground the demo. Products and clients stay synthetic.",
                "datasets": []}
    for name, meta in SOURCES.items():
        raw = os.path.join(ROOT, meta["raw"])
        raw_files = ([os.path.join(raw, f) for f in sorted(os.listdir(raw))] if os.path.isdir(raw) else [raw])
        manifest["datasets"].append({
            "file": name, "sha256": sha(outs[name]),
            "raw_files": {os.path.relpath(p, ROOT).replace("\\", "/"): sha(p) for p in raw_files},
            **{k: v for k, v in meta.items() if k != "raw"}})
    json.dump(manifest, open(os.path.join(ROOT, "MANIFEST.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("built", ", ".join(outs))


if __name__ == "__main__":
    main()
