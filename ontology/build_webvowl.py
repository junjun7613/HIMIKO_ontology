#!/usr/bin/env python3
"""HIMIKO / epig オントロジーの WebVOWL 可視化データビルダー。

--target himiko (デフォルト):
    hmk_owl/ 配下の 4 TTL (hmkp, hmki, hmke, hmkia) と英語オーバーレイをマージし、
    urn: の名前空間を http: にフラット化して OWL2VOWL に渡す。
    webvowl/data/template.json を出力する。

--target epig:
    ontology/epig_ontology.ttl 単体を対象とする。owl:imports を剥がして
    OWL2VOWL に渡し、webvowl/data/epig.json を出力する。

前提:
    - java (OWL2VOWL 0.2.0 の実行に必要)
    - owl2vowl.jar (ontology/tools/owl2vowl.jar が既定パス)
      入手: https://github.com/VisualDataWeb/OWL2VOWL/releases/download/0.2.0/owl2vowl.zip

使用方法:
    python build_webvowl.py                              # himiko
    python build_webvowl.py --target epig                # epig
    python build_webvowl.py --owl2vowl /path/to/owl2vowl.jar
"""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from rdflib import Graph, URIRef, Literal, OWL, RDF, RDFS
from rdflib.namespace import DCTERMS

HIMIKO_ONTO_IRI = "http://purl.org/atag/himiko/ontology"
EPIG_ONTO_IRI = "http://epigraphic-careers.org/ontology"

LAYER_TAG = {
    "urn:himiko:ontology:physical:":       "hmkp_",
    "urn:himiko:ontology:intrinsic:":      "hmki_",
    "urn:himiko:ontology:extrinsic:":      "hmke_",
    "urn:himiko:ontology:interpretation:": "hmkia_",
}
OLD_ONTO_IRIS = {
    "urn:himiko:ontology:physical",
    "urn:himiko:ontology:intrinsic",
    "urn:himiko:ontology:extrinsic",
    "urn:himiko:ontology:interpretation",
}
HIMIKO_SOURCES = [
    "himiko_physical.ttl",       # hmkp:
    "himiko_intrinsic.ttl",      # hmki:
    "himiko_extrinsic.ttl",      # hmke:
    "himiko_interpretation.ttl", # hmkia:
    "himiko_i18n_en.ttl",        # English rdfs:comment overlay
]
EPIG_SOURCE = "epig_ontology.ttl"
HMKI_SOURCE = "hmk_owl/himiko_intrinsic.ttl"


def rewrite(term):
    if isinstance(term, URIRef):
        s = str(term)
        for prefix, tag in LAYER_TAG.items():
            if s.startswith(prefix):
                return URIRef(f"{HIMIKO_ONTO_IRI}#{tag}{s[len(prefix):]}")
    return term


def merge_and_flatten_himiko(ontology_dir: Path, out_rdf: Path) -> int:
    g_in = Graph()
    for name in HIMIKO_SOURCES:
        g_in.parse(ontology_dir / name, format="turtle")

    g = Graph()
    for s, p, o in g_in:
        g.add((rewrite(s), rewrite(p), rewrite(o)))

    for s in list(g.subjects(RDF.type, OWL.Ontology)):
        g.remove((s, None, None))
    for old in OLD_ONTO_IRIS:
        for triple in list(g.triples((URIRef(old), None, None))):
            g.remove(triple)

    onto = URIRef(HIMIKO_ONTO_IRI)
    g.add((onto, RDF.type, OWL.Ontology))
    g.add((onto, DCTERMS.title, Literal("HIMIKO — Historical Micro Knowledge and Ontology (merged)", lang="en")))
    g.add((onto, DCTERMS.title, Literal("HIMIKO 歴史マイクロ知識オントロジー (統合)", lang="ja")))
    g.add((onto, RDFS.label, Literal("HIMIKO", lang="en")))
    g.add((onto, OWL.versionInfo, Literal("0.2-merged")))

    g.serialize(destination=str(out_rdf), format="pretty-xml")

    text = out_rdf.read_text()
    text = text.replace(
        '<rdf:RDF\n  xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"',
        f'<rdf:RDF\n  xml:base="{HIMIKO_ONTO_IRI}"\n  xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"',
    )
    out_rdf.write_text(text)
    return len(g)


HMKI_NS = "urn:himiko:ontology:intrinsic:"


def _referenced_hmki_uris(g: Graph):
    """epig グラフの中で参照される hmki: 名前空間の URI を集める。"""
    referenced = set()
    for s, p, o in g:
        for term in (s, o):
            if isinstance(term, URIRef) and str(term).startswith(HMKI_NS):
                referenced.add(term)
    return referenced


def _drop_deprecated(g: Graph) -> int:
    """owl:deprecated true のリソースと、それを含む全 triple を削除する。"""
    depr = set(g.subjects(OWL.deprecated, Literal(True)))
    removed = 0
    for term in depr:
        for triple in list(g.triples((term, None, None))):
            g.remove(triple)
            removed += 1
        for triple in list(g.triples((None, None, term))):
            g.remove(triple)
            removed += 1
    return removed


