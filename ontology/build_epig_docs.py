#!/usr/bin/env python3
"""
Epigraphic Careers Ontology (epig:) 用の HTML ドキュメントビルダー。

入力: ontology/epig_ontology.ttl (主)、ontology/hmk_owl/himiko_intrinsic.ttl (参照)
出力: ontology/epig.html

owl:deprecated true が付いたクラス・プロパティは列挙からもドキュメント本体からも
除外する。hmki: 名前空間のリソースは epig: が参照する場合に限り「関連語彙」として
別セクションに表示する。

使用方法:
    python build_epig_docs.py
    python build_epig_docs.py -o /tmp/epig_preview.html
"""

import argparse
import html
from pathlib import Path
from collections import defaultdict

from rdflib import Graph, URIRef, Literal, BNode
from rdflib.namespace import RDF, RDFS, OWL, XSD


SCRIPT_DIR = Path(__file__).parent
EPIG_TTL = SCRIPT_DIR / "epig_ontology.ttl"
HMKI_TTL = SCRIPT_DIR / "hmk_owl" / "himiko_intrinsic.ttl"

EPIG_NS = "http://epigraphic-careers.org/ontology#"
HMKI_NS = "urn:himiko:ontology:intrinsic:"
HMKP_NS = "urn:himiko:ontology:physical:"
HMKIA_NS = "urn:himiko:ontology:interpretation:"
HMKE_NS = "urn:himiko:ontology:extrinsic:"

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
    "hmkp":    HMKP_NS,
    "hmki":    HMKI_NS,
    "hmkia":   HMKIA_NS,
    "hmke":    HMKE_NS,
    "epig":    EPIG_NS,
}


# ---------------- graph helpers ----------------

def load_graphs():
    g_epig = Graph()
    g_epig.parse(EPIG_TTL, format="turtle")
    g_hmki = Graph()
    g_hmki.parse(HMKI_TTL, format="turtle")
    return g_epig, g_hmki


def qname(uri) -> str:
    if isinstance(uri, BNode):
        return f"_:{uri}"
    s = str(uri)
    # longest prefix wins
    matches = sorted(
        ((pref, ns) for pref, ns in COMMON_PREFIXES.items() if s.startswith(ns)),
        key=lambda x: -len(x[1]),
    )
    if matches:
        pref, ns = matches[0]
        return f"{pref}:{s[len(ns):]}"
    return s


def anchor_id(qn: str) -> str:
    return qn.replace(":", "-").replace("/", "-")


def is_deprecated(g: Graph, s) -> bool:
    return (s, OWL.deprecated, Literal(True)) in g


def get_label(g: Graph, s, lang: str = "en") -> str:
    for _, _, o in g.triples((s, RDFS.label, None)):
        if isinstance(o, Literal) and (o.language or "") == lang:
            return str(o)
    for _, _, o in g.triples((s, RDFS.label, None)):
        if isinstance(o, Literal):
            return str(o)
    return ""


def get_comment(g: Graph, s, lang: str = "en") -> str:
    matches_lang = []
    fallback = []
    for _, _, o in g.triples((s, RDFS.comment, None)):
        if isinstance(o, Literal):
            if (o.language or "") == lang:
                matches_lang.append(str(o))
            else:
                fallback.append(str(o))
    if matches_lang:
        return "<br>".join(matches_lang)
    return "<br>".join(fallback)


def rdf_list(g: Graph, head):
    items = []
    while head and head != RDF.nil:
        first = g.value(head, RDF.first)
        if first is not None:
            items.append(first)
        head = g.value(head, RDF.rest)
    return items


def link(uri, in_scope_uris: set) -> str:
    if isinstance(uri, BNode):
        return "<em>anonymous</em>"
    qn = qname(uri)
    if str(uri) in in_scope_uris:
        return f'<a href="#{anchor_id(qn)}">{html.escape(qn)}</a>'
    return f'<a href="{html.escape(str(uri))}" rel="external" target="_blank">{html.escape(qn)}</a>'


def format_dr(g: Graph, s, predicate, in_scope_uris: set) -> str:
    parts = []
    for _, _, o in g.triples((s, predicate, None)):
        if isinstance(o, BNode):
            union = list(g.objects(o, OWL.unionOf))
            if union:
                items = [link(item, in_scope_uris) for item in rdf_list(g, union[0])]
                parts.append("(" + " ∪ ".join(items) + ")")
            else:
                parts.append("<em>anonymous class</em>")
        else:
            parts.append(link(o, in_scope_uris))
    return ", ".join(parts) if parts else "<span class='none'>—</span>"


