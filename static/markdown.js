// A small, safe Markdown renderer for chat replies: tables, bold/italic, inline code, headings, bullet and numbered lists, paragraphs.
// Everything is HTML-escaped FIRST and only a fixed set of tags is produced, so a reply can never inject markup or script. No links or images.
(function () {
  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,;:!?]|$)/g, "$1<em>$2</em>");
  const isSep = (l) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l) && l.includes("-");
  const isRow = (l) => /^\s*\|.*\|?\s*$/.test(l) && (l.match(/\|/g) || []).length >= 2;
  const cells = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  const numeric = (c) => /^[-+]?[\d.,\s]+(%|x)?$|^[-+]?[$¥৳€£]\s?[\d.,]+$/.test(c.trim());

  function table(rows) {
    const head = cells(rows[0]), aligns = cells(rows[1]).map((c) => (/^:-*:$/.test(c) ? "center" : /-:$/.test(c) ? "right" : ""));
    const body = rows.slice(2).map(cells);
    const numCol = head.map((_, i) => body.length > 0 && body.every((r) => numeric(r[i] || "")));
    const al = (i) => (aligns[i] || (numCol[i] ? "right" : ""));
    const th = head.map((c, i) => `<th${al(i) ? ` class="a-${al(i)}"` : ""}>${inline(c)}</th>`).join("");
    const tr = body.map((r) => `<tr>${head.map((_, i) => `<td${al(i) ? ` class="a-${al(i)}"` : ""}>${inline(r[i] || "")}</td>`).join("")}</tr>`).join("");
    return `<div class="md-table"><table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
  }

  function render(text) {
    const lines = String(text || "").replace(/\r/g, "").split("\n");
    const out = [];
    let i = 0, para = [];
    const flush = () => { if (para.length) { out.push(`<p>${para.map(inline).join("<br>")}</p>`); para = []; } };
    while (i < lines.length) {
      const l = lines[i];
      if (!l.trim()) { flush(); i++; continue; }
      if (isRow(l) && i + 1 < lines.length && isSep(lines[i + 1])) {           // a table: header, separator, then rows
        flush();
        const rows = [l, lines[i + 1]];
        i += 2;
        while (i < lines.length && isRow(lines[i]) && lines[i].trim()) rows.push(lines[i++]);
        out.push(table(rows));
        continue;
      }
      let m;
      if ((m = l.match(/^\s*(#{1,4})\s+(.*)$/))) { flush(); out.push(`<h4>${inline(m[2])}</h4>`); i++; continue; }
      if (/^\s*[-*•]\s+/.test(l)) {
        flush();
        const items = [];
        while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*•]\s+/, ""));
        out.push(`<ul>${items.map((x) => `<li>${inline(x)}</li>`).join("")}</ul>`);
        continue;
      }
      if (/^\s*\d+[.)]\s+/.test(l)) {
        flush();
        const items = [];
        while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*\d+[.)]\s+/, ""));
        out.push(`<ol>${items.map((x) => `<li>${inline(x)}</li>`).join("")}</ol>`);
        continue;
      }
      para.push(l.trim()); i++;
    }
    flush();
    return out.join("");
  }

  // Plain text for reading aloud and for copying: no pipes, asterisks or hashes.
  function plain(text) {
    const lines = String(text || "").replace(/\r/g, "").split("\n");
    const res = [];
    for (let i = 0; i < lines.length; i++) {
      const l = lines[i];
      if (isSep(l) && i > 0 && isRow(lines[i - 1])) continue;
      if (isRow(l)) { res.push(cells(l).join(", ")); continue; }
      res.push(l.replace(/\*\*([^*]+)\*\*/g, "$1").replace(/`([^`]+)`/g, "$1").replace(/^\s*#{1,4}\s+/, "").replace(/^\s*[-*•]\s+/, ""));
    }
    return res.join("\n");
  }

  const api = { render, plain, esc };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window !== "undefined") window.WGMarkdown = api;
})();
