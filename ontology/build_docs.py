#!/usr/bin/env python3
"""
HIMIKO オントロジーの HTML ドキュメントビルダー (bilingual)。

TTL 4 ファイル (hmkp, hmki, hmke, hmkia) を読み込み、
1 ページの HTML (日英切替 UI 付き) を生成する。

使用方法:
    python build_docs.py                         # ontology/himiko.html を出力
    python build_docs.py -o /tmp/preview.html    # 出力先を指定

依存: rdflib
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
        "title_en": "Physical Layer",
        "color": "#3b82f6",
        "intro_ja": (
            "史料そのものの物質的・文字情報的特徴を記述する層。"
            "Source (物理的媒体) が bears によって Text (テキスト) を担い、"
            "Text は Character の連結リストとして展開される。"
            "Annotation は Character 範囲を hasRange (startChar / endChar) で指定する。"
            "現行の ATAG 実装で最も稠密に構築されているのがこの層である。"
        ),
        "intro_en": (
            "Layer for describing the material and textual characteristics of the source itself. "
            "A Source (physical medium) bears a Text via bears, and Text is expanded as a linked list of Characters. "
            "Annotation specifies a Character range via hasRange (startChar / endChar). "
            "This layer is the most densely modelled in the current ATAG implementation."
        ),
    },
    {
        "prefix": "hmktei",
        "uri": "urn:himiko:ontology:physical:tei:",
        "file": "himiko_physical_tei.ttl",
        "title_ja": "史料物理層 — TEI 変換プロファイル",
        "title_en": "Physical Layer — TEI Conversion Profile",
        "color": "#60a5fa",
        "intro_ja": (
            "TEI/EDCS の要素・属性に由来する、アノテーションの種別クラスと細目プロパティを定義するプロファイル。"
            "アノテーション種別は hmkp:Annotation のサブクラス (欠損 hmktei:Gap、略号 hmktei:Abbr など) として"
            "表現し、欠損理由 (reason)・単位 (unit) などの細目プロパティは対応する種別クラスを domain とする。"
            "これらは特定の入力フォーマット (TEI Guidelines) の語彙に対応するものであり、史料種別に依存しない"
            "抽象的枠組みである物理層コアからは意図的に分離してある。各クラス・プロパティは対応する TEI の"
            "要素・属性を rdfs:seeAlso で示す。互換用の文字列プロパティ hmktei:kind は移行期のため残置 (deprecated)。"
        ),
        "intro_en": (
            "A profile defining annotation kind classes and fine-grained properties derived from TEI/EDCS elements "
            "and attributes. Annotation kinds are modelled as subclasses of hmkp:Annotation (e.g. hmktei:Gap for "
            "lacunae, hmktei:Abbr for abbreviations), and detail properties such as gap reason and unit are scoped "
            "to the corresponding kind class via rdfs:domain. These correspond to the vocabulary of a specific input "
            "format (TEI Guidelines) and are deliberately separated from the physical-layer core, a "
            "source-type-independent abstract framework. Each class or property points to the corresponding TEI "
            "element or attribute via rdfs:seeAlso. The legacy string property hmktei:kind is retained during the "
            "migration period (deprecated)."
        ),
    },
    {
        "prefix": "hmki",
        "uri": "urn:himiko:ontology:intrinsic:",
        "file": "himiko_intrinsic.ttl",
        "title_ja": "史料内在知識層",
        "title_en": "Intrinsic Knowledge Layer",
        "color": "#f59e0b",
        "intro_ja": (
            "史料に記述された意味内容を構造化する層。Statement (イベント言及) を意味内容記述の"
            "基本単位とし、その構成要素として EntityReference を用いる。"
            "Statement は Character を直接 mentions することで史料上の根拠を保持し、"
            "EntityReference は hasRange によって指し示すテキスト範囲を明示する。"
        ),
        "intro_en": (
            "Layer for structuring the semantic content described in a source. "
            "Statement (event mention) is the basic unit of semantic description, with EntityReference as its constituent. "
            "A Statement directly mentions Characters to preserve textual evidence, and EntityReference makes its "
            "referenced text range explicit through hasRange."
        ),
    },
    {
        "prefix": "hmke",
        "uri": "urn:himiko:ontology:extrinsic:",
        "file": "himiko_extrinsic.ttl",
        "title_ja": "外在知識層",
        "title_en": "Extrinsic Knowledge Layer",
        "color": "#10b981",
        "intro_ja": (
            "史料中の言及を史料外部の知識体系と接続する層。EntityReference — EntityInContext — Entity "
            "という三段階の構造を採り、単なるエンティティ・リンキングでは失われる歴史的コンテキスト "
            "(時間・社会・地理) を保持する。EntityInContext は eventSince / eventUntil によって"
            "時間的範囲を持ち、hasLocation / hasRole / memberOf などで文脈的属性を保持する。"
        ),
        "intro_en": (
            "Layer that connects in-source mentions to external knowledge systems. "
            "It employs a three-tier structure of EntityReference — EntityInContext — Entity, preserving the historical "
            "context (temporal, social, geographical) that plain entity linking would lose. "
            "EntityInContext carries a temporal span via eventSince / eventUntil and contextual attributes such as "
            "hasLocation / hasRole / memberOf."
        ),
    },
    {
        "prefix": "hmkia",
        "uri": "urn:himiko:ontology:interpretation:",
        "file": "himiko_interpretation.ttl",
        "title_ja": "解釈行為層",
        "title_en": "Interpretation Act Layer",
        "color": "#8b5cf6",
        "intro_ja": (
            "三層すべてのデータ生成に介在する研究者の「解釈」を独立したリソースとして実体化する層。"
            "Annotation・Statement・EntityInContext などは generatedBy によって必ず"
            " InterpretationAct を参照する。InterpretationAct 同士は supports / critiques / revises "
            "などで再帰的に接続される。基本モデルは HiCO を踏襲する。"
        ),
        "intro_en": (
            "Layer that materialises the researcher's interpretation—present in the data generation of all three layers—"
            "as an independent resource. Annotation, Statement, EntityInContext, and others always reference an "
            "InterpretationAct via generatedBy. Interpretation Acts are recursively linked to each other with "
            "supports / critiques / revises. The base model follows HiCO."
        ),
    },
]

COMMON_PREFIXES = {
    "rdf":   "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs":  "http://www.w3.org/2000/01/rdf-schema#",
    "owl":   "http://www.w3.org/2002/07/owl#",
    "xsd":   "http://www.w3.org/2001/XMLSchema#",
    "dcterms": "http://purl.org/dc/terms/",
    "oa":    "http://www.w3.org/ns/oa#",
    "prov":  "http://www.w3.org/ns/prov#",
    "foaf":  "http://xmlns.com/foaf/0.1/",
    "hico":  "http://purl.org/emmedi/hico/",
    "cito":  "http://purl.org/spar/cito/",
    "geo":   "http://www.w3.org/2003/01/geo/wgs84_pos#",
}

# ---------------- i18n helpers ----------------

def bi(ja: str, en: str, tag: str = "span") -> str:
    """Render a bilingual snippet with data-lang attribute selectors."""
    return (
        f'<{tag} data-lang="ja">{ja}</{tag}>'
        f'<{tag} data-lang="en">{en}</{tag}>'
    )


# ---------------- graph helpers (unchanged) ----------------

I18N_OVERLAY = "himiko_i18n_en.ttl"


def load_all_layers():
    combined = Graph()
    for layer in LAYERS:
        path = TTL_DIR / layer["file"]
        combined.parse(path, format="turtle")
    overlay = TTL_DIR / I18N_OVERLAY
    if overlay.exists():
        combined.parse(overlay, format="turtle")
    return combined


def qname(g: Graph, uri) -> str:
    if isinstance(uri, BNode):
        return f"_:{uri}"
    s = str(uri)
    # 最長一致を優先する。hmktei: の URI (…:physical:tei:) は hmkp: の URI
    # (…:physical:) を接頭に含むため、単純な先頭一致だと hmkp: に誤マッチする。
    for layer in sorted(LAYERS, key=lambda l: len(l["uri"]), reverse=True):
        if s.startswith(layer["uri"]):
            return f"{layer['prefix']}:{s[len(layer['uri']):]}"
    for pref, ns in sorted(COMMON_PREFIXES.items(), key=lambda kv: len(kv[1]), reverse=True):
        if s.startswith(ns):
            return f"{pref}:{s[len(ns):]}"
    return s


def anchor_id(qn: str) -> str:
    return qn.replace(":", "-").replace("/", "-")


def local_layer(uri: str):
    # 最長一致を優先 (hmktei: の URI は hmkp: の URI を接頭に含むため)。
    for layer in sorted(LAYERS, key=lambda l: len(l["uri"]), reverse=True):
        if str(uri).startswith(layer["uri"]):
            return layer
    return None


def get_labels(g: Graph, s):
    out = {}
    for _, _, o in g.triples((s, RDFS.label, None)):
        if isinstance(o, Literal):
            out[o.language or ""] = str(o)
    return out


def get_comments(g: Graph, s):
    out = {}
    for _, _, o in g.triples((s, RDFS.comment, None)):
        if isinstance(o, Literal):
            out.setdefault(o.language or "", []).append(str(o))
    return out


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


def rdf_list(g: Graph, head):
    items = []
    while head and head != RDF.nil:
        first = g.value(head, RDF.first)
        if first is not None:
            items.append(first)
        head = g.value(head, RDF.rest)
    return items


def link(g: Graph, uri, qn: str = None) -> str:
    if isinstance(uri, BNode):
        return f"<em>{html.escape(qn or '_:blank')}</em>"
    qn = qn or qname(g, uri)
    layer = local_layer(uri)
    if layer:
        return f'<a href="#{anchor_id(qn)}">{html.escape(qn)}</a>'
    s = str(uri)
    return f'<a href="{html.escape(s)}" rel="external" target="_blank">{html.escape(qn)}</a>'


def format_dr_html(g: Graph, s, predicate):
    out = []
    for _, _, o in g.triples((s, predicate, None)):
        if isinstance(o, BNode):
            union = list(g.objects(o, OWL.unionOf))
            if union:
                items = [link(g, item) for item in rdf_list(g, union[0])]
                out.append("(" + " ∪ ".join(items) + ")")
            else:
                out.append("<em>anonymous class</em>")
        else:
            out.append(link(g, o))
    return ", ".join(out) if out else "<span class='none'>—</span>"


# ---------------- rendering ----------------

def render_entity_card(g: Graph, s, kind: str, layer):
    qn = qname(g, s)
    labels = get_labels(g, s)
    comments = get_comments(g, s)

    label_en = labels.get("en", "")
    label_ja = labels.get("ja", "")
    comment_ja = "<br>".join(comments.get("ja", [])) if "ja" in comments else ""
    comment_en = "<br>".join(comments.get("en", [])) if "en" in comments else ""

    super_p = format_dr_html(g, s, RDFS.subClassOf if kind == "Class" else RDFS.subPropertyOf)
    domain_html = format_dr_html(g, s, RDFS.domain)
    range_html  = format_dr_html(g, s, RDFS.range)

    is_functional = (s, RDF.type, OWL.FunctionalProperty) in g

    subs = []
    for sub_s, _, _ in g.triples((None, RDFS.subClassOf if kind == "Class" else RDFS.subPropertyOf, s)):
        if isinstance(sub_s, BNode):
            continue
        subs.append(link(g, sub_s))
    sub_html = ", ".join(subs) if subs else ""

    see_also = []
    for _, _, o in g.triples((s, RDFS.seeAlso, None)):
        see_also.append(link(g, o))
    see_also_html = ", ".join(see_also)

    equivs = []
    for _, _, o in g.triples((s, OWL.equivalentClass if kind == "Class" else OWL.equivalentProperty, None)):
        equivs.append(link(g, o))
    equiv_html = ", ".join(equivs)

    color = layer["color"]
    kind_label_ja = {
        "Class": "クラス",
        "ObjectProperty": "オブジェクトプロパティ",
        "DatatypeProperty": "データプロパティ",
    }.get(kind, kind)
    kind_label_en = {
        "Class": "Class",
        "ObjectProperty": "Object Property",
        "DatatypeProperty": "Datatype Property",
    }.get(kind, kind)

    lines = [f'<article class="entity {kind.lower()}" id="{anchor_id(qn)}" style="border-left-color:{color}">']
    lines.append('<header>')
    lines.append(
        f'  <span class="kind-badge" style="background:{color}">'
        f'{bi(html.escape(kind_label_ja), html.escape(kind_label_en))}'
        f'</span>'
    )
    if is_functional:
        lines.append('  <span class="kind-badge functional">functional</span>')
    lines.append(f'  <h4><code>{html.escape(qn)}</code></h4>')

    # Label: prefer active-language label, gracefully fall back to the other
    if label_ja or label_en:
        ja_disp = label_ja or label_en
        en_disp = label_en or label_ja
        lines.append(
            f'  <p class="label">'
            f'{bi(html.escape(ja_disp), html.escape(en_disp))}'
            f'</p>'
        )
    lines.append(
        f'  <p class="iri">'
        f'{bi("<span class=\'k\'>IRI:</span>", "<span class=\'k\'>IRI:</span>")} '
        f'<code>{html.escape(str(s))}</code></p>'
    )
    lines.append('</header>')

    # Comments: show both when available; when only one exists, show it in both languages
    if comment_ja or comment_en:
        ja_body = comment_ja or comment_en
        en_body = comment_en or comment_ja
        lines.append(
            f'<p class="comment">'
            f'<span data-lang="ja">{ja_body}</span>'
            f'<span data-lang="en">{en_body}</span>'
            f'</p>'
        )

    lines.append('<dl class="meta">')
    if kind != "Class":
        lines.append(f'  <dt>{bi("ドメイン", "Domain")}</dt><dd>{domain_html}</dd>')
        lines.append(f'  <dt>{bi("レンジ", "Range")}</dt><dd>{range_html}</dd>')
    if super_p and super_p != "<span class='none'>—</span>":
        key = bi("上位クラス", "Super-class") if kind == "Class" else bi("上位プロパティ", "Super-property")
        lines.append(f'  <dt>{key}</dt><dd>{super_p}</dd>')
    if sub_html:
        key = bi("下位クラス", "Sub-class(es)") if kind == "Class" else bi("下位プロパティ", "Sub-property(ies)")
        lines.append(f'  <dt>{key}</dt><dd>{sub_html}</dd>')
    if equiv_html:
        key = bi("等価クラス", "Equivalent class") if kind == "Class" else bi("等価プロパティ", "Equivalent property")
        lines.append(f'  <dt>{key}</dt><dd>{equiv_html}</dd>')
    if see_also_html:
        lines.append(f'  <dt>{bi("参照", "See also")}</dt><dd>{see_also_html}</dd>')
    lines.append('</dl>')

    lines.append('</article>')
    return "\n".join(lines)


CSS = """
:root {
  --bg: #ffffff;
  --fg: #1f2937;
  --muted: #6b7280;
  --border: #e5e7eb;
  --code-bg: #f3f4f6;
  --sidebar-bg: #f9fafb;
  --link: #2563eb;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", "Hiragino Sans", "Yu Gothic UI", sans-serif;
  color: var(--fg);
  background: var(--bg);
  line-height: 1.65;
}
.wrapper { display: grid; grid-template-columns: 260px 1fr; min-height: 100vh; }
nav.toc {
  background: var(--sidebar-bg);
  border-right: 1px solid var(--border);
  padding: 24px 16px;
  position: sticky; top: 0; align-self: start;
  height: 100vh; overflow-y: auto;
  font-size: 14px;
}
nav.toc h2 { font-size: 15px; margin: 20px 0 8px; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }
nav.toc h2:first-child { margin-top: 0; }
nav.toc ul { list-style: none; padding: 0; margin: 0 0 8px 0; }
nav.toc li { margin: 3px 0; }
nav.toc li.sub { padding-left: 12px; font-size: 13px; }
nav.toc a { color: var(--fg); text-decoration: none; }
nav.toc a:hover { color: var(--link); text-decoration: underline; }
nav.toc a code { background: transparent; color: inherit; }

