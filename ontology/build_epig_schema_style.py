#!/usr/bin/env python3
"""
論文・書籍掲載用の schema.org 風リファレンス表を生成するビルダー — epig 版。

HIMIKO 版 (build_schema_style_tex.py / build_schema_style_tables.py) と同じ
schema.org リファレンス形式で、epig オントロジー (epig_ontology.ttl) の
クラス・プロパティを 2 表 (クラス表・プロパティ表) にまとめる。
LaTeX (booktabs + longtable) と HTML の両方を出力する。

  クラス表     : クラス URI | ラベル | 上位クラス
  プロパティ表  : プロパティ URI | ラベル (逆向き・上位・関数的を併記) | 定義域 | 値域

owl:deprecated true が付いたエントリは除外する。
object property と datatype property は 1 つのプロパティ表に統合する。

出力:
  ontology/figs/epig_schema_style_tables.tex
  ontology/figs/epig_schema_style_tables.html

使用方法:
    python build_epig_schema_style.py
    python build_epig_schema_style.py --tex-only
    python build_epig_schema_style.py --html-only
    python build_epig_schema_style.py --start-no 7-1   # LaTeX caption に表番号併記
"""

import argparse
import html
from pathlib import Path

from rdflib import Graph, Literal, BNode
from rdflib.namespace import RDF, RDFS, OWL

SCRIPT_DIR = Path(__file__).parent
EPIG_TTL = SCRIPT_DIR / "epig_ontology.ttl"
EPIG_NS = "http://epigraphic-careers.org/ontology#"

PREFIXES = {
    "epig":    EPIG_NS,
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
    "hmke":    "urn:himiko:ontology:extrinsic:",
    "hmkia":   "urn:himiko:ontology:interpretation:",
}


# ---------------- graph helpers ----------------

def load_graph():
    g = Graph()
    g.parse(EPIG_TTL, format="turtle")
    return g


def qname(uri) -> str:
    if isinstance(uri, BNode):
        return f"_:{uri}"
    s = str(uri)
    for pref, ns in sorted(PREFIXES.items(), key=lambda kv: len(kv[1]), reverse=True):
        if s.startswith(ns):
            return f"{pref}:{s[len(ns):]}"
    return s


def is_epig(uri) -> bool:
    return str(uri).startswith(EPIG_NS)


def is_deprecated(g: Graph, s) -> bool:
    for o in g.objects(s, OWL.deprecated):
        if isinstance(o, Literal) and str(o).lower() == "true":
            return True
    return False


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


def dr_parts(g: Graph, s, predicate):
    """domain / range / subClassOf の値を (kind, [qname,...]) のリストで返す。"""
    parts = []
    for _, _, o in g.triples((s, predicate, None)):
        if isinstance(o, BNode):
            union = list(g.objects(o, OWL.unionOf))
            if union:
                parts.append(("union", [qname(x) for x in rdf_list(g, union[0])]))
            else:
                parts.append(("plain", ["匿名クラス"]))
        else:
            parts.append(("plain", [qname(o)]))
    return parts


def collect(g: Graph):
    classes, props = [], []
    for s in g.subjects(RDF.type, OWL.Class):
        if isinstance(s, BNode) or not is_epig(s) or is_deprecated(g, s):
            continue
        classes.append(s)
    for ptype in (OWL.ObjectProperty, OWL.DatatypeProperty):
        for s in g.subjects(RDF.type, ptype):
            if isinstance(s, BNode) or not is_epig(s) or is_deprecated(g, s):
                continue
            if s not in props:
                props.append(s)
    classes.sort(key=lambda u: str(u))
    props.sort(key=lambda u: str(u))
    return classes, props


def prop_notes(g: Graph, s):
    """(逆向き: … / 上位: … / 関数的プロパティ) の注記要素リストを返す。

    各要素は (種別ラベル, [qname,...]) か ("func", None)。
    """
    notes = []
    inv = [qname(o) for o in g.objects(s, OWL.inverseOf)]
    inv += [qname(subj) for subj in g.subjects(OWL.inverseOf, s)]
    inv = sorted(set(inv))
    if inv:
        notes.append(("逆向き", inv))
    sup = sorted({qname(o) for o in g.objects(s, RDFS.subPropertyOf)})
    if sup:
        notes.append(("上位", sup))
    if (s, RDF.type, OWL.FunctionalProperty) in g:
        notes.append(("func", None))
    return notes


