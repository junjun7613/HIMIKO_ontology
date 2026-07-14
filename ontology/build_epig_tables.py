#!/usr/bin/env python3
"""
論文添付用の表 (HTML) を生成するビルダー — epig 版。

epig_ontology.ttl から以下 3 表を出力する:
  - クラス表    : QName, ラベル(ja), 上位クラス, 定義(ja)
  - オブジェクトプロパティ表: QName, ラベル(ja), ドメイン, レンジ, 上位プロパティ, Func, 定義(ja)
  - データプロパティ表   : QName, ラベル(ja), ドメイン, レンジ, Func, 定義(ja)

owl:deprecated true が付いたエントリは除外する。

出力: ontology/figs/epig_tables.html

使用方法:
    python build_epig_tables.py
    python build_epig_tables.py -o /tmp/epig_tables.html
"""

import argparse
import html
from pathlib import Path

from rdflib import Graph, URIRef, Literal, BNode
from rdflib.namespace import RDF, RDFS, OWL


SCRIPT_DIR = Path(__file__).parent
EPIG_TTL = SCRIPT_DIR / "epig_ontology.ttl"

EPIG_NS = "http://epigraphic-careers.org/ontology#"

COMMON_PREFIXES = {
    "rdf":     "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs":    "http://www.w3.org/2000/01/rdf-schema#",
    "owl":     "http://www.w3.org/2002/07/owl#",
    "xsd":     "http://www.w3.org/2001/XMLSchema#",
    "dcterms": "http://purl.org/dc/terms/",
    "prov":    "http://www.w3.org/ns/prov#",
    "schema":  "https://schema.org/",
    "skos":    "http://www.w3.org/2004/02/skos/core#",
    "foaf":    "http://xmlns.com/foaf/0.1/",
    "hmkp":    "urn:himiko:ontology:physical:",
    "hmki":    "urn:himiko:ontology:intrinsic:",
    "hmkia":   "urn:himiko:ontology:interpretation:",
    "hmke":    "urn:himiko:ontology:extrinsic:",
    "epig":    EPIG_NS,
}


def qname(uri) -> str:
    if isinstance(uri, BNode):
        return f"_:{uri}"
    s = str(uri)
    matches = sorted(
        ((pref, ns) for pref, ns in COMMON_PREFIXES.items() if s.startswith(ns)),
        key=lambda x: -len(x[1]),
    )
    if matches:
        pref, ns = matches[0]
        return f"{pref}:{s[len(ns):]}"
    return s


def is_deprecated(g: Graph, s) -> bool:
    return (s, OWL.deprecated, Literal(True)) in g


def get_label_ja(g: Graph, s) -> str:
    for _, _, o in g.triples((s, RDFS.label, None)):
        if isinstance(o, Literal) and (o.language or "") == "ja":
            return str(o)
    for _, _, o in g.triples((s, RDFS.label, None)):
        if isinstance(o, Literal):
            return str(o)
    return ""


def get_comment_ja(g: Graph, s) -> str:
    for _, _, o in g.triples((s, RDFS.comment, None)):
        if isinstance(o, Literal) and (o.language or "") == "ja":
            return str(o)
    for _, _, o in g.triples((s, RDFS.comment, None)):
        if isinstance(o, Literal):
            return str(o)
    return ""


def rdf_list(g: Graph, head):
    items = []
    while head and head != RDF.nil:
        first = g.value(head, RDF.first)
        if first is not None:
            items.append(first)
        head = g.value(head, RDF.rest)
    return items


def format_dr(g: Graph, s, predicate) -> str:
    parts = []
    for _, _, o in g.triples((s, predicate, None)):
        if isinstance(o, BNode):
            union = list(g.objects(o, OWL.unionOf))
            if union:
                items = [qname(item) for item in rdf_list(g, union[0])]
                parts.append("(" + " ∪ ".join(items) + ")")
            else:
                parts.append("匿名クラス")
        else:
            parts.append(qname(o))
    return ", ".join(parts)


def collect_entities(g: Graph):
    classes, ops, dps = [], [], []
    for s in g.subjects(RDF.type, OWL.Class):
        if isinstance(s, BNode) or not str(s).startswith(EPIG_NS):
            continue
        if is_deprecated(g, s):
            continue
        classes.append(s)
    for s in g.subjects(RDF.type, OWL.ObjectProperty):
        if isinstance(s, BNode) or not str(s).startswith(EPIG_NS):
            continue
        if is_deprecated(g, s):
            continue
        ops.append(s)
    for s in g.subjects(RDF.type, OWL.DatatypeProperty):
        if isinstance(s, BNode) or not str(s).startswith(EPIG_NS):
            continue
        if is_deprecated(g, s):
            continue
        dps.append(s)
    for lst in (classes, ops, dps):
        lst.sort(key=lambda u: str(u))
    return classes, ops, dps


