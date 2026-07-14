#!/usr/bin/env python3
"""
論文添付用の表 (HTML) を生成するビルダー。

HIMIKO オントロジー 4 レイヤー (hmkp, hmki, hmke, hmkia) について、
レイヤーごとに以下 3 つの表を出力する:
  - クラス表    : QName, ラベル(ja), 上位クラス, 定義(ja)
  - オブジェクトプロパティ表: QName, ラベル(ja), ドメイン, レンジ, 上位プロパティ, Func, 定義(ja)
  - データプロパティ表   : QName, ラベル(ja), ドメイン, レンジ, Func, 定義(ja)

出力: ontology/figs/himiko_tables.html (印刷/PDF化を想定したスタンドアロン HTML)

使用方法:
    python build_tables.py
    python build_tables.py -o /tmp/tables.html
"""

import argparse
import html
from pathlib import Path
from collections import defaultdict

from rdflib import Graph, URIRef, Literal, BNode
from rdflib.namespace import RDF, RDFS, OWL, XSD


SCRIPT_DIR = Path(__file__).parent
TTL_DIR = SCRIPT_DIR / "hmk_owl"

LAYERS = [
    {
        "prefix": "hmkp",
        "uri": "urn:himiko:ontology:physical:",
        "file": "himiko_physical.ttl",
        "title_ja": "史料物理層",
        "color": "#3b82f6",
    },
    {
        "prefix": "hmktei",
        "uri": "urn:himiko:ontology:physical:tei:",
        "file": "himiko_physical_tei.ttl",
        "title_ja": "史料物理層 — TEI 変換プロファイル",
        "color": "#60a5fa",
    },
    {
        "prefix": "hmki",
        "uri": "urn:himiko:ontology:intrinsic:",
        "file": "himiko_intrinsic.ttl",
        "title_ja": "史料内在知識層",
        "color": "#f59e0b",
    },
    {
        "prefix": "hmke",
        "uri": "urn:himiko:ontology:extrinsic:",
        "file": "himiko_extrinsic.ttl",
        "title_ja": "外在知識層",
        "color": "#10b981",
    },
    {
        "prefix": "hmkia",
        "uri": "urn:himiko:ontology:interpretation:",
        "file": "himiko_interpretation.ttl",
        "title_ja": "解釈行為層",
        "color": "#8b5cf6",
    },
]

COMMON_PREFIXES = {
    "rdf":     "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs":    "http://www.w3.org/2000/01/rdf-schema#",
    "owl":     "http://www.w3.org/2002/07/owl#",
    "xsd":     "http://www.w3.org/2001/XMLSchema#",
    "dcterms": "http://purl.org/dc/terms/",
    "oa":      "http://www.w3.org/ns/oa#",
    "prov":    "http://www.w3.org/ns/prov#",
    "foaf":    "http://xmlns.com/foaf/0.1/",
    "hico":    "http://purl.org/emmedi/hico/",
    "cito":    "http://purl.org/spar/cito/",
    "geo":     "http://www.w3.org/2003/01/geo/wgs84_pos#",
    "owltime": "http://www.w3.org/2006/time#",
}


# ---------------- graph helpers ----------------

def load_all_layers():
    g = Graph()
    for layer in LAYERS:
        g.parse(TTL_DIR / layer["file"], format="turtle")
    return g


def qname(g: Graph, uri) -> str:
    if isinstance(uri, BNode):
        return f"_:{uri}"
    s = str(uri)
    # 最長一致を優先 (hmktei: の URI は hmkp: の URI を接頭に含むため)。
    for layer in sorted(LAYERS, key=lambda l: len(l["uri"]), reverse=True):
        if s.startswith(layer["uri"]):
            return f"{layer['prefix']}:{s[len(layer['uri']):]}"
    for pref, ns in sorted(COMMON_PREFIXES.items(), key=lambda kv: len(kv[1]), reverse=True):
        if s.startswith(ns):
            return f"{pref}:{s[len(ns):]}"
    return s