# ---------------- LaTeX rendering ----------------

_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def tex_escape(s: str) -> str:
    if not s:
        return ""
    out = []
    for ch in s:
        if ch in _LATEX_SPECIALS:
            out.append(_LATEX_SPECIALS[ch])
        elif ch == "∪":
            out.append(r" $\cup$ ")
        else:
            out.append(ch)
    return "".join(out)


def _breakable(qn: str) -> str:
    """QName に \\allowbreak 挿入点を持つエスケープ済み文字列を返す (折り返し用)。"""
    out = []
    for i, ch in enumerate(qn):
        out.append(_LATEX_SPECIALS.get(ch, ch))
        nxt = qn[i + 1] if i + 1 < len(qn) else ""
        if ch in (":", "_"):
            out.append(r"\allowbreak{}")
        elif (ch.islower() or ch.isdigit()) and nxt.isupper():
            out.append(r"\allowbreak{}")
    return "".join(out)


def tex_tt(qn: str) -> str:
    return r"\texttt{" + _breakable(qn) + "}"


def tex_dr_cell(parts) -> str:
    if not parts:
        return "---"
    rendered = []
    for kind, items in parts:
        if kind == "union":
            rendered.append("(" + r" $\cup$ ".join(tex_tt(x) for x in items) + ")")
        else:
            rendered.append(tex_tt(items[0]))
    return ", ".join(rendered)


def tex_label_cell(g: Graph, s, label: str) -> str:
    main = tex_escape(label) if label else ""
    segs = []
    for kind, items in prop_notes(g, s):
        if kind == "func":
            segs.append("関数的プロパティ")
        else:
            segs.append(f"{kind}: " + ", ".join(tex_tt(q) for q in items))
    note = (r" {\small (" + " / ".join(segs) + ")}") if segs else ""
    if not main and not segs:
        return "---"
    return (main if main else "---") + note


def _longtable(colspec, header_cells, body_rows, caption):
    n = len(header_cells)
    header = " & ".join(header_cells) + r" \\"
    L = [r"\begin{longtable}{" + colspec + "}",
         r"\caption{" + caption + r"}\\", r"\toprule", header, r"\midrule",
         r"\endfirsthead",
         r"\multicolumn{" + str(n) + r"}{l}{\small （前ページからの続き）}\\",
         r"\toprule", header, r"\midrule", r"\endhead",
         r"\midrule",
         r"\multicolumn{" + str(n) + r"}{r}{\small （次ページへ続く）}\\",
         r"\endfoot", r"\bottomrule", r"\endlastfoot"]
    L.extend(body_rows)
    L.append(r"\end{longtable}")
    return "\n".join(L)


def _cap(text, no):
    return (f"表 {no}\\quad {tex_escape(text)}") if no else tex_escape(text)


def _next_no(no):
    if not no:
        return None
    if "-" in no:
        h, _, t = no.rpartition("-")
        if t.isdigit():
            return f"{h}-{int(t)+1}"
    return str(int(no)+1) if no.isdigit() else no


PREAMBLE = r"""% ============================================================
%  epig オントロジー リファレンス表 (schema.org 風 / booktabs+longtable)
%  自動生成元: ontology/epig_ontology.ttl
%  ビルダー:   ontology/build_epig_schema_style.py
%
%  本文に \input{epig_schema_style_tables.tex} で取り込む。
%  プリアンブルに以下が必要:
%      \usepackage{booktabs}
%      \usepackage{longtable}
%      \usepackage{array}
%      \usepackage{amssymb}   % \cup (∪) 用
% ============================================================
"""