def collect_entities(g: Graph, ns: str):
    classes, ops, dps = [], [], []
    for s in g.subjects(RDF.type, OWL.Class):
        if isinstance(s, BNode):
            continue
        if not str(s).startswith(ns):
            continue
        if is_deprecated(g, s):
            continue
        classes.append(s)
    for s in g.subjects(RDF.type, OWL.ObjectProperty):
        if isinstance(s, BNode):
            continue
        if not str(s).startswith(ns):
            continue
        if is_deprecated(g, s):
            continue
        ops.append(s)
    for s in g.subjects(RDF.type, OWL.DatatypeProperty):
        if isinstance(s, BNode):
            continue
        if not str(s).startswith(ns):
            continue
        if is_deprecated(g, s):
            continue
        dps.append(s)
    for lst in (classes, ops, dps):
        lst.sort(key=lambda u: str(u))
    return classes, ops, dps


def collect_referenced_hmki(g_epig: Graph, g_hmki: Graph):
    """epig の subject/object から参照される hmki: リソースだけ拾う。"""
    referenced = set()
    for s, p, o in g_epig:
        for term in (s, o):
            if isinstance(term, URIRef) and str(term).startswith(HMKI_NS):
                referenced.add(term)
    # subClassOf / subPropertyOf も辿る (1段だけ)
    additional = set()
    for term in referenced:
        for _, _, o in g_hmki.triples((term, RDFS.subClassOf, None)):
            if isinstance(o, URIRef) and str(o).startswith(HMKI_NS):
                additional.add(o)
        for _, _, o in g_hmki.triples((term, RDFS.subPropertyOf, None)):
            if isinstance(o, URIRef) and str(o).startswith(HMKI_NS):
                additional.add(o)
    referenced |= additional

    cls, ops, dps = [], [], []
    for term in referenced:
        if is_deprecated(g_hmki, term):
            continue
        if (term, RDF.type, OWL.Class) in g_hmki:
            cls.append(term)
        elif (term, RDF.type, OWL.ObjectProperty) in g_hmki:
            ops.append(term)
        elif (term, RDF.type, OWL.DatatypeProperty) in g_hmki:
            dps.append(term)
    for lst in (cls, ops, dps):
        lst.sort(key=lambda u: str(u))
    return cls, ops, dps


# ---------------- rendering ----------------

