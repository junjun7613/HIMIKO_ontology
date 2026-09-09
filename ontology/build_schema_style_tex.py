#!/usr/bin/env python3
"""
論文・書籍掲載用の schema.org 風リファレンス表を LaTeX (booktabs + longtable) で
生成するビルダー。

build_schema_style_tables.py の LaTeX 版。HIMIKO オントロジー 4 レイヤー
(hmkp, hmktei, hmki, hmke, hmkia) のクラス・プロパティを、レイヤーごとに 3 列の
longtable として出力する:
  クラス表     : クラス URI | 日本語ラベルなど | 上位クラス
  プロパティ表  : プロパティ URI | 日本語ラベルなど (逆向き・上位・属性を併記) | 値域

出力は本文に \\input{} で取り込むことを想定した表フラグメント (.tex)。
プリアンブルに以下が必要:
    \\usepackage{booktabs}
    \\usepackage{longtable}
    \\usepackage{array}
    \\usepackage{amssymb}   % \\cup 用 (∪ を数式に置換)
  日本語は LuaLaTeX/XeLaTeX + luatexja/zxjatype、あるいは (u)pLaTeX を想定。

使用方法:
    python build_schema_style_tex.py
    python build_schema_style_tex.py -o /tmp/tables.tex
    python build_schema_style_tex.py --start-no 6-4   # 表番号を付ける (caption に併記)
"""

import argparse
from pathlib import Path
from collections import defaultdict

from rdflib import Graph, Literal, BNode
from rdflib.namespace import RDF, RDFS, OWL

SCRIPT_DIR = Path(__file__).parent
TTL_DIR = SCRIPT_DIR / "hmk_owl"