CSS = """
:root {
  --fg: #1f2937;
  --muted: #6b7280;
  --border: #cbd5e1;
  --border-light: #e5e7eb;
  --thead-bg: #f3f4f6;
  --code-bg: #f3f4f6;
  --accent: #0ea5e9;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 32px 40px 48px;
  font-family: "Hiragino Mincho ProN", "Yu Mincho", "Noto Serif JP", serif;
  color: var(--fg);
  background: #fff;
  line-height: 1.55;
  font-size: 12px;
}
h1 { font-size: 20px; margin: 0 0 4px; }
.subtitle { color: var(--muted); margin: 0 0 24px; font-size: 13px; }
h2 {
  font-size: 15px;
  margin: 32px 0 10px;
  padding: 6px 10px;
  color: #fff;
  border-radius: 3px;
  background: var(--accent);
}
h3 {
  font-size: 13px;
  margin: 18px 0 6px;
  color: var(--fg);
  font-weight: 700;
}
.section-intro { color: var(--muted); font-size: 11.5px; margin: -4px 0 10px; }

table.ttable {
  border-collapse: collapse;
  width: 100%;
  font-size: 11px;
  margin: 0 0 14px;
  page-break-inside: auto;
}
table.ttable thead th {
  background: var(--thead-bg);
  border-top: 1.5px solid var(--fg);
  border-bottom: 1px solid var(--fg);
  padding: 5px 8px;
  text-align: left;
  vertical-align: bottom;
  font-weight: 700;
  font-size: 11px;
  white-space: nowrap;
}
table.ttable tbody td {
  border-bottom: 1px solid var(--border-light);
  padding: 5px 8px;
  vertical-align: top;
}
table.ttable tbody tr:last-child td {
  border-bottom: 1.5px solid var(--fg);
}
table.ttable code {
  font-family: "SF Mono", ui-monospace, Menlo, Consolas, monospace;
  background: var(--code-bg);
  padding: 1px 4px;
  border-radius: 2px;
  font-size: 10.5px;
  white-space: nowrap;
}
table.ttable td.qname { white-space: nowrap; }
table.ttable td.def { line-height: 1.5; }
table.ttable td.dr { font-size: 10.5px; }
table.ttable .none { color: var(--muted); }
table.ttable .func {
  display: inline-block;
  padding: 1px 5px;
  border: 1px solid var(--muted);
  border-radius: 2px;
  font-size: 9.5px;
  color: var(--muted);
}

table.summary {
  border-collapse: collapse;
  margin: 0 0 24px;
  font-size: 11.5px;
}
table.summary th, table.summary td {
  border: 1px solid var(--border);
  padding: 4px 10px;
  text-align: center;
}
table.summary th { background: var(--thead-bg); font-weight: 700; }
table.summary td.name { text-align: left; }

footer { margin-top: 32px; color: var(--muted); font-size: 10.5px; }

@page { size: A4; margin: 20mm 15mm; }
@media print {
  body { padding: 0; }
  h2 { page-break-after: avoid; }
  h3 { page-break-after: avoid; }
  table.ttable { page-break-inside: auto; }
  table.ttable tr { page-break-inside: avoid; page-break-after: auto; }
  table.ttable thead { display: table-header-group; }
}
"""


def esc(s: str) -> str:
    return html.escape(s or "")


def none_cell(text: str = "—") -> str:
    return f'<span class="none">{text}</span>'


def render_class_table(g: Graph, items):
    if not items:
        return ""
    rows = []
    for s in items:
        qn = qname(s)
        label = get_label_ja(g, s)
        comment = get_comment_ja(g, s)
        sup = format_dr(g, s, RDFS.subClassOf)
        rows.append(
            f'<tr>'
            f'<td class="qname"><code>{esc(qn)}</code></td>'
            f'<td>{esc(label) or none_cell()}</td>'
            f'<td class="dr">{esc(sup) if sup else none_cell()}</td>'
            f'<td class="def">{esc(comment) or none_cell()}</td>'
            f'</tr>'
        )
    return (
        f'<h3>クラス (Classes) — {len(items)} 件</h3>\n'
        f'<table class="ttable">\n'
        f'  <thead><tr>'
        f'<th style="width:20%">QName</th>'
        f'<th style="width:14%">ラベル</th>'
        f'<th style="width:20%">上位クラス</th>'
        f'<th>定義</th>'
        f'</tr></thead>\n'
        f'  <tbody>\n{chr(10).join(rows)}\n  </tbody>\n'
        f'</table>'
    )