def local_layer(uri):
    # 最長一致を優先 (hmktei: の URI は hmkp: の URI を接頭に含むため)。
    for layer in sorted(LAYERS, key=lambda l: len(l["uri"]), reverse=True):
        if str(uri).startswith(layer["uri"]):
            return layer
    return None


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
    """domain / range / subClassOf 等の値をカンマ区切りで文字列化。unionOf 対応。"""
    parts = []
    for _, _, o in g.triples((s, predicate, None)):
        if isinstance(o, BNode):
            union = list(g.objects(o, OWL.unionOf))
            if union:
                items = [qname(g, item) for item in rdf_list(g, union[0])]
                parts.append("(" + " ∪ ".join(items) + ")")
            else:
                parts.append("匿名クラス")
        else:
            parts.append(qname(g, o))
    return ", ".join(parts)


def collect_entities(g: Graph):
    by_layer_class = defaultdict(list)
    by_layer_op = defaultdict(list)
    by_layer_dp = defaultdict(list)
    for s in g.subjects(RDF.type, OWL.Class):
        if isinstance(s, BNode):
            continue
        layer = local_layer(s)
        if layer:
            by_layer_class[layer["prefix"]].append(s)
    for s in g.subjects(RDF.type, OWL.ObjectProperty):
        if isinstance(s, BNode):
            continue
        layer = local_layer(s)
        if layer:
            by_layer_op[layer["prefix"]].append(s)
    for s in g.subjects(RDF.type, OWL.DatatypeProperty):
        if isinstance(s, BNode):
            continue
        layer = local_layer(s)
        if layer:
            by_layer_dp[layer["prefix"]].append(s)
    for d in (by_layer_class, by_layer_op, by_layer_dp):
        for k in d:
            d[k].sort(key=lambda u: str(u))
    return by_layer_class, by_layer_op, by_layer_dp


# ---------------- HTML rendering ----------------

