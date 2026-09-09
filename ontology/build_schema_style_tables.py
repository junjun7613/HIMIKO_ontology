#!/usr/bin/env python3
"""
論文・書籍掲載用の schema.org 風リファレンス表 (HTML) を生成するビルダー。

schema.org のリファレンス表 (例: 表6-4 schema:Thing に適用するプロパティ) を模した
3 列の簡潔なリスト形式で、HIMIKO オントロジー 4 レイヤー (hmkp, hmktei, hmki, hmke,
hmkia) のクラス・プロパティを掲載する。

出力される表:
  クラス表      : クラス URI | 日本語ラベルなど | 上位クラス
  プロパティ表   : プロパティ URI | 日本語ラベルなど (逆向き・上位プロパティ・属性を併記) | 値域

「日本語ラベルなど」欄には、schema.org 表の「内容の対象。(逆向き: schema:subjectOf)」の
書式にならい、日本語ラベルに続けて (逆向き: …)・(上位: …)・関数的プロパティ等の
補足を括弧書きで併記する。

出力: ontology/figs/himiko_schema_style_tables.html (印刷/PDF 化を想定したスタンドアロン HTML)

使用方法:
    python build_schema_style_tables.py
    python build_schema_style_tables.py -o /tmp/tables.html
"""

import argparse
import html
from pathlib import Path
from collections import defaultdict

from rdflib import Graph, Literal, BNode
from rdflib.namespace import RDF, RDFS, OWL

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


def rdf_list(g: Graph, head):
    items = []
    while head and head != RDF.nil:
        first = g.value(head, RDF.first)
        if first is not None:
            items.append(first)
        head = g.value(head, RDF.rest)
    return items


def format_dr(g: Graph, s, predicate):
    """domain / range / subClassOf 等の値のリストを QName で返す。unionOf 対応。"""
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
    return parts


def collect_entities(g: Graph):
    by_layer_class = defaultdict(list)
    by_layer_prop = defaultdict(list)  # object + datatype をまとめて掲載
    for s in g.subjects(RDF.type, OWL.Class):
        if isinstance(s, BNode):
            continue
        layer = local_layer(s)
        if layer:
            by_layer_class[layer["prefix"]].append(s)
    for prop_type in (OWL.ObjectProperty, OWL.DatatypeProperty):
        for s in g.subjects(RDF.type, prop_type):
            if isinstance(s, BNode):
                continue
            layer = local_layer(s)
            if layer and s not in by_layer_prop[layer["prefix"]]:
                by_layer_prop[layer["prefix"]].append(s)
    for d in (by_layer_class, by_layer_prop):
        for k in d:
            d[k].sort(key=lambda u: str(u))
    return by_layer_class, by_layer_prop


# ---------------- HTML rendering ----------------

CSS = """
:root {
  --fg: #1f2937;
  --muted: #6b7280;
  --border: #333;
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
  margin: 34px 0 10px;
  padding: 6px 10px;
  color: #fff;
  border-radius: 3px;
}
h3 {
  font-size: 12.5px;
  margin: 20px 0 6px;
  color: var(--fg);
  font-weight: 700;
}
.caption { font-weight: 700; font-size: 12px; margin: 16px 0 4px; }

/* schema.org 風: 全セルに罫線を引いた素朴なグリッド表 */
table.sform {
  border-collapse: collapse;
  width: 100%;
  font-size: 11px;
  margin: 0 0 8px;
  page-break-inside: auto;
}
table.sform th, table.sform td {
  border: 1px solid var(--border);
  padding: 5px 9px;
  text-align: left;
  vertical-align: top;
}
table.sform thead th {
  font-weight: 700;
  background: #fff;
  white-space: nowrap;
}
table.sform td.uri code,
table.sform td.val code {
  font-family: "SF Mono", ui-monospace, Menlo, Consolas, monospace;
  font-size: 10.5px;
  white-space: nowrap;
}
table.sform td.label { line-height: 1.5; }
table.sform td.label .note { color: var(--muted); }
table.sform .none { color: var(--muted); }

.layer-intro { color: var(--muted); font-size: 11.5px; margin: 4px 0 12px; }

footer { margin-top: 32px; color: var(--muted); font-size: 10.5px; }

@page { size: A4; margin: 20mm 15mm; }
@media print {
  body { padding: 0; }
  h2, h3, .caption { page-break-after: avoid; }
  table.sform { page-break-inside: auto; }
  table.sform tr { page-break-inside: avoid; page-break-after: auto; }
  table.sform thead { display: table-header-group; }
}
"""