def render_entity_card(g: Graph, s, kind: str, color: str, in_scope_uris: set):
    qn = qname(s)
    label = get_label(g, s, "en")
    comment = get_comment(g, s, "en")

    super_rel = RDFS.subClassOf if kind == "Class" else RDFS.subPropertyOf
    super_html = format_dr(g, s, super_rel, in_scope_uris)
    domain_html = format_dr(g, s, RDFS.domain, in_scope_uris)
    range_html = format_dr(g, s, RDFS.range, in_scope_uris)

    subs = []
    for sub_s, _, _ in g.triples((None, super_rel, s)):
        if isinstance(sub_s, BNode):
            continue
        if is_deprecated(g, sub_s):
            continue
        subs.append(link(sub_s, in_scope_uris))
    sub_html = ", ".join(subs)

    equiv_rel = OWL.equivalentClass if kind == "Class" else OWL.equivalentProperty
    equivs = [link(o, in_scope_uris) for _, _, o in g.triples((s, equiv_rel, None))]
    equiv_html = ", ".join(equivs)

    see_also = [link(o, in_scope_uris) for _, _, o in g.triples((s, RDFS.seeAlso, None))]
    see_also_html = ", ".join(see_also)

    is_functional = (s, RDF.type, OWL.FunctionalProperty) in g

    kind_label = {
        "Class": "Class",
        "ObjectProperty": "Object Property",
        "DatatypeProperty": "Datatype Property",
    }[kind]

    lines = [f'<article class="entity {kind.lower()}" id="{anchor_id(qn)}" style="border-left-color:{color}">']
    lines.append('<header>')
    lines.append(f'  <span class="kind-badge" style="background:{color}">{html.escape(kind_label)}</span>')
    if is_functional:
        lines.append('  <span class="kind-badge functional">functional</span>')
    lines.append(f'  <h4><code>{html.escape(qn)}</code></h4>')
    if label:
        lines.append(f'  <p class="label">{html.escape(label)}</p>')
    lines.append(f'  <p class="iri"><span class="k">IRI:</span> <code>{html.escape(str(s))}</code></p>')
    lines.append('</header>')

    if comment:
        lines.append(f'<p class="comment">{comment}</p>')

    lines.append('<dl class="meta">')
    if kind != "Class":
        lines.append(f'  <dt>Domain</dt><dd>{domain_html}</dd>')
        lines.append(f'  <dt>Range</dt><dd>{range_html}</dd>')
    if super_html and super_html != "<span class='none'>—</span>":
        key = "Super-class" if kind == "Class" else "Super-property"
        lines.append(f'  <dt>{key}</dt><dd>{super_html}</dd>')
    if sub_html:
        key = "Sub-class(es)" if kind == "Class" else "Sub-property(ies)"
        lines.append(f'  <dt>{key}</dt><dd>{sub_html}</dd>')
    if equiv_html:
        key = "Equivalent class" if kind == "Class" else "Equivalent property"
        lines.append(f'  <dt>{key}</dt><dd>{equiv_html}</dd>')
    if see_also_html:
        lines.append(f'  <dt>See also</dt><dd>{see_also_html}</dd>')
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
  --accent: #0ea5e9;
  --hmki-color: #f59e0b;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", "Segoe UI", sans-serif;
  color: var(--fg);
  background: var(--bg);
  line-height: 1.65;
}
.wrapper { display: grid; grid-template-columns: 270px 1fr; min-height: 100vh; }
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
.layer-intro { padding: 12px 18px; border-left: 4px solid; background: var(--sidebar-bg); border-radius: 4px; margin: 12px 0 24px; font-size: 14px; }
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
@media (max-width: 900px) {
  .wrapper { grid-template-columns: 1fr; }
  nav.toc { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--border); }
  main { padding: 24px; }
}
"""


def build_toc(epig_cls, epig_op, epig_dp, hmki_cls, hmki_op, hmki_dp):
    items = ['<h2 style="margin-top:0">epig:</h2>',
             '<p style="font-size:12px;color:var(--muted);margin:0 0 12px">v2.0 · Epigraphic Careers Ontology</p>',
             '<h2>Contents</h2>',
             '<ul>',
             '  <li><a href="#introduction">Introduction</a></li>',
             '  <li><a href="#namespaces">Namespaces</a></li>',
             '  <li><a href="#summary">Summary</a></li>',
             '  <li><a href="#vowl">Interactive Ontology (WebVOWL)</a></li>',
             '</ul>']

    def section(header, color, kind_id, items_list):
        out = [f'<h2 style="color:{color}">{header}</h2>', '<ul>']
        for s in items_list:
            qn = qname(s)
            out.append(f'  <li class="sub"><a href="#{anchor_id(qn)}"><code>{html.escape(qn)}</code></a></li>')
        out.append('</ul>')
        return out

    items += section("epig: Classes", "var(--accent)", "cls", epig_cls)
    items += section("epig: Object Properties", "#6366f1", "op", epig_op)
    items += section("epig: Datatype Properties", "#10b981", "dp", epig_dp)

    if hmki_cls or hmki_op or hmki_dp:
        items.append('<h2 style="color:var(--hmki-color)">Related — hmki:</h2>')
        items.append('<ul>')
        for s in hmki_cls + hmki_op + hmki_dp:
            qn = qname(s)
            items.append(f'  <li class="sub"><a href="#{anchor_id(qn)}"><code>{html.escape(qn)}</code></a></li>')
        items.append('</ul>')

    return "\n".join(items)


def build_section(g, title, color, intro, kind, entities, in_scope_uris, section_id):
    out = [f'<section id="{section_id}">',
           f'<h2 style="border-bottom-color:{color}">{html.escape(title)}</h2>']
    if intro:
        out.append(f'<div class="layer-intro" style="border-left-color:{color}">{intro}</div>')
    if entities:
        for s in entities:
            out.append(render_entity_card(g, s, kind, color, in_scope_uris))
    else:
        out.append('<p style="color:var(--muted); font-style:italic">(none)</p>')
    out.append('</section>')
    return "\n".join(out)


def build_html(g_epig: Graph, g_hmki: Graph) -> str:
    epig_cls, epig_op, epig_dp = collect_entities(g_epig, EPIG_NS)
    hmki_cls, hmki_op, hmki_dp = collect_referenced_hmki(g_epig, g_hmki)

    # in-scope URI set for internal linking
    in_scope = set(str(s) for s in epig_cls + epig_op + epig_dp)
    in_scope |= set(str(s) for s in hmki_cls + hmki_op + hmki_dp)

    toc_html = build_toc(epig_cls, epig_op, epig_dp, hmki_cls, hmki_op, hmki_dp)

    # Ontology metadata
    onto_iri = URIRef("http://epigraphic-careers.org/ontology")
    version = ""
    for _, _, o in g_epig.triples((onto_iri, OWL.versionInfo, None)):
        version = str(o)
    creator = ""
    for _, _, o in g_epig.triples((onto_iri, URIRef("http://purl.org/dc/terms/creator"), None)):
        creator = str(o)
    description = ""
    for _, _, o in g_epig.triples((onto_iri, URIRef("http://purl.org/dc/terms/description"), None)):
        if isinstance(o, Literal) and (o.language or "en") in ("en", ""):
            description = str(o)
            break
    if not description:
        for _, _, o in g_epig.triples((onto_iri, URIRef("http://purl.org/dc/terms/description"), None)):
            description = str(o)
            break

    ns_rows = []
    for pref, ns in COMMON_PREFIXES.items():
        ns_rows.append(f'<tr><td><code>{pref}</code></td><td><code>{html.escape(ns)}</code></td></tr>')

    summary_cards = (
        f'<div class="summary-card" style="background:var(--accent)"><h3>Classes</h3>'
        f'<div><span class="n">{len(epig_cls)}</span> <span class="k">owl:Class</span></div></div>'
        f'<div class="summary-card" style="background:#6366f1"><h3>Object Properties</h3>'
        f'<div><span class="n">{len(epig_op)}</span> <span class="k">owl:ObjectProperty</span></div></div>'
        f'<div class="summary-card" style="background:#10b981"><h3>Datatype Properties</h3>'
        f'<div><span class="n">{len(epig_dp)}</span> <span class="k">owl:DatatypeProperty</span></div></div>'
        f'<div class="summary-card" style="background:var(--hmki-color)"><h3>Related hmki</h3>'
        f'<div><span class="n">{len(hmki_cls) + len(hmki_op) + len(hmki_dp)}</span> <span class="k">imported entities</span></div></div>'
    )

    epig_classes_section = build_section(
        g_epig, "Classes — epig:", "var(--accent)",
        "Core classes of the epigraphic careers ontology. <code>foaf:Person</code> and other external classes referenced by <code>epig:</code> properties are shown inline in Domain/Range fields.",
        "Class", epig_cls, in_scope, "epig-classes")

    epig_op_section = build_section(
        g_epig, "Object Properties — epig:", "#6366f1",
        "Object properties (link nodes to nodes).", "ObjectProperty", epig_op, in_scope, "epig-object-properties")

    epig_dp_section = build_section(
        g_epig, "Datatype Properties — epig:", "#10b981",
        "Datatype properties (attach literal values to nodes).", "DatatypeProperty", epig_dp, in_scope, "epig-datatype-properties")

    hmki_sections = []
    if hmki_cls or hmki_op or hmki_dp:
        hmki_sections.append('<section id="hmki-related">')
        hmki_sections.append(f'<h2 style="border-bottom-color:var(--hmki-color)">Related Vocabulary — hmki: (imported)</h2>')
        hmki_sections.append(
            '<div class="layer-intro" style="border-left-color:var(--hmki-color)">'
            'HIMIKO Intrinsic Knowledge Layer (<code>hmki:</code>) entities referenced by <code>epig:</code>. '
            'The full <code>hmki</code> layer is documented in <a href="himiko.html">himiko.html</a>; '
            'only the fragments touched by <code>epig:</code> are reproduced here for context.'
            '</div>'
        )
        if hmki_cls:
            hmki_sections.append('<h3>Classes</h3>')
            for s in hmki_cls:
                hmki_sections.append(render_entity_card(g_hmki, s, "Class", "var(--hmki-color)", in_scope))
        if hmki_op:
            hmki_sections.append('<h3>Object Properties</h3>')
            for s in hmki_op:
                hmki_sections.append(render_entity_card(g_hmki, s, "ObjectProperty", "var(--hmki-color)", in_scope))
        if hmki_dp:
            hmki_sections.append('<h3>Datatype Properties</h3>')
            for s in hmki_dp:
                hmki_sections.append(render_entity_card(g_hmki, s, "DatatypeProperty", "var(--hmki-color)", in_scope))
        hmki_sections.append('</section>')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Epigraphic Careers Ontology (epig:)</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{CSS}</style>
</head>
<body>
<div class="wrapper">
  <nav class="toc">
    {toc_html}
  </nav>
  <main>
    <h1>Epigraphic Careers Ontology</h1>
    <p class="subtitle">A vocabulary for describing persons, careers, benefactions, and communities recorded in Roman inscriptions.</p>

    <section id="introduction">
      <h2>Introduction</h2>
      <div class="meta-block">
        <dl>
          <dt>Ontology IRI</dt><dd><code>http://epigraphic-careers.org/ontology</code></dd>
          <dt>Version</dt><dd>{html.escape(version) or "—"}</dd>
          <dt>Creator</dt><dd>{html.escape(creator) or "—"}</dd>
          <dt>Imports</dt><dd><code>hmkp:</code>, <code>hmki:</code>, <code>hmkia:</code>, <code>prov:</code></dd>
        </dl>
      </div>
      <p>{html.escape(description) or "The <code>epig:</code> ontology describes epigraphic careers by extending the HIMIKO upper ontology."}</p>
      <p style="font-size:13px; color:var(--muted)">This page is auto-generated from <code>ontology/epig_ontology.ttl</code>. Entities marked with <code>owl:deprecated true</code> are omitted.</p>
    </section>

    <section id="namespaces">
      <h2>Namespaces</h2>
      <table class="prefixes">
        <thead><tr>
          <td><strong>Prefix</strong></td>
          <td><strong>Namespace URI</strong></td>
        </tr></thead>
        <tbody>
{chr(10).join(ns_rows)}
        </tbody>
      </table>
    </section>

    <section id="summary">
      <h2>Summary</h2>
      <div class="summary-row">
        {summary_cards}
      </div>
    </section>

    <section id="vowl">
      <h2>Interactive Ontology (WebVOWL)</h2>
      <p>A VOWL (Visual Notation for OWL Ontologies) visualisation of <code>epig:</code>, with the referenced <code>hmki:</code> vocabulary merged in. Drag nodes to reposition, and click any element to inspect details in the side panel.</p>
      <div style="margin:16px 0; border:1px solid var(--border); border-radius:8px; overflow:hidden; background:#fff;">
        <iframe
          src="webvowl/index.html#epig"
          title="Epigraphic Careers Ontology — WebVOWL visualization"
          style="width:100%; height:720px; border:0; display:block;"
          loading="lazy"
        ></iframe>
      </div>
      <p style="font-size:13px; color:var(--muted)">
        Source: <code>webvowl/data/epig.json</code>, generated from <code>ontology/epig_ontology.ttl</code> plus the referenced fragments of <code>hmk_owl/himiko_intrinsic.ttl</code> via OWL2VOWL 0.2.0. Regenerate with <code>python ontology/build_webvowl.py --target epig</code>. See <a href="http://vowl.visualdataweb.org/" target="_blank" rel="noopener">vowl.visualdataweb.org</a> for the VOWL specification.
      </p>
    </section>

{epig_classes_section}

{epig_op_section}

{epig_dp_section}

{chr(10).join(hmki_sections)}

    <footer>
      Generated from <code>ontology/epig_ontology.ttl</code> (and referenced fragments of <code>hmk_owl/himiko_intrinsic.ttl</code>) by <code>build_epig_docs.py</code>.
    </footer>
  </main>
</div>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default=str(SCRIPT_DIR / "epig.html"),
                    help="Output HTML path (default: ontology/epig.html)")
    args = ap.parse_args()

    g_epig, g_hmki = load_graphs()
    print(f"epig: {len(g_epig)} triples; hmki: {len(g_hmki)} triples")

    out = build_html(g_epig, g_hmki)
    Path(args.output).write_text(out, encoding="utf-8")
    print(f"→ Wrote {args.output} ({len(out):,} bytes)")


if __name__ == "__main__":
    main()