def prepare_epig(source_ttl: Path, hmki_ttl: Path, out_rdf: Path) -> int:
    """epig_ontology.ttl + himiko_intrinsic.ttl (参照分のみ) を単一 RDF/XML に変換。

    処理:
      1. epig_ontology.ttl をロード
      2. epig グラフから参照されている hmki: URI を抽出し、himiko_intrinsic.ttl から
         該当リソースを (1 段の subClassOf / subPropertyOf を含めて) 移植
      3. owl:deprecated true のリソースと関連 triple を全削除
      4. owl:imports を除去
      5. xml:base 付き RDF/XML に直列化
    """
    g = Graph()
    g.parse(source_ttl, format="turtle")

    # hmki: の参照分を移植
    g_hmki = Graph()
    g_hmki.parse(hmki_ttl, format="turtle")

    referenced = _referenced_hmki_uris(g)
    # 1 段の subClassOf / subPropertyOf を追加
    additional = set()
    for term in list(referenced):
        for _, _, o in g_hmki.triples((term, RDFS.subClassOf, None)):
            if isinstance(o, URIRef) and str(o).startswith(HMKI_NS):
                additional.add(o)
        for _, _, o in g_hmki.triples((term, RDFS.subPropertyOf, None)):
            if isinstance(o, URIRef) and str(o).startswith(HMKI_NS):
                additional.add(o)
    referenced |= additional

    added = 0
    for term in referenced:
        for triple in g_hmki.triples((term, None, None)):
            g.add(triple)
            added += 1
    print(f"  merged {added} hmki: triples ({len(referenced)} resources)")

    # deprecated 除去
    removed = _drop_deprecated(g)
    if removed:
        print(f"  dropped {removed} triples marked owl:deprecated true")

    # owl:imports 除去
    for s, p, o in list(g.triples((None, OWL.imports, None))):
        g.remove((s, p, o))

    g.serialize(destination=str(out_rdf), format="pretty-xml")

    text = out_rdf.read_text()
    text = text.replace(
        '<rdf:RDF\n  xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"',
        f'<rdf:RDF\n  xml:base="{EPIG_ONTO_IRI}"\n  xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"',
    )
    out_rdf.write_text(text)
    return len(g)


def run_owl2vowl(jar: Path, rdf: Path, work_dir: Path) -> Path:
    result = subprocess.run(
        ["java", "-jar", str(jar), "-file", str(rdf)],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"OWL2VOWL failed: {result.stderr}")
    json_path = work_dir / (rdf.stem + ".json")
    if not json_path.exists():
        raise RuntimeError(f"OWL2VOWL did not produce {json_path}")
    return json_path


def patch_header(vowl_json_path: Path, onto_iri: str) -> None:
    d = json.loads(vowl_json_path.read_text())
    d.setdefault("header", {})
    d["header"]["iri"] = onto_iri
    d["header"].setdefault("baseIri", onto_iri)
    vowl_json_path.write_text(json.dumps(d, ensure_ascii=False, indent=2))


TARGETS = {
    "himiko": {
        "iri": HIMIKO_ONTO_IRI,
        "default_out": "webvowl/data/template.json",
        "rdf_name": "himiko_merged.rdf",
    },
    "epig": {
        "iri": EPIG_ONTO_IRI,
        "default_out": "webvowl/data/epig.json",
        "rdf_name": "epig_flat.rdf",
    },
}


def main() -> None:
    script_dir = Path(__file__).resolve().parent

    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=list(TARGETS.keys()), default="himiko",
                    help="Which ontology to build (default: himiko)")
    ap.add_argument("--owl2vowl", type=Path,
                    default=script_dir / "tools" / "owl2vowl.jar",
                    help="Path to owl2vowl.jar (default: ontology/tools/owl2vowl.jar)")
    ap.add_argument("--ontology-dir", type=Path,
                    default=script_dir / "hmk_owl",
                    help="Directory containing HIMIKO source TTL files (only used for --target himiko)")
    ap.add_argument("--epig-ttl", type=Path,
                    default=script_dir / EPIG_SOURCE,
                    help=f"Path to epig ontology TTL (only used for --target epig)")
    ap.add_argument("--hmki-ttl", type=Path,
                    default=script_dir / HMKI_SOURCE,
                    help=f"Path to himiko_intrinsic TTL used to merge referenced hmki: entities (only for --target epig)")
    ap.add_argument("--out", type=Path,
                    default=None,
                    help="Destination path for the VOWL JSON (default depends on --target)")
    args = ap.parse_args()

    target_cfg = TARGETS[args.target]
    out_path = args.out or (script_dir / target_cfg["default_out"])

    if not args.owl2vowl.exists():
        raise SystemExit(
            f"owl2vowl.jar not found at {args.owl2vowl}. "
            f"Download from https://github.com/VisualDataWeb/OWL2VOWL/releases/download/0.2.0/owl2vowl.zip"
        )

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        rdf = work / target_cfg["rdf_name"]

        if args.target == "himiko":
            triples = merge_and_flatten_himiko(args.ontology_dir, rdf)
            print(f"merged {triples} triples → {rdf}")
        else:
            triples = prepare_epig(args.epig_ttl, args.hmki_ttl, rdf)
            print(f"prepared {triples} triples → {rdf}")

        vowl_json = run_owl2vowl(args.owl2vowl.resolve(), rdf, work)
        patch_header(vowl_json, target_cfg["iri"])

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(vowl_json.read_bytes())
        print(f"wrote VOWL JSON → {out_path}")


if __name__ == "__main__":
    main()