def esc(s: str) -> str:
    return html.escape(s or "")


def none_cell(text: str = "—") -> str:
    return f'<span class="none">{text}</span>'


def code_join(qnames):
    """QName のリストを <code> でラップしてカンマ区切りで返す。"""
    if not qnames:
        return none_cell()
    return ", ".join(f"<code>{esc(q)}</code>" for q in qnames)


def render_class_table(g: Graph, items):
    """クラス表: クラス URI | 日本語ラベルなど | 上位クラス。"""
    if not items:
        return ""
    rows = []
    for s in items:
        qn = qname(g, s)
        label = get_label_ja(g, s)
        sup = format_dr(g, s, RDFS.subClassOf)
        rows.append(
            f'<tr>'
            f'<td class="uri"><code>{esc(qn)}</code></td>'
            f'<td class="label">{esc(label) or none_cell()}</td>'
            f'<td class="val">{code_join(sup)}</td>'
            f'</tr>'
        )
    return (
        f'<table class="sform">\n'
        f'  <thead><tr>'
        f'<th style="width:26%">クラス URI</th>'
        f'<th style="width:40%">ラベル</th>'
        f'<th>上位クラス</th>'
        f'</tr></thead>\n'
        f'  <tbody>\n{chr(10).join(rows)}\n  </tbody>\n'
        f'</table>'
    )


def label_notes_cell(g: Graph, s, label: str) -> str:
    """schema.org 風の「日本語ラベルなど」セルを生成。

    日本語ラベルに続けて、逆向きプロパティ・上位プロパティ・関数的属性を
    括弧書きの補足として併記する。
    """
    main = esc(label) if label else ""
    notes = []

    inv = [qname(g, o) for o in g.objects(s, OWL.inverseOf)]
    # inverseOf は片側にしか書かれないことがあるため双方向で拾う
    inv += [qname(g, subj) for subj in g.subjects(OWL.inverseOf, s)]
    inv = sorted(set(inv))
    if inv:
        notes.append("逆向き: " + ", ".join(f"<code>{esc(q)}</code>" for q in inv))

    sup = format_dr(g, s, RDFS.subPropertyOf)
    if sup:
        notes.append("上位: " + ", ".join(f"<code>{esc(q)}</code>" for q in sup))

    if (s, RDF.type, OWL.FunctionalProperty) in g:
        notes.append("関数的プロパティ")

    note_html = ""
    if notes:
        note_html = f' <span class="note">({" / ".join(notes)})</span>'

    if not main and not notes:
        return none_cell()
    return (main or none_cell()) + note_html


def render_property_table(g: Graph, items):
    """プロパティ表: プロパティ URI | 日本語ラベルなど | 値域。"""
    if not items:
        return ""
    rows = []
    for s in items:
        qn = qname(g, s)
        label = get_label_ja(g, s)
        dom = format_dr(g, s, RDFS.domain)
        rng = format_dr(g, s, RDFS.range)
        rows.append(
            f'<tr>'
            f'<td class="uri"><code>{esc(qn)}</code></td>'
            f'<td class="label">{label_notes_cell(g, s, label)}</td>'
            f'<td class="val">{code_join(dom)}</td>'
            f'<td class="val">{code_join(rng)}</td>'
            f'</tr>'
        )
    return (
        f'<table class="sform">\n'
        f'  <thead><tr>'
        f'<th style="width:22%">プロパティ URI</th>'
        f'<th style="width:34%">ラベル</th>'
        f'<th style="width:22%">定義域</th>'
        f'<th style="width:22%">値域</th>'
        f'</tr></thead>\n'
        f'  <tbody>\n{chr(10).join(rows)}\n  </tbody>\n'
        f'</table>'
    )