LAYERS = [
    {"prefix": "hmkp",   "uri": "urn:himiko:ontology:physical:",     "file": "himiko_physical.ttl",       "title_ja": "史料物理層"},
    {"prefix": "hmki",   "uri": "urn:himiko:ontology:intrinsic:",    "file": "himiko_intrinsic.ttl",      "title_ja": "史料内在知識層"},
    {"prefix": "hmke",   "uri": "urn:himiko:ontology:extrinsic:",    "file": "himiko_extrinsic.ttl",      "title_ja": "外在知識層"},
    {"prefix": "hmkia",  "uri": "urn:himiko:ontology:interpretation:","file": "himiko_interpretation.ttl", "title_ja": "解釈行為層"},
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


# ---------------- graph helpers (build_schema_style_tables.py と共通) ----------------

def load_all_layers():
    g = Graph()
    for layer in LAYERS:
        g.parse(TTL_DIR / layer["file"], format="turtle")
    return g


def qname(g: Graph, uri) -> str:
    if isinstance(uri, BNode):
        return f"_:{uri}"
    s = str(uri)
    for layer in sorted(LAYERS, key=lambda l: len(l["uri"]), reverse=True):
        if s.startswith(layer["uri"]):
            return f"{layer['prefix']}:{s[len(layer['uri']):]}"
    for pref, ns in sorted(COMMON_PREFIXES.items(), key=lambda kv: len(kv[1]), reverse=True):
        if s.startswith(ns):
            return f"{pref}:{s[len(ns):]}"
    return s


def local_layer(uri):
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


def range_parts(g: Graph, s, predicate):
    """domain / range / subClassOf 等の値を (text, is_union) タプルのリストで返す。

    union の場合、要素 QName のリストを返し LaTeX 側で \\cup 連結する。
    """
    parts = []
    for _, _, o in g.triples((s, predicate, None)):
        if isinstance(o, BNode):
            union = list(g.objects(o, OWL.unionOf))
            if union:
                items = [qname(g, item) for item in rdf_list(g, union[0])]
                parts.append(("union", items))
            else:
                parts.append(("plain", ["匿名クラス"]))
        else:
            parts.append(("plain", [qname(g, o)]))
    return parts


def collect_entities(g: Graph):
    by_layer_class = defaultdict(list)
    by_layer_prop = defaultdict(list)
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


# ---------------- LaTeX escaping ----------------

# LaTeX 特殊文字。本文テキスト (ラベル・caption) 用。
_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def tex_escape(s: str) -> str:
    """本文テキスト用の LaTeX エスケープ。∪ は数式の \\cup に置換。"""
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


def _breakable_qname(qn: str) -> str:
    r"""QName の \allowbreak 挿入点を持つエスケープ済み文字列を返す。

    長い URI が p{} 列内で折り返されず隣列に食い込むのを防ぐため、
    : の直後・アンダースコアの後・camelCase (小文字→大文字) の境界に
    標準の \allowbreak を挿入する。追加パッケージは不要。
    """
    out = []
    for i, ch in enumerate(qn):
        esc_ch = _LATEX_SPECIALS.get(ch, ch)
        out.append(esc_ch)
        nxt = qn[i + 1] if i + 1 < len(qn) else ""
        # : または _ の直後で改行を許可 (区切り文字の後)
        if ch in (":", "_"):
            out.append(r"\allowbreak{}")
        # camelCase の切れ目 (小文字/数字 → 大文字) で改行を許可
        elif ch.islower() or ch.isdigit():
            if nxt.isupper():
                out.append(r"\allowbreak{}")
    return "".join(out)


def tex_texttt(qn: str) -> str:
    r"""QName を \texttt{...} で組む。中の特殊文字 (_, # 等) はエスケープし、
    長い URI が折り返せるよう \allowbreak を挿入する。"""
    return r"\texttt{" + _breakable_qname(qn) + "}"


def texttt_join(qnames):
    r"""QName のリストを \texttt でラップしカンマ区切りで返す。空なら —。"""
    if not qnames:
        return "---"
    return ", ".join(tex_texttt(q) for q in qnames)


def range_cell(parts):
    r"""range_parts() の結果を LaTeX セル文字列に。union は \texttt{A} $\cup$ \texttt{B}。"""
    if not parts:
        return "---"
    rendered = []
    for kind, items in parts:
        if kind == "union":
            joined = r" $\cup$ ".join(tex_texttt(x) for x in items)
            rendered.append("(" + joined + ")")
        else:
            rendered.append(tex_texttt(items[0]))
    return ", ".join(rendered)


# ---------------- label + notes cell ----------------

def label_notes_cell(g: Graph, s, label: str) -> str:
    """schema.org 風「日本語ラベルなど」セル (LaTeX)。

    日本語ラベル + (逆向き: … / 上位: … / 関数的プロパティ) を注記する。
    """
    main = tex_escape(label) if label else ""
    notes = []

    inv = [qname(g, o) for o in g.objects(s, OWL.inverseOf)]
    inv += [qname(g, subj) for subj in g.subjects(OWL.inverseOf, s)]
    inv = sorted(set(inv))
    if inv:
        notes.append("逆向き: " + ", ".join(tex_texttt(q) for q in inv))

    sup = [qname(g, o) for o in g.objects(s, RDFS.subPropertyOf)]
    sup = sorted(set(sup))
    if sup:
        notes.append("上位: " + ", ".join(tex_texttt(q) for q in sup))

    if (s, RDF.type, OWL.FunctionalProperty) in g:
        notes.append("関数的プロパティ")

    note = ""
    if notes:
        # 注記は小さめのフォントで
        note = r" {\small (" + " / ".join(notes) + ")}"

    if not main and not notes:
        return "---"
    return (main if main else "---") + note


# ---------------- LaTeX table rendering ----------------

def _next_table_no(no):
    if no is None:
        return None
    if "-" in no:
        head, _, tail = no.rpartition("-")
        if tail.isdigit():
            return f"{head}-{int(tail) + 1}"
    if no.isdigit():
        return str(int(no) + 1)
    return no


def _caption(title, count, kind, table_no):
    label = f"{title} の{kind}（{count} 件）"
    if table_no is not None:
        return f"表 {table_no}\\quad {tex_escape(label)}"
    return tex_escape(label)


def _longtable(colspec, header_cells, body_rows, caption):
    r"""booktabs + longtable の一つの表を組む。header はページ跨ぎで繰り返す。"""
    header = " & ".join(header_cells) + r" \\"
    lines = []
    lines.append(r"\begin{longtable}{" + colspec + "}")
    lines.append(r"\caption{" + caption + r"}\\")
    lines.append(r"\toprule")
    lines.append(header)
    lines.append(r"\midrule")
    lines.append(r"\endfirsthead")
    # 2 ページ目以降のヘッダ
    lines.append(r"\multicolumn{" + str(len(header_cells)) +
                 r"}{l}{\small （前ページからの続き）}\\")
    lines.append(r"\toprule")
    lines.append(header)
    lines.append(r"\midrule")
    lines.append(r"\endhead")
    lines.append(r"\midrule")
    lines.append(r"\multicolumn{" + str(len(header_cells)) +
                 r"}{r}{\small （次ページへ続く）}\\")
    lines.append(r"\endfoot")
    lines.append(r"\bottomrule")
    lines.append(r"\endlastfoot")
    lines.extend(body_rows)
    lines.append(r"\end{longtable}")
    return "\n".join(lines)


def render_class_table(g: Graph, items, title, table_no):
    if not items:
        return ""
    rows = []
    for s in items:
        qn = tex_texttt(qname(g, s))
        label = tex_escape(get_label_ja(g, s)) or "---"
        sup = range_cell(range_parts(g, s, RDFS.subClassOf))
        rows.append(f"{qn} & {label} & {sup} \\\\")
    caption = _caption(title, len(items), "クラス", table_no)
    header = [r"\textbf{クラス URI}", r"\textbf{ラベル}", r"\textbf{上位クラス}"]
    # p{} で折り返しを許可 (URI は左寄せ固定幅、ラベルと値域は可変)
    colspec = r"@{}>{\raggedright\arraybackslash}p{0.26\linewidth} >{\raggedright\arraybackslash}p{0.40\linewidth} >{\raggedright\arraybackslash}p{0.28\linewidth}@{}"
    return _longtable(colspec, header, rows, caption)


def render_property_table(g: Graph, items, title, table_no):
    if not items:
        return ""
    rows = []
    for s in items:
        qn = tex_texttt(qname(g, s))
        label = label_notes_cell(g, s, get_label_ja(g, s))
        dom = range_cell(range_parts(g, s, RDFS.domain))
        rng = range_cell(range_parts(g, s, RDFS.range))
        rows.append(f"{qn} & {label} & {dom} & {rng} \\\\")
    caption = _caption(title, len(items), "プロパティ", table_no)
    header = [r"\textbf{プロパティ URI}", r"\textbf{ラベル}",
              r"\textbf{定義域}", r"\textbf{値域}"]
    colspec = (r"@{}>{\raggedright\arraybackslash}p{0.22\linewidth} "
               r">{\raggedright\arraybackslash}p{0.34\linewidth} "
               r">{\raggedright\arraybackslash}p{0.20\linewidth} "
               r">{\raggedright\arraybackslash}p{0.20\linewidth}@{}")
    return _longtable(colspec, header, rows, caption)


PREAMBLE_NOTE = r"""% ============================================================
%  HIMIKO オントロジー リファレンス表 (schema.org 風 / booktabs+longtable)
%  自動生成元: ontology/hmk_owl/*.ttl
%  ビルダー:   ontology/build_schema_style_tex.py
%
%  本文に \input{himiko_schema_style_tables.tex} で取り込む。
%  プリアンブルに以下が必要:
%      \usepackage{booktabs}
%      \usepackage{longtable}
%      \usepackage{array}
%      \usepackage{amssymb}   % \cup (∪) 用
%  日本語組版は LuaLaTeX/XeLaTeX(+luatexja 等) または (u)pLaTeX を想定。
% ============================================================
"""


def build_tex(g: Graph, start_no) -> str:
    cls_by, prop_by = collect_entities(g)
    blocks = [PREAMBLE_NOTE]
    table_no = start_no
    for layer in LAYERS:
        p = layer["prefix"]
        cls_list = cls_by.get(p, [])
        prop_list = prop_by.get(p, [])
        blocks.append("% ----- " + layer["title_ja"] + f" ({p}:) -----")
        c_html = render_class_table(g, cls_list, layer["title_ja"], table_no)
        if c_html:
            blocks.append(c_html)
            table_no = _next_table_no(table_no)
        p_html = render_property_table(g, prop_list, layer["title_ja"], table_no)
        if p_html:
            blocks.append(p_html)
            table_no = _next_table_no(table_no)
    return "\n\n".join(blocks) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "-o", "--output",
        default=str(SCRIPT_DIR / "figs" / "himiko_schema_style_tables.tex"),
        help="出力 TeX パス (デフォルト: ontology/figs/himiko_schema_style_tables.tex)",
    )
    ap.add_argument(
        "--start-no",
        default=None,
        help="最初の表番号 (例: '6-4')。指定すると caption に『表 6-4』等を併記し連番を振る。省略時は番号なし。",
    )
    args = ap.parse_args()

    g = load_all_layers()
    print(f"Loaded {len(g)} triples from {len(LAYERS)} ontology files")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_tex(g, args.start_no), encoding="utf-8")
    print(f"→ Wrote {out_path} ({out_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