def build_tex(g, classes, props, start_no) -> str:
    no = start_no
    blocks = [PREAMBLE]

    # クラス表
    rows = []
    for s in classes:
        rows.append(f"{tex_tt(qname(s))} & {tex_escape(get_label_ja(g, s)) or '---'} "
                    f"& {tex_dr_cell(dr_parts(g, s, RDFS.subClassOf))} \\\\")
    colspec = (r"@{}>{\raggedright\arraybackslash}p{0.30\linewidth} "
               r">{\raggedright\arraybackslash}p{0.38\linewidth} "
               r">{\raggedright\arraybackslash}p{0.30\linewidth}@{}")
    blocks.append(_longtable(
        colspec,
        [r"\textbf{クラス URI}", r"\textbf{ラベル}", r"\textbf{上位クラス}"],
        rows, _cap(f"epig オントロジー のクラス（{len(classes)} 件）", no)))
    no = _next_no(no)

    # プロパティ表
    rows = []
    for s in props:
        rows.append(f"{tex_tt(qname(s))} & {tex_label_cell(g, s, get_label_ja(g, s))} "
                    f"& {tex_dr_cell(dr_parts(g, s, RDFS.domain))} "
                    f"& {tex_dr_cell(dr_parts(g, s, RDFS.range))} \\\\")
    colspec = (r"@{}>{\raggedright\arraybackslash}p{0.22\linewidth} "
               r">{\raggedright\arraybackslash}p{0.34\linewidth} "
               r">{\raggedright\arraybackslash}p{0.20\linewidth} "
               r">{\raggedright\arraybackslash}p{0.20\linewidth}@{}")
    blocks.append(_longtable(
        colspec,
        [r"\textbf{プロパティ URI}", r"\textbf{ラベル}",
         r"\textbf{定義域}", r"\textbf{値域}"],
        rows, _cap(f"epig オントロジー のプロパティ（{len(props)} 件）", no)))

    return "\n\n".join(blocks) + "\n"


# ---------------- HTML rendering ----------------

CSS = """
:root { --fg:#1f2937; --muted:#6b7280; --border:#333; --code-bg:#f3f4f6; }
* { box-sizing: border-box; }
body { margin:0; padding:32px 40px 48px;
  font-family:"Hiragino Mincho ProN","Yu Mincho","Noto Serif JP",serif;
  color:var(--fg); background:#fff; line-height:1.55; font-size:12px; }
h1 { font-size:20px; margin:0 0 4px; }
.subtitle { color:var(--muted); margin:0 0 24px; font-size:13px; }
.caption { font-weight:700; font-size:12px; margin:16px 0 4px; }
table.sform { border-collapse:collapse; width:100%; font-size:11px; margin:0 0 8px; }
table.sform th, table.sform td { border:1px solid var(--border); padding:5px 9px;
  text-align:left; vertical-align:top; }
table.sform thead th { font-weight:700; background:#fff; white-space:nowrap; }
table.sform td.uri code, table.sform td.val code {
  font-family:"SF Mono",ui-monospace,Menlo,Consolas,monospace; font-size:10.5px;
  white-space:nowrap; }
table.sform td.label .note { color:var(--muted); }
table.sform .none { color:var(--muted); }
.layer-intro { color:var(--muted); font-size:11.5px; margin:4px 0 12px; }
footer { margin-top:32px; color:var(--muted); font-size:10.5px; }
@page { size:A4; margin:20mm 15mm; }
@media print { body{padding:0;} .caption{page-break-after:avoid;}
  table.sform tr{page-break-inside:avoid;} table.sform thead{display:table-header-group;} }
"""


def esc(s):
    return html.escape(s or "")


def none_cell(t="—"):
    return f'<span class="none">{t}</span>'


def html_dr_cell(parts):
    if not parts:
        return none_cell()
    out = []
    for kind, items in parts:
        if kind == "union":
            out.append("(" + " ∪ ".join(f"<code>{esc(x)}</code>" for x in items) + ")")
        else:
            out.append(f"<code>{esc(items[0])}</code>")
    return ", ".join(out)