def render_property_table(g: Graph, items, kind_label: str):
    if not items:
        return ""
    rows = []
    for s in items:
        qn = qname(s)
        label = get_label_ja(g, s)
        comment = get_comment_ja(g, s)
        dom = format_dr(g, s, RDFS.domain)
        rng = format_dr(g, s, RDFS.range)
        sup = format_dr(g, s, RDFS.subPropertyOf)
        is_functional = (s, RDF.type, OWL.FunctionalProperty) in g
        func_cell = '<span class="func">Func</span>' if is_functional else none_cell()
        rows.append(
            f'<tr>'
            f'<td class="qname"><code>{esc(qn)}</code></td>'
            f'<td>{esc(label) or none_cell()}</td>'
            f'<td class="dr">{esc(dom) if dom else none_cell()}</td>'
            f'<td class="dr">{esc(rng) if rng else none_cell()}</td>'
            f'<td class="dr">{esc(sup) if sup else none_cell()}</td>'
            f'<td style="text-align:center">{func_cell}</td>'
            f'<td class="def">{esc(comment) or none_cell()}</td>'
            f'</tr>'
        )
    return (
        f'<h3>{kind_label} — {len(items)} 件</h3>\n'
        f'<table class="ttable">\n'
        f'  <thead><tr>'
        f'<th style="width:18%">QName</th>'
        f'<th style="width:12%">ラベル</th>'
        f'<th style="width:12%">ドメイン</th>'
        f'<th style="width:12%">レンジ</th>'
        f'<th style="width:12%">上位プロパティ</th>'
        f'<th style="width:5%">属性</th>'
        f'<th>定義</th>'
        f'</tr></thead>\n'
        f'  <tbody>\n{chr(10).join(rows)}\n  </tbody>\n'
        f'</table>'
    )


def build_html(g: Graph) -> str:
    cls_list, op_list, dp_list = collect_entities(g)

    total = len(cls_list) + len(op_list) + len(dp_list)
    summary_row = (
        f'<tr>'
        f'<td class="name"><code>epig</code> — 碑文経歴オントロジー</td>'
        f'<td>{len(cls_list)}</td><td>{len(op_list)}</td><td>{len(dp_list)}</td>'
        f'<td><strong>{total}</strong></td>'
        f'</tr>'
    )

    cls_html = render_class_table(g, cls_list)
    op_html = render_property_table(g, op_list, "オブジェクトプロパティ (Object Properties)")
    dp_html = render_property_table(g, dp_list, "データプロパティ (Datatype Properties)")

    body_parts = [
        f'<h2>epig: 碑文経歴オントロジー <code style="background:rgba(255,255,255,0.2); '
        f'color:#fff; padding:1px 6px; border-radius:2px; font-size:11px">epig:</code></h2>',
    ]
    for h in (cls_html, op_html, dp_html):
        if h:
            body_parts.append(h)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>epig オントロジー クラス・プロパティ一覧表</title>
<style>{CSS}</style>
</head>
<body>
<h1>epig オントロジー クラス・プロパティ一覧表</h1>
<p class="subtitle">Epigraphic Careers Ontology — 論文添付用リファレンス表 (deprecated を除く)</p>

<table class="summary">
  <thead><tr>
    <th>オントロジー</th>
    <th>クラス</th>
    <th>オブジェクトプロパティ</th>
    <th>データプロパティ</th>
    <th>合計</th>
  </tr></thead>
  <tbody>
{summary_row}
  </tbody>
</table>

<p class="section-intro">
凡例 — <strong>QName</strong>: 修飾名 (プレフィックス:ローカル名)。
<strong>ドメイン/レンジ</strong>: <code>(A ∪ B)</code> は <code>owl:unionOf</code> による直和。
<strong>属性</strong>: <span class="func">Func</span> は <code>owl:FunctionalProperty</code> (関数的プロパティ) を示す。
<code>owl:deprecated true</code> のエントリは除外している。
外部語彙のプレフィックス (rdfs, owl, xsd, prov, foaf, schema, skos, hmkp, hmki, hmkia) は
省略形のまま表記する。
</p>

{chr(10).join(body_parts)}

<footer>
自動生成元: <code>ontology/epig_ontology.ttl</code> · ビルダー: <code>ontology/build_epig_tables.py</code>
</footer>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "-o", "--output",
        default=str(SCRIPT_DIR / "figs" / "epig_tables.html"),
        help="出力 HTML パス (デフォルト: ontology/figs/epig_tables.html)",
    )
    args = ap.parse_args()

    g = Graph()
    g.parse(EPIG_TTL, format="turtle")
    print(f"Loaded {len(g)} triples from {EPIG_TTL.name}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_html(g), encoding="utf-8")
    print(f"→ Wrote {out_path} ({out_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