CSS = """
:root {
  --fg: #1f2937;
  --muted: #6b7280;
  --border: #cbd5e1;
  --border-light: #e5e7eb;
  --thead-bg: #f3f4f6;
  --code-bg: #f3f4f6;
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
}
h3 {
  font-size: 13px;
  margin: 18px 0 6px;
  color: var(--fg);
  font-weight: 700;
}
.layer-intro { color: var(--muted); font-size: 11.5px; margin: -4px 0 10px; }

table.ttable {
  border-collapse: collapse;
  width: 100%;
  font-size: 11px;
  margin: 0 0 14px;
  page-break-inside: auto;
}
table.ttable caption {
  caption-side: top;
  text-align: left;
  font-weight: 700;
  font-size: 12px;
  padding: 4px 0 6px;
  color: var(--fg);
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


def render_class_table(g: Graph, layer, items):
    if not items:
        return ""
    rows = []
    for s in items:
        qn = qname(g, s)
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
        f'<th style="width:16%">QName</th>'
        f'<th style="width:14%">ラベル</th>'
        f'<th style="width:18%">上位クラス</th>'
        f'<th>定義</th>'
        f'</tr></thead>\n'
        f'  <tbody>\n{chr(10).join(rows)}\n  </tbody>\n'
        f'</table>'
    )


def render_property_table(g: Graph, layer, items, kind_label: str, is_object: bool):
    """kind_label: 表見出しに出す種別名。is_object: True なら ObjectProperty."""
    if not items:
        return ""
    rows = []
    for s in items:
        qn = qname(g, s)
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
    if is_object:
        colwidths = ["15%", "12%", "12%", "12%", "12%", "5%", ""]
    else:
        colwidths = ["15%", "12%", "12%", "12%", "12%", "5%", ""]
    return (
        f'<h3>{kind_label} — {len(items)} 件</h3>\n'
        f'<table class="ttable">\n'
        f'  <thead><tr>'
        f'<th style="width:{colwidths[0]}">QName</th>'
        f'<th style="width:{colwidths[1]}">ラベル</th>'
        f'<th style="width:{colwidths[2]}">ドメイン</th>'
        f'<th style="width:{colwidths[3]}">レンジ</th>'
        f'<th style="width:{colwidths[4]}">上位プロパティ</th>'
        f'<th style="width:{colwidths[5]}">属性</th>'
        f'<th>定義</th>'
        f'</tr></thead>\n'
        f'  <tbody>\n{chr(10).join(rows)}\n  </tbody>\n'
        f'</table>'
    )


def render_layer(g: Graph, layer, cls_list, op_list, dp_list):
    header = (
        f'<h2 style="background:{layer["color"]}">'
        f'{esc(layer["title_ja"])}  <code style="background:rgba(255,255,255,0.2); '
        f'color:#fff; padding:1px 6px; border-radius:2px; font-size:11px">'
        f'{layer["prefix"]}:</code></h2>'
    )
    parts = [header]
    cls_html = render_class_table(g, layer, cls_list)
    op_html = render_property_table(g, layer, op_list, "オブジェクトプロパティ (Object Properties)", is_object=True)
    dp_html = render_property_table(g, layer, dp_list, "データプロパティ (Datatype Properties)", is_object=False)
    for h in (cls_html, op_html, dp_html):
        if h:
            parts.append(h)
    if not (cls_html or op_html or dp_html):
        parts.append('<p class="layer-intro">このレイヤーには該当エントリがない。</p>')
    return "\n".join(parts)


def build_html(g: Graph) -> str:
    cls_by, op_by, dp_by = collect_entities(g)

    summary_rows = []
    total = [0, 0, 0]
    for layer in LAYERS:
        p = layer["prefix"]
        n_c = len(cls_by.get(p, []))
        n_o = len(op_by.get(p, []))
        n_d = len(dp_by.get(p, []))
        total[0] += n_c
        total[1] += n_o
        total[2] += n_d
        summary_rows.append(
            f'<tr>'
            f'<td class="name"><code>{p}</code> — {esc(layer["title_ja"])}</td>'
            f'<td>{n_c}</td><td>{n_o}</td><td>{n_d}</td>'
            f'<td><strong>{n_c + n_o + n_d}</strong></td>'
            f'</tr>'
        )
    summary_rows.append(
        f'<tr style="border-top:1.5px solid var(--fg)">'
        f'<td class="name"><strong>合計</strong></td>'
        f'<td><strong>{total[0]}</strong></td>'
        f'<td><strong>{total[1]}</strong></td>'
        f'<td><strong>{total[2]}</strong></td>'
        f'<td><strong>{sum(total)}</strong></td>'
        f'</tr>'
    )

    layer_htmls = []
    for layer in LAYERS:
        p = layer["prefix"]
        layer_htmls.append(render_layer(
            g, layer, cls_by.get(p, []), op_by.get(p, []), dp_by.get(p, [])
        ))

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>HIMIKO オントロジー クラス・プロパティ一覧表</title>
<style>{CSS}</style>
</head>
<body>
<h1>HIMIKO オントロジー クラス・プロパティ一覧表</h1>
<p class="subtitle">Historical Micro Knowledge and Ontology — 論文添付用リファレンス表</p>

<table class="summary">
  <thead><tr>
    <th>レイヤー</th>
    <th>クラス</th>
    <th>オブジェクトプロパティ</th>
    <th>データプロパティ</th>
    <th>合計</th>
  </tr></thead>
  <tbody>
{chr(10).join(summary_rows)}
  </tbody>
</table>

<p class="layer-intro">
凡例 — <strong>QName</strong>: 修飾名 (プレフィックス:ローカル名)。
<strong>ドメイン/レンジ</strong>: <code>(A ∪ B)</code> は <code>owl:unionOf</code> による直和。
<strong>属性</strong>: <span class="func">Func</span> は <code>owl:FunctionalProperty</code> (関数的プロパティ) を示す。
外部語彙のプレフィックス (rdfs, owl, xsd, oa, prov, foaf, hico, cito, geo, owltime, dcterms) は
省略形のまま表記し、詳細は本編 §名前空間を参照。
</p>

{chr(10).join(layer_htmls)}

<footer>
自動生成元: <code>ontology/hmk_owl/*.ttl</code> · ビルダー: <code>ontology/build_tables.py</code>
</footer>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "-o", "--output",
        default=str(SCRIPT_DIR / "figs" / "himiko_tables.html"),
        help="出力 HTML パス (デフォルト: ontology/figs/himiko_tables.html)",
    )
    args = ap.parse_args()

    g = load_all_layers()
    print(f"Loaded {len(g)} triples from {len(LAYERS)} ontology files")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_html(g), encoding="utf-8")
    print(f"→ Wrote {out_path} ({out_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
