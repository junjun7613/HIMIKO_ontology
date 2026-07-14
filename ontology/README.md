# HIMIKO / epig オントロジー ドキュメント

TTL からHTMLドキュメント・論文用テーブル・WebVOWL 可視化データを生成し、
ローカルサーバーで閲覧するための手順。

生成済み HTML は GitHub Pages で公開される。
リポジトリ設定 **Settings → Pages → Deploy from a branch → `main` / `(root)`** を選択。
リポジトリルートの `index.html` が `ontology/index.html` へリダイレクトする。
公開URL: `https://junjun7613.github.io/HIMIKO_ontology/`（→ `.../ontology/himiko.html` 等）。

## セットアップ（クローン後）

`venv/` と `tools/owl2vowl.jar` はリポジトリに含めない（`.gitignore`）。
再生成する場合のみ以下が必要:

```bash
# Python 依存（HTML/テーブル生成に必要）
python3 -m venv venv
venv/bin/pip install -r requirements.txt   # rdflib

# WebVOWL JSON を再生成する場合のみ（java 必須）
#   OWL2VOWL 0.2.0 を取得して ontology/tools/owl2vowl.jar に配置
#   https://github.com/VisualDataWeb/OWL2VOWL/releases/download/0.2.0/owl2vowl.zip
```

閲覧するだけなら再生成もツールも不要（生成済み HTML/JSON がコミット済み）。

## 生成物

| ファイル | 内容 | ビルダー |
|---|---|---|
| `himiko.html` | HIMIKO 4層オントロジー・ドキュメント（日英切替） | `build_docs.py` |
| `epig.html` | epig オントロジー・ドキュメント | `build_epig_docs.py` |
| `figs/himiko_tables.html` | HIMIKO 論文添付用テーブル | `build_tables.py` |
| `figs/epig_tables.html` | epig 論文添付用テーブル | `build_epig_tables.py` |
| `webvowl/data/template.json` | HIMIKO WebVOWL 可視化データ | `build_webvowl.py --target himiko` |
| `webvowl/data/epig.json` | epig WebVOWL 可視化データ | `build_webvowl.py --target epig` |

入力 TTL: `hmk_owl/*.ttl`（HIMIKO 4層 + 英語オーバーレイ）、`epig_ontology.ttl`（epig）。

## 再生成

```bash
# ontology/ ディレクトリで実行。PY は rdflib を含む Python。
cd ontology
PY=../venv/bin/python

# HTML ドキュメント + テーブル
"$PY" build_docs.py            # → himiko.html
"$PY" build_tables.py          # → figs/himiko_tables.html
"$PY" build_epig_docs.py       # → epig.html
"$PY" build_epig_tables.py     # → figs/epig_tables.html

# WebVOWL 可視化データ（要 java + tools/owl2vowl.jar）
"$PY" build_webvowl.py --target himiko   # → webvowl/data/template.json
"$PY" build_webvowl.py --target epig     # → webvowl/data/epig.json
```

## ローカルサーバーで閲覧

`himiko.html` は `diagrams/` 画像と `webvowl/index.html#template` を、
`epig.html` は `webvowl/index.html#epig` を相対パスで参照する。
WebVOWL は JSON を `fetch()` で読み込むため `file://` では動作しない。
**`ontology/` をドキュメントルートにした HTTP サーバーが必要。**

```bash
# ontology/ ディレクトリで実行
cd ontology
python3 -m http.server 8000
```

サーバー起動後、ブラウザで以下を開く:

| URL | 表示内容 |
|---|---|
| http://localhost:8000/himiko.html | HIMIKO ドキュメント |
| http://localhost:8000/epig.html | epig ドキュメント |
| http://localhost:8000/figs/himiko_tables.html | HIMIKO テーブル |
| http://localhost:8000/figs/epig_tables.html | epig テーブル |
| http://localhost:8000/webvowl/index.html#template | HIMIKO WebVOWL（単体） |
| http://localhost:8000/webvowl/index.html#epig | epig WebVOWL（単体） |

停止は `Ctrl+C`。ポートが使用中なら `8000` を別の番号に変更する。