def render_layer(g: Graph, layer, cls_list, prop_list, table_no):
    header = (
        f'<h2 style="background:{layer["color"]}">'
        f'{esc(layer["title_ja"])}  <code style="background:rgba(255,255,255,0.2); '
        f'color:#fff; padding:1px 6px; border-radius:2px; font-size:11px">'
        f'{layer["prefix"]}:</code></h2>'
    )
    parts = [header]

    cls_html = render_class_table(g, cls_list)
    if cls_html:
        parts.append(
            f'<p class="caption">表 {table_no[0]}　'
            f'{esc(layer["title_ja"])} のクラス（{len(cls_list)} 件）</p>'
        )
        parts.append(cls_html)
        table_no[0] = _next_table_no(table_no[0])

    prop_html = render_property_table(g, prop_list)
    if prop_html:
        parts.append(
            f'<p class="caption">表 {table_no[0]}　'
            f'{esc(layer["title_ja"])} のプロパティ（{len(prop_list)} 件）</p>'
        )
        parts.append(prop_html)
        table_no[0] = _next_table_no(table_no[0])

    if not (cls_html or prop_html):
        parts.append('<p class="layer-intro">このレイヤーには該当エントリがない。</p>')
    return "\n".join(parts)


def _next_table_no(no: str) -> str:
    """'6-4' → '6-5' のように末尾の枝番をインクリメントする。"""
    if "-" in no:
        head, _, tail = no.rpartition("-")
        if tail.isdigit():
            return f"{head}-{int(tail) + 1}"
    if no.isdigit():
        return str(int(no) + 1)
    return no


def build_html(g: Graph, start_no: str) -> str:
    cls_by, prop_by = collect_entities(g)

    layer_htmls = []
    table_no = [start_no]  # ミュータブルに持ち回してレイヤーをまたいで連番を振る
    for layer in LAYERS:
        p = layer["prefix"]
        layer_htmls.append(render_layer(
            g, layer, cls_by.get(p, []), prop_by.get(p, []), table_no
        ))

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>HIMIKO オントロジー リファレンス（schema.org 風）</title>
<style>{CSS}</style>
</head>
<body>
<h1>HIMIKO オントロジー リファレンス表</h1>
<p class="subtitle">Historical Micro Knowledge and Ontology — 論文・書籍掲載用 (schema.org リファレンス形式)</p>

<p class="layer-intro">
凡例 — <strong>URI</strong> は修飾名 (プレフィックス:ローカル名) で表記する。
プロパティ欄の補足のうち <strong>(逆向き: …)</strong> は <code>owl:inverseOf</code>、
<strong>(上位: …)</strong> は <code>rdfs:subPropertyOf</code>、
<strong>関数的プロパティ</strong> は <code>owl:FunctionalProperty</code> を示す。
<strong>値域</strong> の <code>(A ∪ B)</code> は <code>owl:unionOf</code> による直和を表す。
外部語彙 (rdfs, owl, xsd, oa, prov, foaf, hico, cito, geo, owltime, dcterms) は
省略形のまま表記する。
</p>

{chr(10).join(layer_htmls)}

<footer>
自動生成元: <code>ontology/hmk_owl/*.ttl</code> · ビルダー: <code>ontology/build_schema_style_tables.py</code>
</footer>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "-o", "--output",
        default=str(SCRIPT_DIR / "figs" / "himiko_schema_style_tables.html"),
        help="出力 HTML パス (デフォルト: ontology/figs/himiko_schema_style_tables.html)",
    )
    ap.add_argument(
        "--start-no",
        default="1",
        help="最初の表番号 (例: '6-4')。以降レイヤー・種別ごとに連番を振る。",
    )
    args = ap.parse_args()

    g = load_all_layers()
    print(f"Loaded {len(g)} triples from {len(LAYERS)} ontology files")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_html(g, args.start_no), encoding="utf-8")
    print(f"→ Wrote {out_path} ({out_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