def html_label_cell(g, s, label):
    main = esc(label)
    segs = []
    for kind, items in prop_notes(g, s):
        if kind == "func":
            segs.append("関数的プロパティ")
        else:
            segs.append(f"{kind}: " + ", ".join(f"<code>{esc(q)}</code>" for q in items))
    note = f' <span class="note">({" / ".join(segs)})</span>' if segs else ""
    if not main and not segs:
        return none_cell()
    return (main or none_cell()) + note


def build_html(g, classes, props) -> str:
    crows = []
    for s in classes:
        crows.append(
            f'<tr><td class="uri"><code>{esc(qname(s))}</code></td>'
            f'<td class="label">{esc(get_label_ja(g, s)) or none_cell()}</td>'
            f'<td class="val">{html_dr_cell(dr_parts(g, s, RDFS.subClassOf))}</td></tr>')
    prows = []
    for s in props:
        prows.append(
            f'<tr><td class="uri"><code>{esc(qname(s))}</code></td>'
            f'<td class="label">{html_label_cell(g, s, get_label_ja(g, s))}</td>'
            f'<td class="val">{html_dr_cell(dr_parts(g, s, RDFS.domain))}</td>'
            f'<td class="val">{html_dr_cell(dr_parts(g, s, RDFS.range))}</td></tr>')
    return f"""<!DOCTYPE html>
<html lang="ja">
<head><meta charset="UTF-8">
<title>epig オントロジー リファレンス（schema.org 風）</title>
<style>{CSS}</style></head>
<body>
<h1>epig オントロジー リファレンス表</h1>
<p class="subtitle">Epigraphic Careers Ontology — 論文・書籍掲載用 (schema.org リファレンス形式)</p>
<p class="layer-intro">
凡例 — <strong>URI</strong> は修飾名。プロパティ欄の <strong>(逆向き: …)</strong> は
<code>owl:inverseOf</code>、<strong>(上位: …)</strong> は <code>rdfs:subPropertyOf</code>、
<strong>関数的プロパティ</strong> は <code>owl:FunctionalProperty</code>、
値域欄の <code>(A ∪ B)</code> は <code>owl:unionOf</code> を示す。
<code>owl:deprecated</code> のエントリは除外している。
</p>

<p class="caption">表　epig オントロジー のクラス（{len(classes)} 件）</p>
<table class="sform"><thead><tr>
<th style="width:30%">クラス URI</th><th style="width:38%">ラベル</th><th>上位クラス</th>
</tr></thead><tbody>
{chr(10).join(crows)}
</tbody></table>

<p class="caption">表　epig オントロジー のプロパティ（{len(props)} 件）</p>
<table class="sform"><thead><tr>
<th style="width:22%">プロパティ URI</th><th style="width:34%">ラベル</th>
<th style="width:22%">定義域</th><th style="width:22%">値域</th>
</tr></thead><tbody>
{chr(10).join(prows)}
</tbody></table>

<footer>自動生成元: <code>ontology/epig_ontology.ttl</code> ·
ビルダー: <code>ontology/build_epig_schema_style.py</code></footer>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tex-only", action="store_true")
    ap.add_argument("--html-only", action="store_true")
    ap.add_argument("--start-no", default=None,
                    help="LaTeX caption の先頭表番号 (例: '7-1')。省略時は番号なし。")
    ap.add_argument("--tex-out", default=str(SCRIPT_DIR / "figs" / "epig_schema_style_tables.tex"))
    ap.add_argument("--html-out", default=str(SCRIPT_DIR / "figs" / "epig_schema_style_tables.html"))
    args = ap.parse_args()

    g = load_graph()
    classes, props = collect(g)
    print(f"Loaded {len(g)} triples · {len(classes)} classes, {len(props)} properties "
          f"(deprecated 除外済み)")

    do_tex = not args.html_only
    do_html = not args.tex_only

    if do_tex:
        p = Path(args.tex_out); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(build_tex(g, classes, props, args.start_no), encoding="utf-8")
        print(f"→ Wrote {p} ({p.stat().st_size:,} bytes)")
    if do_html:
        p = Path(args.html_out); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(build_html(g, classes, props), encoding="utf-8")
        print(f"→ Wrote {p} ({p.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