main { padding: 40px 48px; max-width: 1000px; }
h1 { font-size: 30px; margin: 0 0 8px; }
h2 { font-size: 24px; margin: 40px 0 12px; padding-bottom: 8px; border-bottom: 2px solid var(--border); }
h3 { font-size: 19px; margin: 28px 0 10px; color: var(--fg); }
h4 { margin: 0; font-size: 18px; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; background: var(--code-bg); padding: 1px 5px; border-radius: 3px; font-size: 0.92em; }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
.subtitle { color: var(--muted); margin-top: 0; }
.meta-block { background: var(--sidebar-bg); border: 1px solid var(--border); border-radius: 6px; padding: 12px 18px; margin: 20px 0; font-size: 14px; }
.meta-block dt { font-weight: 600; float: left; width: 130px; color: var(--muted); }
.meta-block dd { margin: 0 0 4px 130px; }
table.prefixes { border-collapse: collapse; width: 100%; font-size: 14px; margin: 12px 0; }
table.prefixes td { padding: 6px 10px; border-bottom: 1px solid var(--border); }
table.prefixes td:first-child { width: 100px; font-weight: 600; }
table.prefixes code { background: transparent; padding: 0; }
.diagram-figure { text-align: center; margin: 24px 0; padding: 20px; background: var(--sidebar-bg); border-radius: 8px; border: 1px solid var(--border); }
.diagram-figure img { max-width: 100%; height: auto; display: block; margin: 0 auto; }
.layer-intro { padding: 12px 18px; border-left: 4px solid; background: var(--sidebar-bg); border-radius: 4px; margin: 12px 0 24px; }
details.section-group { margin: 20px 0 8px; border-top: 1px solid var(--border); }
details.section-group[open] { margin-bottom: 20px; }
details.section-group > summary {
  list-style: none;
  cursor: pointer;
  padding: 10px 4px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 19px;
  font-weight: 600;
  color: var(--fg);
  user-select: none;
}
details.section-group > summary::-webkit-details-marker { display: none; }
details.section-group > summary::before {
  content: "";
  display: inline-block;
  width: 0; height: 0;
  border-left: 6px solid var(--muted);
  border-top: 5px solid transparent;
  border-bottom: 5px solid transparent;
  transition: transform 0.15s ease;
  flex-shrink: 0;
}
details.section-group[open] > summary::before { transform: rotate(90deg); }
details.section-group > summary:hover { color: var(--link); }
details.section-group > summary .count { color: var(--muted); font-weight: 400; font-size: 15px; }
article.entity {
  background: #fff;
  border: 1px solid var(--border);
  border-left: 5px solid;
  border-radius: 6px;
  padding: 16px 20px;
  margin: 14px 0;
}
article.entity header { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; margin-bottom: 8px; }
.kind-badge { display: inline-block; color: #fff; font-size: 11px; padding: 2px 8px; border-radius: 3px; font-weight: 600; letter-spacing: .04em; }
.kind-badge.functional { background: #6b7280; }
article.entity h4 code { font-size: 17px; background: transparent; padding: 0; }
article.entity p.label { margin: 0; color: var(--muted); font-size: 14px; flex-basis: 100%; }
article.entity p.iri { flex-basis: 100%; margin: 4px 0 0; font-size: 12px; color: var(--muted); }
article.entity p.iri code { font-size: 11px; }
article.entity .comment { margin: 8px 0; font-size: 15px; }
article.entity dl.meta { margin: 12px 0 0; font-size: 14px; display: grid; grid-template-columns: 130px 1fr; gap: 4px 12px; }
article.entity dl.meta dt { font-weight: 600; color: var(--muted); }
article.entity dl.meta dd { margin: 0; }
article.entity .none { color: var(--muted); font-style: italic; }
.summary-row { display: flex; flex-wrap: wrap; gap: 14px; margin: 12px 0 24px; }
.summary-card { flex: 1 1 200px; padding: 14px 18px; border-radius: 8px; color: #fff; }
.summary-card h3 { color: #fff; margin: 0 0 6px; font-size: 16px; }
.summary-card .n { font-size: 26px; font-weight: 700; }
.summary-card .k { font-size: 13px; opacity: .9; }
footer { margin-top: 60px; padding-top: 20px; border-top: 1px solid var(--border); color: var(--muted); font-size: 13px; }

/* -------- language switch -------- */
.lang-switch {
  position: sticky;
  top: 0;
  z-index: 10;
  background: rgba(255,255,255,0.9);
  backdrop-filter: saturate(180%) blur(8px);
  padding: 10px 0 12px;
  margin: -40px -48px 24px;
  padding-left: 48px;
  padding-right: 48px;
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 10px;
  font-size: 13px;
}
.lang-switch .label { color: var(--muted); }
.lang-switch button {
  border: 1px solid var(--border);
  background: #fff;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 13px;
  cursor: pointer;
  color: var(--fg);
}
.lang-switch button.active {
  background: var(--fg);
  color: #fff;
  border-color: var(--fg);
}

/* Bilingual content visibility (default: JP visible; JS toggles on load) */
html[lang="ja"] [data-lang="en"] { display: none; }
html[lang="en"] [data-lang="ja"] { display: none; }
/* For block-level bilingual chunks that need to keep their own display */
html[lang="ja"] p[data-lang="en"],
html[lang="en"] p[data-lang="ja"],
html[lang="ja"] div[data-lang="en"],
html[lang="en"] div[data-lang="ja"] { display: none; }

/* Diagram figure: swap picture srcset via <picture>/<source> already handles it,
   but we also support two <img> approach with data-lang for graceful fallback. */
html[lang="ja"] img[data-lang="en"],
html[lang="en"] img[data-lang="ja"] { display: none; }

@media (max-width: 900px) {
  .wrapper { grid-template-columns: 1fr; }
  nav.toc { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--border); }
  main { padding: 24px; }
  .lang-switch { margin: -24px -24px 20px; padding-left: 24px; padding-right: 24px; }
}
"""


LANG_JS = r"""
(function () {
  var KEY = "himiko-lang";
  function getInitial() {
    // 1) URL ?lang=...  2) localStorage  3) <html lang>  4) default 'ja'
    try {
      var u = new URL(window.location.href);
      var q = u.searchParams.get("lang");
      if (q === "ja" || q === "en") return q;
    } catch (e) {}
    try {
      var v = localStorage.getItem(KEY);
      if (v === "ja" || v === "en") return v;
    } catch (e) {}
    var htmlLang = (document.documentElement.lang || "").toLowerCase();
    if (htmlLang.indexOf("en") === 0) return "en";
    return "ja";
  }
  function apply(lang) {
    document.documentElement.lang = lang;
    var btns = document.querySelectorAll(".lang-switch button[data-set-lang]");
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.toggle("active", btns[i].getAttribute("data-set-lang") === lang);
    }
    try { localStorage.setItem(KEY, lang); } catch (e) {}
  }
  document.addEventListener("DOMContentLoaded", function () {
    apply(getInitial());
    var btns = document.querySelectorAll(".lang-switch button[data-set-lang]");
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener("click", function () {
        apply(this.getAttribute("data-set-lang"));
      });
    }

    // Open the enclosing <details> when navigating to an anchor inside it,
    // so TOC links and direct URL hashes reveal the target instead of
    // scrolling to a collapsed section.
    function openAncestors(el) {
      var node = el;
      while (node && node !== document.body) {
        if (node.tagName === "DETAILS") node.open = true;
        node = node.parentNode;
      }
    }
    function revealHash() {
      var h = window.location.hash;
      if (!h || h.length < 2) return;
      var id;
      try { id = decodeURIComponent(h.slice(1)); } catch (e) { id = h.slice(1); }
      var el = document.getElementById(id);
      if (!el) return;
      openAncestors(el);
      // Re-scroll after open so the browser lands on the now-visible target.
      setTimeout(function () {
        if (typeof el.scrollIntoView === "function") {
          el.scrollIntoView({ block: "start" });
        }
      }, 0);
    }
    revealHash();
    window.addEventListener("hashchange", revealHash);
    // Also handle clicks on same-page anchors even when the hash is unchanged.
    document.addEventListener("click", function (e) {
      var a = e.target.closest && e.target.closest('a[href^="#"]');
      if (!a) return;
      var href = a.getAttribute("href");
      if (!href || href.length < 2) return;
      var id;
      try { id = decodeURIComponent(href.slice(1)); } catch (err) { id = href.slice(1); }
      var el = document.getElementById(id);
      if (el) openAncestors(el);
    });
  });
})();
"""


def build_toc(class_by_layer, op_by_layer, dp_by_layer):
    items = []
    items.append('<h2>' + bi("目次", "Overview") + '</h2>')
    items.append('<ul>')
    items.append(f'  <li><a href="#introduction">{bi("はじめに", "Introduction")}</a></li>')
    items.append(f'  <li><a href="#namespaces">{bi("名前空間", "Namespaces")}</a></li>')
    items.append(f'  <li><a href="#diagram">{bi("概念図", "Concept Diagram")}</a></li>')
    items.append(f'  <li><a href="#vowl">{bi("インタラクティブ可視化 (WebVOWL)", "Interactive Ontology (WebVOWL)")}</a></li>')
    items.append(f'  <li><a href="#summary">{bi("要約", "Summary")}</a></li>')
    items.append('</ul>')
    for layer in LAYERS:
        p = layer["prefix"]
        items.append(
            f'<h2 style="color:{layer["color"]}">{p}: '
            f'{bi(html.escape(layer["title_ja"]), html.escape(layer["title_en"]))}'
            f'</h2>'
        )
        items.append('<ul>')
        if class_by_layer.get(p):
            items.append(f'  <li><a href="#{p}-classes">{bi("クラス", "Classes")}</a>')
            items.append('    <ul>')
            for s in class_by_layer[p]:
                qn = f"{p}:{str(s).split(':')[-1]}"
                items.append(f'      <li class="sub"><a href="#{anchor_id(qn)}"><code>{html.escape(qn)}</code></a></li>')
            items.append('    </ul></li>')
        if op_by_layer.get(p):
            items.append(f'  <li><a href="#{p}-object-properties">{bi("オブジェクトプロパティ", "Object Properties")}</a>')
            items.append('    <ul>')
            for s in op_by_layer[p]:
                qn = f"{p}:{str(s).split(':')[-1]}"
                items.append(f'      <li class="sub"><a href="#{anchor_id(qn)}"><code>{html.escape(qn)}</code></a></li>')
            items.append('    </ul></li>')
        if dp_by_layer.get(p):
            items.append(f'  <li><a href="#{p}-datatype-properties">{bi("データプロパティ", "Datatype Properties")}</a>')
            items.append('    <ul>')
            for s in dp_by_layer[p]:
                qn = f"{p}:{str(s).split(':')[-1]}"
                items.append(f'      <li class="sub"><a href="#{anchor_id(qn)}"><code>{html.escape(qn)}</code></a></li>')
            items.append('    </ul></li>')
        items.append('</ul>')
    return "\n".join(items)


def build_layer_section(g, layer, cls_list, op_list, dp_list):
    p = layer["prefix"]
    out = [f'<section id="layer-{p}">']
    out.append(
        f'<h2 id="{p}" style="border-bottom-color:{layer["color"]}">'
        f'{bi(html.escape(layer["title_ja"]), html.escape(layer["title_en"]))}'
        f' — <code>{p}:</code>'
        f'</h2>'
    )
    out.append(
        f'<div class="layer-intro" style="border-left-color:{layer["color"]}">'
        f'<span data-lang="ja">{html.escape(layer["intro_ja"])}</span>'
        f'<span data-lang="en">{html.escape(layer["intro_en"])}</span>'
        f'</div>'
    )

    if cls_list:
        out.append(f'<details class="section-group" id="{p}-classes">')
        out.append(
            f'  <summary>{bi("クラス", "Classes")} '
            f'<span class="count">({len(cls_list)})</span></summary>'
        )
        for s in cls_list:
            out.append(render_entity_card(g, s, "Class", layer))
        out.append('</details>')
    if op_list:
        out.append(f'<details class="section-group" id="{p}-object-properties">')
        out.append(
            f'  <summary>{bi("オブジェクトプロパティ", "Object Properties")} '
            f'<span class="count">({len(op_list)})</span></summary>'
        )
        for s in op_list:
            out.append(render_entity_card(g, s, "ObjectProperty", layer))
        out.append('</details>')
    if dp_list:
        out.append(f'<details class="section-group" id="{p}-datatype-properties">')
        out.append(
            f'  <summary>{bi("データプロパティ", "Datatype Properties")} '
            f'<span class="count">({len(dp_list)})</span></summary>'
        )
        for s in dp_list:
            out.append(render_entity_card(g, s, "DatatypeProperty", layer))
        out.append('</details>')
    out.append('</section>')
    return "\n".join(out)


def build_html(g: Graph) -> str:
    cls_by, op_by, dp_by = collect_entities(g)

    toc_html = build_toc(cls_by, op_by, dp_by)

    total_cls = sum(len(v) for v in cls_by.values())
    total_op  = sum(len(v) for v in op_by.values())
    total_dp  = sum(len(v) for v in dp_by.values())

    summary_cards = []
    for layer in LAYERS:
        p = layer["prefix"]
        n_cls = len(cls_by.get(p, []))
        n_op  = len(op_by.get(p, []))
        n_dp  = len(dp_by.get(p, []))
        summary_cards.append(
            f'<div class="summary-card" style="background:{layer["color"]}">'
            f'<h3>{bi(html.escape(layer["title_ja"]), html.escape(layer["title_en"]))} '
            f'<code style="background:rgba(255,255,255,0.2); color:#fff">{p}:</code></h3>'
            f'<div><span class="n">{n_cls}</span> <span class="k">{bi("クラス", "Classes")}</span> · '
            f'<span class="n">{n_op}</span> <span class="k">{bi("オブジェクトプロパティ", "Obj Prop")}</span> · '
            f'<span class="n">{n_dp}</span> <span class="k">{bi("データプロパティ", "Data Prop")}</span></div>'
            f'</div>'
        )

    ns_rows = []
    for layer in LAYERS:
        ns_rows.append(
            f'<tr><td><code>{layer["prefix"]}</code></td>'
            f'<td><code>{layer["uri"]}</code></td>'
            f'<td>{bi(html.escape(layer["title_ja"]), html.escape(layer["title_en"]))}</td></tr>'
        )
    for k, v in COMMON_PREFIXES.items():
        ns_rows.append(f'<tr><td><code>{k}</code></td><td><code>{v}</code></td><td></td></tr>')

    section_htmls = []
    for layer in LAYERS:
        p = layer["prefix"]
        section_htmls.append(build_layer_section(
            g, layer, cls_by.get(p, []), op_by.get(p, []), dp_by.get(p, [])
        ))

    html_out = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>HIMIKO Ontology — Historical Micro Knowledge and Ontology</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{CSS}</style>
</head>
<body>
<div class="wrapper">
  <nav class="toc">
    <h2 style="margin-top:0">HIMIKO</h2>
    <p style="font-size:12px;color:var(--muted);margin:0 0 12px">v0.2 · Historical Micro Knowledge and Ontology</p>
    {toc_html}
  </nav>
  <main>
    <div class="lang-switch" role="group" aria-label="Language">
      <span class="label">{bi("言語:", "Language:")}</span>
      <button type="button" data-set-lang="ja">日本語</button>
      <button type="button" data-set-lang="en">English</button>
    </div>

    <h1>HIMIKO Ontology</h1>
    <p class="subtitle">{bi(
        "Historical Micro Knowledge and Ontology — 歴史マイクロナレッジのための概念モデル",
        "Historical Micro Knowledge and Ontology — a conceptual model for historical micro-knowledge"
    )}</p>

    <section id="introduction">
      <h2>{bi("はじめに", "Introduction")}</h2>
      <div class="meta-block">
        <dl>
          <dt>{bi("オントロジーIRI", "Ontology IRI")}</dt><dd><code>urn:himiko:ontology</code></dd>
          <dt>{bi("バージョン", "Version")}</dt><dd>0.2 (2026-07-12)</dd>
          <dt>{bi("作成者", "Creator")}</dt><dd>HIMIKO project</dd>
          <dt>{bi("レイヤ", "Layers")}</dt><dd>hmkp (Physical) · hmki (Intrinsic) · hmke (Extrinsic) · hmkia (Interpretation)</dd>
        </dl>
      </div>
      <p data-lang="ja">HIMIKO は、歴史史料に関わる知識を「史料物理層」「史料内在知識層」「外在知識層」の三層に分け、それらを横断する「解釈行為 Interpretation Act」を独立リソースとして位置付けることで、史料の物理的・文字的特徴からその意味内容、外部典拠、そして知識生成に関わる解釈行為までを一貫した知識グラフとして表現する概念モデルである。本ページは、HIMIKO を実装する 4 層のオントロジー (hmkp, hmki, hmke, hmkia) の全クラス・プロパティを Turtle 定義から自動生成した参照ドキュメントである。</p>
      <p data-lang="en">HIMIKO is a conceptual model that partitions knowledge about historical sources into three layers—Physical, Intrinsic-Knowledge, and Extrinsic-Knowledge—and treats the researcher's Interpretation Act as an independent resource that cuts across all of them. In doing so it represents the physical and textual features of a source, its semantic content, its external references, and the interpretation acts involved in producing that knowledge as a single coherent knowledge graph. This page is a reference document auto-generated from the Turtle definitions of the four ontologies (hmkp, hmki, hmke, hmkia) that implement HIMIKO.</p>
    </section>

    <section id="namespaces">
      <h2>{bi("名前空間", "Namespaces")}</h2>
      <table class="prefixes">
        <thead><tr>
          <td><strong>{bi("プレフィックス", "Prefix")}</strong></td>
          <td><strong>{bi("名前空間URI", "Namespace URI")}</strong></td>
          <td><strong>{bi("説明", "Description")}</strong></td>
        </tr></thead>
        <tbody>
{chr(10).join(ns_rows)}
        </tbody>
      </table>
      <p style="font-size:14px; color:var(--muted)">
        <span data-lang="ja">インスタンス URI は <code>urn:himiko:resource:</code> 配下に置かれる (例: <code>urn:himiko:resource:text:EDCS-00000007</code>)。</span>
        <span data-lang="en">Instance URIs are placed under <code>urn:himiko:resource:</code> (e.g. <code>urn:himiko:resource:text:EDCS-00000007</code>).</span>
      </p>
    </section>

    <section id="diagram">
      <h2>{bi("概念図", "Concept Diagram")}</h2>
      <figure class="diagram-figure">
        <img data-lang="ja" src="diagrams/jp.jpg" alt="HIMIKO 概念図">
        <img data-lang="en" src="diagrams/en.jpg" alt="HIMIKO conceptual diagram">
      </figure>
      <p style="font-size:14px; color:var(--muted)">
        <span data-lang="ja">破線の Interpretation Act は 3 層をまたぐ形で位置付けられ、Annotation・Statement・EntityInContext などの生成に介在する。</span>
        <span data-lang="en">The dashed Interpretation Act sits across all three layers and mediates the creation of Annotation, Statement, EntityInContext, and so on.</span>
      </p>
    </section>

    <section id="vowl">
      <h2>{bi("インタラクティブ可視化 (WebVOWL)", "Interactive Ontology (WebVOWL)")}</h2>
      <p data-lang="ja">4 層 (<code>hmkp</code> / <code>hmki</code> / <code>hmke</code> / <code>hmkia</code>) の全クラス・プロパティを統合した VOWL (Visual Notation for OWL Ontologies) 可視化。ドラッグで再配置、要素クリックで詳細をサイドバーに表示できる。</p>
      <p data-lang="en">A VOWL (Visual Notation for OWL Ontologies) visualisation that merges all classes and properties across the four layers (<code>hmkp</code> / <code>hmki</code> / <code>hmke</code> / <code>hmkia</code>). Drag nodes to reposition, and click any element to inspect details in the side panel.</p>
      <div style="margin:16px 0; border:1px solid var(--border); border-radius:8px; overflow:hidden; background:#fff;">
        <iframe
          src="webvowl/index.html#template"
          title="HIMIKO Ontology — WebVOWL visualization"
          style="width:100%; height:720px; border:0; display:block;"
          loading="lazy"
        ></iframe>
      </div>
      <p style="font-size:13px; color:var(--muted)">
        <span data-lang="ja">右上の「Ontology」から他語彙 (FOAF, GoodRelations など) との比較や、TTL/OWL ファイルの手動アップロードも可能。可視化元データ: <code>webvowl/data/template.json</code> (<code>hmk_owl/himiko_physical.ttl</code> / <code>himiko_intrinsic.ttl</code> / <code>himiko_extrinsic.ttl</code> / <code>himiko_interpretation.ttl</code> を OWL2VOWL でマージ変換)。VOWL 仕様は <a href="http://vowl.visualdataweb.org/" target="_blank" rel="noopener">vowl.visualdataweb.org</a>。</span>
        <span data-lang="en">Use the top-right "Ontology" menu to compare with other vocabularies (FOAF, GoodRelations, etc.) or to upload TTL/OWL files manually. Source data: <code>webvowl/data/template.json</code> (merged from <code>hmk_owl/himiko_physical.ttl</code> / <code>himiko_intrinsic.ttl</code> / <code>himiko_extrinsic.ttl</code> / <code>himiko_interpretation.ttl</code> via OWL2VOWL). See <a href="http://vowl.visualdataweb.org/" target="_blank" rel="noopener">vowl.visualdataweb.org</a> for the VOWL specification.</span>
      </p>
    </section>

    <section id="summary">
      <h2>{bi("要約", "Summary")}</h2>
      <div class="summary-row">
        {chr(10).join(summary_cards)}
      </div>
      <p style="font-size:14px; color:var(--muted)">
        <span data-lang="ja">合計: <strong>{total_cls}</strong> クラス · <strong>{total_op}</strong> オブジェクトプロパティ · <strong>{total_dp}</strong> データプロパティ</span>
        <span data-lang="en">Total: <strong>{total_cls}</strong> classes · <strong>{total_op}</strong> object properties · <strong>{total_dp}</strong> datatype properties</span>
      </p>
    </section>

{chr(10).join(section_htmls)}

    <footer>
      <span data-lang="ja">生成元: <code>ontology/hmk_owl/*.ttl</code>, ビルダー: <code>build_docs.py</code></span>
      <span data-lang="en">Generated from <code>ontology/hmk_owl/*.ttl</code> by <code>build_docs.py</code></span>
      <br>HIMIKO project · 2026
    </footer>
  </main>
</div>
<script>{LANG_JS}</script>
</body>
</html>
"""
    return html_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default=str(SCRIPT_DIR / "himiko.html"),
                    help="出力 HTML パス (デフォルト: ontology/himiko.html)")
    args = ap.parse_args()

    g = load_all_layers()
    print(f"Loaded {len(g)} triples from {len(LAYERS)} ontology files")

    html_out = build_html(g)
    Path(args.output).write_text(html_out, encoding="utf-8")
    print(f"→ Wrote {args.output} ({len(html_out):,} bytes)")


if __name__ == "__main__":
    main()
