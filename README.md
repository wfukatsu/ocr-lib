# dococr

日本語の業務文書 (仕様書、帳票、記録、図面) を読み取り、Markdown と JSON にする Python ライブラリ。

[docling](https://github.com/docling-project/docling) でページの構造を分解し、
[NDLOCR-Lite](https://github.com/ndl-lab/ndlocr-lite) で文字を読む。そのうえで、通常の OCR では落ちる情報
(取り消し線、チェック欄、罫線の帳票の項目と値の対応) を取り出す。読み取りを確定できなかった箇所は、
黙って出力せず「要確認」として残し、人が確認する一覧にまとめる。

特定の組織の帳票や用語は持たない。帳票の定義と用語集は、利用する側がファイルで渡す。

## できること

| 機能 | 内容 | コマンド |
| --- | --- | --- |
| 構造化 OCR | PDF・画像を、見出し・段落・表・図の構造を保った Markdown にする。テキスト層が信用できる PDF は OCR しない | `dococr-ocr` |
| 取り消し線 | Word / Excel / PDF / スキャンから、取り消し線のある文字列を `~~…~~` で出す | `dococr-strike` |
| チェック欄 | □ / ■ をページ画像から判定し、タスクリスト (`- [ ]` / `- [x]`) にする | `dococr-ocr` に含む |
| 帳票の欄抽出 | 罫線からセルを切り出し、項目と値の対応を保って読む。見出しの語や値の型を定義して渡せる | `dococr-form` |
| 図・写真 | 画像ファイルに切り出して Markdown から参照する。図面のページは macOS の Vision でも読む | `dococr-ocr` に含む |
| 用語集 | OCR が要らないファイルから型番や用語を集め、読み取りの誤りを補正する | `dococr-glossary` |
| 確認の一覧 | 出力フォルダから、人が確認すべき箇所を 1 つの一覧にまとめる | `dococr-review` |
| 採点 | 出力を正解データと照らして採点し、前回より下がった指標を知らせる | `dococr-eval` |
| 旧形式の変換 | `.doc` / `.xls` / `.ppt` を新形式に変換する | `dococr-convert` |
| ファイルの対応表 | 2 つのフォルダのファイルを、ファイル名の番号で突き合わせる | `dococr-map` |
| 視覚モデルの試行 | 手書きの数値や図面の表題欄を、視覚モデルに構造化させる (社外に送信する) | `dococr-vlm` |

## インストール

Python 3.10 以上。

```bash
pip install -e .            # 取り消し線 (Word / Excel / テキスト層のある PDF)、対応表、採点
pip install -e ".[ocr]"     # 構造化 OCR、帳票、スキャン PDF (docling を使う)
```

OCR を使う機能は、NDLOCR-Lite を別に取得し、その `src` のパスを `--ndlocr-src` (Python からは `ndlocr_src`) で渡す。

```bash
git clone https://github.com/ndl-lab/ndlocr-lite
pip install -r ndlocr-lite/requirements.txt
```

次のものは、あれば使う。なくても動く。

| もの | 使いみち | 入れ方 |
| --- | --- | --- |
| Tesseract と日本語データ | 帳票の短い値を、別のエンジンと照合する | `brew install tesseract tesseract-lang` など |
| macOS の Vision | 食い違った値の多数決、図面のページの読み取り | `pip install -e ".[vision]"` (macOS のみ) |
| LibreOffice | 旧形式 (`.doc` / `.xls` / `.ppt`) の変換 | `brew install --cask libreoffice` など |
| Anthropic の SDK | `dococr-vlm` の `anthropic` / `bedrock` / `vertex` | `pip install -e ".[vlm]"` |

動作を確認した版は `constraints.txt` にある。docling は内部構造に依存しているので、版をそろえるには
`pip install -c constraints.txt -e ".[ocr]"` とする。

## 使い方

### コマンドから

```bash
# 取り消し線 (OCR なし)
dococr-strike 文書.docx -o out.md --report strike.json

# 構造化 OCR。out/ に Markdown と JSON が出る
dococr-ocr --ndlocr-src ndlocr-lite/src --out out スキャン.pdf

# フォルダごと読む。用語集を先に作り、フォルダ構成を out/ に再現する
dococr-ocr --ndlocr-src ndlocr-lite/src --out out --root 入力フォルダ --list files.txt --forms forms.json

# 人が確認すべき箇所の一覧
dococr-review out -o review.md --csv review.csv
```

### Python から

```python
from dococr import extract_strikes, ocr_files

# Word / Excel / テキスト層のある PDF の取り消し線 (OCR なし)
markdown, found = extract_strikes("文書.docx")

# スキャン PDF や画像の構造化 OCR。out/ に Markdown と JSON が出る
failed = ocr_files(["スキャン.pdf"], "out", ndlocr_src="ndlocr-lite/src", forms="forms.json")
```

| 名前 | 内容 |
| --- | --- |
| `extract_strikes(path, tracked="mark", figures=None)` | (Markdown, 取り消し線と要確認箇所の一覧) を返す。テキスト層を使えない PDF には `NeedsOcr` を送出するので、その場合は `ocr_files` で読む |
| `ocr_files(inputs, out_dir, ndlocr_src, *, forms, glossary, root, pages, …)` | 構造化 OCR の結果を `out_dir` に書き出し、読めなかった入力の一覧を返す。`forms` は帳票の定義、`glossary` は用語集 (TSV)。どちらも省略できる |
| `load_forms(path)` / `define_form(name, labels, …)` | 帳票の定義を JSON から読む / コードで作る (「帳票の定義」) |

個々の処理 (経路判定、セルの切り出し、チェック欄の判定など) は、役割ごとのモジュールを直接呼べる (「モジュールの構成」)。

### 出力

`dococr-ocr` は、入力 1 ファイルにつき次のファイルを出力先に書き出す。該当するものがなければ出ない。

| ファイル | 内容 |
| --- | --- |
| `<名前>.md` | 本文。先頭に経路、各ページの先頭に注意が必要なページの注記が入る |
| `<名前>.meta.json` | 経路、ページごとの統計 (読めた割合、チェック欄や取り消し線の数)、切り出した図の一覧 |
| `<名前>.strike.json` | 取り消し線の一覧 (確定したものと、要確認のもの) |
| `<名前>.checkbox.json` | チェック欄の一覧 |
| `<名前>.form_review.json` | 帳票で確定できなかった値 |
| `<名前>.glossary.json` | 用語集による補正と候補 |
| `json/<名前>.pNNNN.json` | ページごとの docling の出力 (帳票のページは `.form.json`) |
| `figures/<名前>/` | 切り出した図・写真 |
| `glossary.tsv` | 入力から作った用語集 (`--root` を指定した場合) |

Markdown の中の要確認は、HTML コメント (`<!-- 要確認 p.N: … -->`) と、値の後ろの ` (?)` で示す。

### サンプル

公開されている文書を実際に読んだ結果を [`samples/`](samples/README.md) に置いている。

| | 場所 |
| --- | --- |
| 元文書 | 公共建築工事標準仕様書（機械設備工事編）令和４年版 (国土交通省): <https://www.mlit.go.jp/gobuild/content/001879206.pdf> |
| 変換後の Markdown (テキスト層の経路、p.1〜12) | [`samples/mlit-kikai-r4/text-layer/kikai_r4_p001-012.md`](samples/mlit-kikai-r4/text-layer/kikai_r4_p001-012.md) |
| 変換後の Markdown (OCR の経路、用語集つき、p.9〜11) | [`samples/mlit-kikai-r4/ocr/kikai_r4_p009-011_ocr.md`](samples/mlit-kikai-r4/ocr/kikai_r4_p009-011_ocr.md) |

この元文書の PDF はリポジトリに置いていない。
出典：国土交通省ウェブサイト (<https://www.mlit.go.jp/gobuild/gobuild_tk6_000021.html>)。変換後のファイルは、元文書を加工して作成したもの。

取り消し線のサンプルは、架空の作業要領書を 4 つの形式で作ったもの (`samples/strike/make_sample.py`)。

| 元文書 | 変換後の Markdown |
| --- | --- |
| [`samples/strike/source/youryou.docx`](samples/strike/source/youryou.docx) (Word) | [`samples/strike/output/youryou.docx.md`](samples/strike/output/youryou.docx.md) |
| [`samples/strike/source/youryou.xlsx`](samples/strike/source/youryou.xlsx) (Excel) | [`samples/strike/output/youryou.xlsx.md`](samples/strike/output/youryou.xlsx.md) |
| [`samples/strike/source/youryou_text.pdf`](samples/strike/source/youryou_text.pdf) (テキスト層のある PDF) | [`samples/strike/output/youryou_text.pdf.md`](samples/strike/output/youryou_text.pdf.md) |
| [`samples/strike/source/youryou_scan.pdf`](samples/strike/source/youryou_scan.pdf) (スキャン PDF) | [`samples/strike/output/scan/youryou_scan.md`](samples/strike/output/scan/youryou_scan.md) |

手書きのサンプルは、架空の点検記録と連絡メモを手書き風のフォントで作ったもの (`samples/handwriting/make_sample.py`)。

| 元文書 | 変換後のファイル |
| --- | --- |
| [`samples/handwriting/source/tenken_tegaki.pdf`](samples/handwriting/source/tenken_tegaki.pdf) (画像だけの PDF) | [標準の OCR](samples/handwriting/output/ocr/tenken_tegaki.md) / [macOS の Vision](samples/handwriting/output/vision/tenken_tegaki.vision.txt) / [視覚モデル](samples/handwriting/output/vlm/tenken_tegaki.vlm.md) |

そろった字の手書きの文は標準の OCR でも読めるが、1〜2 文字の値は誤り、手書きのチェックは取れない。崩した字は文も読めない。

実行したコマンド、併せて出る JSON、結果の読み方は [`samples/README.md`](samples/README.md) にある。

### 資料を外部に送らない

`dococr-vlm` を除き、読み取りはすべて手元で行う。`dococr-vlm` は `--allow-external` を付けない限り送信しない。

以下は機能ごとの詳細。

## 取り消し線の抽出 (`dococr-strike`)

取り消し線のある文字列を抽出し、Markdown の `~~文字列~~` で出力する。入力形式ごとに方法が異なる。

| 入力 | 方法 | 確実さ |
| --- | --- | --- |
| Word (.docx / .doc) | run の書式 `w:strike` / `w:dstrike` を読む。変更履歴による削除 `w:del` は区別して出力する | 書式どおり |
| Excel (.xlsx / .xls) | セルの書式と、セル内の一部の文字の書式 (リッチテキスト) を読む。取り消し線を含むセルだけを、シート名とセル番地つきで出力する | 書式どおり |
| テキスト層のある PDF | 水平線・取り消し線注釈の座標と、文字の座標を照合する | 推定。曖昧な箇所は要確認として出力 |
| スキャン PDF | ページ画像から文字を横切る横線を検出して消し、OCR の行と照合する | 推定。行の一部の取り消しは、線の範囲を読み直して確かめる。確かめられなければ要確認 |

```bash
dococr-strike 文書.docx -o out.md --report strike.json
dococr-strike 表.xlsx   -o out.md --report strike.json
dococr-strike 文書.pdf  -o out.md --report strike.json
```

スキャン PDF は docling と NDLOCR-Lite が必要 (「インストール」)。

```bash
dococr-strike スキャン.pdf --out-dir out --ndlocr-src ndlocr-lite/src --pages 19-21
```

`out/` に Markdown、ページ別の統計 (`*.meta.json`)、取り消し線の一覧 (`*.strike.json`) が出る。

### 出力の決まり

- 取り消し線の範囲だけを `~~` で囲む。原文の文字や記号は補正しない。
- 原文の `~~` は `\~\~` にエスケープする。
- Word の変更履歴による削除は `~~文字列~~<!-- 変更履歴による削除 -->` と出力する (`--tracked skip` で出力しない)。
- PDF で線と文字列の対応が曖昧な箇所は `~~` を付けず、`<!-- 要確認 p.N: … -->` としてページ番号付きで示す。

### 既知の制限

- スキャン PDF の取り消し線は約 8mm (2 文字強) 以上の横線だけを対象にする。それより短いものは検出しない。
- スキャン PDF では文字ごとの座標がない。行の一部だけの取り消しは、線の範囲だけを読み直し、その文字列が行の中の 1 か所にそのまま現れれば、その範囲で確定する。一致しなければ、位置から範囲を推定して要確認にする。
- スキャン PDF では、文字より高い縦線につながる横線 (表の罫線) と、周りの文字の高さに比べて短い線 (大きな文字の横画) は取り消し線にしない。
- 図・帳票と判定された領域の中の取り消し線は、確定にせず要確認にする。表の中は、線がセルの文字の幅に収まり、文字の画を横切っているものだけを確定し、それ以外 (罫線かもしれない線) は要確認にする。行に対応しない候補は `*.strike.json` にだけ記録する。
- 縦書きと、回転したページには対応していない。
- Excel は、条件付き書式による取り消し線と、図形・コメントの中の文字は対象外。
- Word の自動番号 (見出しの「(1)」など) は、番号の文字としては出力しない。

## 旧形式の変換 (`dococr-convert`)

旧形式の `.doc` / `.xls` / `.ppt` は、LibreOffice で `.docx` / `.xlsx` / `.pptx` に変換してから処理する。
`dococr-strike` に `.doc` を渡した場合も、内部でこの変換を行う。

```bash
brew install --cask libreoffice   # macOS の場合
dococr-convert 旧形式.doc 旧形式.xls --out-dir converted
```

- 表・自動番号・フィールド・ヘッダー、結合セル・非表示列・取り消し線の書式が保たれる。
- LibreOffice がない場合、`.doc` だけは macOS の textutil で代用する。この場合は表・自動番号・ヘッダーが失われるので警告を出す。`.xls` は LibreOffice が必須。

## 定型帳票の欄抽出 (`dococr-form`)

罫線のある定型帳票 (項目と値が並ぶ台帳など) を、セル単位で読む。表の構造を推定せず、罫線からセルを切り出すので、
項目と値の対応がずれない。

```bash
dococr-form 帳票.pdf --ndlocr-src ndlocr-lite/src --out-dir out --forms forms.json
```

- 出力は、行ごとにセルを ` | ` で並べた Markdown と、セルの座標つきの JSON (`*.form.json`)。
- 文字は行検出を通さず、セル内の文字の行をそのまま文字認識にかける。
- 1〜4 文字の値は Tesseract でも読む (`tesseract` と日本語データが必要)。数字や英数字だけの値は Tesseract の結果を採る。
- 2 つの結果が食い違った値は、次の順に確定させる。確定できなかった値だけに ` (?)` を付けて要確認にする。
  1. 連番: 行の先頭に項目番号 (01, 02, …) が並ぶ列は、位置から番号を決める。どれかのエンジンがその番号を読んでいる行と、読みが確定しておらず前後の行が連番に合っている行だけを直す。どのエンジンも別の番号を読んで確定している行は、欠番かもしれないので書き換えない。
  2. 見出しの辞書: 帳票の定義にある見出しの語に当たれば、その語にする。
  3. 値の型: 帳票の定義で取りうる値が決まっている項目 (例: 区分は A/B/C) は、それに合う読み取りを採る。
  4. 多数決: macOS では Vision でも読み (`pip install -e ".[vision]"`)、3 つのうち 2 つが一致すれば採る。
- どの方法で確定させたかは `*.form.json` の `by` に、元の読み取りは `ndl` と `alt` に残る。
  3 つ目のエンジンだけが違う読みをした場合は `third` に候補として残り、要確認の注記に「別の読み」として出る。
- 罫線のない列の区切りは、文字 4 つ分以上の空白で分ける。

### 欄の中に文章や表が入る帳票

セルごとに値が入る帳票として読めなかった場合は、欄の中に文章や表が入る帳票として読む。

- 罫線から見出しの欄 (題名、概要、理由 など) を探し、その右隣 (次の見出しまで) か真下の範囲に入る行を、見出しの値とする。
- 行はページ全体を行単位で OCR して得る。読めた割合が低いページは分割して読み直す。
- 縦書きの見出しは 1 文字ずつ誤読されやすいので、文字の重なりで照合する。
- 数字・英数字だけの 1〜4 文字の行 (金額や数量) は、セル単位の帳票と同じように別のエンジンと照合する。
- 出力は見出しごとの Markdown。見つからなかった見出しは注記に出す。

### 帳票の定義 (`--forms`)

見出しの語や値の型が分かっている帳票は、JSON で定義して `--forms` (Python からは `forms=`) で渡す。
定義はライブラリの中には置かない。定義がなければ、罫線のあるページは「定義のない罫線の帳票」として読む。
例は `examples/forms.example.json`。

```json
{"forms": [
  {"name": "備品台帳", "layout": "cells",
   "labels": ["資産番号", "品名", "型番", "区分"], "types": {"区分": "[ABC]"}, "min_labels": 3},
  {"name": "計画概要書", "layout": "regions",
   "labels": {"題名": "right", "担当部署": "below", "概要": "right"}, "order": [["題名", "概要"]]}
]}
```

| 項目 | 内容 |
| --- | --- |
| `layout` | `cells` はセルごとに値が入る帳票、`regions` は欄の中に文章や表が入る帳票 |
| `labels` | `cells` では見出しの語の一覧。`regions` では、見出しごとに値の欄が右隣 (`right`) か真下 (`below`) か |
| `types` | 見出しの右隣のセルが取りうる値の正規表現 |
| `order` | (`regions` のみ) 同じ段に左から並ぶ見出しの組。行検出が見落とした見出しの欄を、並び順から推定する |
| `min_labels` | この帳票とみなすのに要る見出しの数。省略すると `cells` は 8、`regions` は 6 (見出しがそれより少なければ、その数) |

書き方の誤り (見出しにない語、読めない正規表現) は、読み取りを始める前にエラーにする。

## 構造化 OCR (`dococr-ocr`)

docling でページ構造を分解し、NDLOCR-Lite で OCR する。入力はファイルごとに経路を決める。

| 判定 | 条件 | 処理 |
| --- | --- | --- |
| テキスト層を使用 | 文字が取り出せ、文字化けしていない | OCR しない。docling でテキスト層から Markdown にする。文字の間隔や行の折り返しに由来する余分な空白 (`1 . 1 . 1`) は、テキスト層の並びにそろえて除く |
| 文字化け | フォントに Unicode 対応表がなく、`(cid:N)` や記号に化ける | 画像にして OCR。1 ページの PDF は macOS の Quick Look で描画する (pdfium や poppler は一部の文字が欠ける) |
| OCR 済みスキャン | ページ全面の画像の上にテキストがある | 既存のテキスト層を使わず、画像にして OCR をやり直す |
| テキスト層なし | 文字がない。または見出しだけがテキストで本文が画像 | 画像にして OCR |

OCR する場合は、1 ページずつ 300dpi の画像にしてから docling に渡す。PDF のまま渡すと、ぼやけたページ画像が
OCR に使われ、文字化けした (または OCR 由来の) テキスト層が表の中身に混ざる。

経路はすべてのページを見て決める。OCR が必要なページが 2 割を超えれば、文書全体を OCR する。2 割以下なら文書はテキスト層を使い、
テキスト層を使えないページ (本文の後ろに綴じたスキャンなど) だけを OCR する。そのページは Markdown の先頭の注記と `*.meta.json` の `ocr_pages` に出る。

```bash
dococr-ocr --ndlocr-src ndlocr-lite/src --out out --root <入力ルート> --list files.txt [--forms forms.json]
```

出力は Markdown、ページごとの docling JSON (`json/`)、統計 (`*.meta.json`)、取り消し線の一覧 (`*.strike.json`)。
Markdown の各ページの先頭に、注意が必要なページの注記が入る。

- `要確認: チェック欄の判定が不確か`: 下の「チェック欄」を参照。
- `未読領域あり`: 文字領域のインクのうち、行として読めた割合 (`ink_covered`) が 6 割未満。図・写真と判定された領域は数えない。
- `行検出が崩壊`: 行検出が意味のない結果を返したため、分割して読み直したページ。

読めた割合が低いページは、帯状と格子状に分割して読み直し、結果を合わせる。

### 帳票のページ

罫線のセルがページの広い範囲を占めるページは、帳票として読めるかを先に試す (`dococr-form` と同じ処理)。
`--forms` で渡した定義のどれかに当たれば、その定義に沿って読んだ結果を出力に使う。`--no-forms` でこの判定を止められる。

定義済みの帳票でないページは、罫線の帳票として、セルの並びをそのまま表にする (測定記録、検査記録)。
表の構造を推定しないので、行の統合や値のずれが起きない。

```text
部位 | 計測値 | 計測日 | 担当
〃 | 1 | 2 | 3 | 4 | 〃 | 〃
天板 | 加工前 | 12.4 | 12.5 | 12.4 | 12.6 | 2025年4月1日 | …
〃 | 加工後 | 10.1 | ／ | 10.0 | ／ | 2025年4月8日 | …
```

- 行は、セルの上端がそろうものを 1 行にする。複数の行にまたがるセルは、2 行目以降に `〃` と出し、どの行も同じ列の並びにする。
- 空のセルも区切りを出す (飛ばすと、右の値が左の列にずれる)。行の末尾に続く空のセルは省く。
- セルを横切る斜線 (該当なし、未使用の欄) は `／`、短い横棒は `—`、丸印は `○`、印影は読まずに `(印)` とする。かすれた印影は `(印) (?)`。
- 文章や図が入る背の高いセルは、行検出を通して読む。図の中の数字が混ざることがある。
- 短い値 (4 文字以下) は別のエンジンと照合し、食い違えば `(?)` を付ける。**長い文字列は照合しないので、誤読が `(?)` なしで出ることがある。**
- 罫線の外にある文字 (欄外の手書きのページ番号など) は出ない。
- `--no-grid` で無効にでき、その場合は通常の経路で読む。

罫線の表が続く文書では、ほとんどのページがどちらの帳票でもない。帳票かどうかは NDLOCR-Lite の読みだけで見分け、
別のエンジンとの照合 (行ごとに Tesseract を起動する) は帳票と分かってから行う。欄単位の帳票の見出しがほとんど見つからない
ページは、短い値の照合と欄の読み直しに進まずに通常の経路へ回す。

テキスト層を使う PDF でも、欄の中に文章や表が入る帳票 (定義のあるもの) のページは欄単位で読む。
docling の読み順では隣り合う欄の行が混ざるため。文字は OCR せずテキスト層のものを使い、欄への割り当てだけを行う。

### チェック欄 (□ / ■)

仕様書などでは、□ を ■ に置き換えて適用する項目を示す。行頭の □ / ■ は、Markdown のタスクリスト
(`- [ ]` / `- [x]`) にそろえて出力する。OCR が読んだ記号だけに頼らず、ページ画像から四角を探して照合する。

- 画像の四角が塗りつぶされていれば選択、中が空なら未選択とする。OCR が読んだ記号と食い違えば、画像の判定を採って要確認にする。
- 四角は行の左端にあるのに OCR が記号を読み落とした行は、画像の判定で補う。
- 四角があるのに行がない項目は、その行を読み直して補う。読めなければ要確認にする。
- 四角の中にインクがあるが塗りつぶしではないもの (手書きのチェックの可能性) は、要確認にする。行頭の「国」「図」「回」のような外側が四角の漢字は、チェック欄にしない。
- 項目の一覧は `*.checkbox.json` に出る。`verified` は、画像の四角と照合できたかどうか。

### 図・写真が主のページ (図面)

ページのほとんどが図や写真のページは、NDLOCR-Lite の行検出ではほとんど読めない (手書きの文字、横向きの文字)。
macOS では Vision でも読み、結果を「参考の読み取り」として本文の後に足す。

- Vision は macOS の中で動き、資料を外部に送らない。`ocrmac` が入っていない環境では読まず、画像のまま扱う旨を注記する。
- 4 方向で読み、文字が横に並ぶ向きのうち最も多く読めたものを採る。
- 名称や型式は読めるが、寸法などの数字には誤りが混ざる。確定扱いにせず、`dococr-review` の一覧に挙げる。
- 図番と名称は表題欄から読めないことが多いので、ファイル名や対応表 (`dococr-map`) から取るとよい。
- `--no-drawings` で無効にできる。

### 図・写真の切り出し

ファイルの中の図や写真は画像ファイルに切り出し、Markdown の元の位置から参照する。

```text
out/
  仕様書.md                      ![図 p.3-1](figures/%E4%BB%95%E6%A7%98%E6%9B%B8/p0003-01.png)
  figures/仕様書/p0003-01.png    p.3 の 1 つめの図
  figures/仕様書/p0007.png       ページ全体が図面や写真のページ
```

- 図の範囲は docling のレイアウト判定による。スキャンはページ画像 (300dpi) から、テキスト層のある PDF は描画したページから切り出す。
- ページのほとんどが図や写真のページ (図面) は、領域ごとに切らず、ページ全体を 1 枚にする。
- 縦か横が 0.5 インチ (約 13mm) 未満の領域は切り出さない (印影、記号、汚れ)。その位置には `<!-- image -->` が残る。
- 図の中の文字は、これまでどおり画像参照の直後に補う。
- 画像は Markdown に埋め込まず (base64 にしない)、相対パスで参照する。Markdown と `figures/` を一緒に動かせば表示できる。
- 切り出した画像の一覧 (ページ、ファイル、範囲) は `*.meta.json` の `figures` に出る。
- 帳票として読んだページの中の図は切り出さない。
- Word は `dococr-strike 仕様書.docx -o out.md` で、文書に埋め込まれた画像を取り出して元の位置から参照する。Excel の図形は対象外。
- `--no-figures` で無効にできる。

## 確認が必要な箇所の一覧 (`dococr-review`)

構造化 OCR の出力フォルダから、人が確認すべき箇所を 1 つの一覧にまとめる。

```bash
dococr-review out -o review.md --csv review.csv
```

| 種類 | 拾うもの |
| --- | --- |
| 未読領域 | 文字領域のインクのうち、行として読めた割合が 6 割未満のページ |
| 行検出の崩壊 | 行検出が意味のない結果を返し、分割して読み直したページ |
| 取り消し線 | 範囲が推定のもの、表・図の中にあって確定しなかったもの |
| チェック欄 | OCR の記号と画像の四角が食い違うもの、手書きの可能性があるもの、行を読めていないもの |
| 帳票の値 | OCR エンジンの結果がそろわず、確定できなかった値 |
| 処理の失敗 | 変換に失敗したファイル |

## 視覚モデルによる読み取りの試行 (`dococr-vlm`)

OCR だけでは取れないもの (測定記録の手書きの数値、図面の表題欄や部品表) を、ページ画像と OCR 結果を視覚モデルに渡して構造化させる。

> **ページ画像と OCR 結果を社外のサービスに送信する。** 契約済みのサービスに限って使うこと。
> `--allow-external` を付けない限り送信しない。送信するページは、送る前に出力先の `sent_log.jsonl` に記録する (応答を受け取れなくても、送ったことは残る)。

```sh
pip install -e ".[ocr,vlm]"
dococr-vlm 報告書.pdf --task measurement --pages 118-122 \
    --ndlocr-src ndlocr-lite/src --out vlm_out --provider claude-code --allow-external
```

- `--task`: `measurement` (測定記録の表) / `drawing` (図面の表題欄と部品表)
- `--provider`: `claude-code` は Claude Code の CLI (`claude -p`) を呼ぶ。API キーは要らず、Claude Code の認証を使う。CLI にはページ画像の読み取りだけを許し、ほかのツールや連携先は使わせない。`anthropic` / `bedrock` / `vertex` は SDK (`pip install -e ".[vlm]"`) を使い、認証情報は各 SDK の標準の環境変数から読む
- `claude-code` では、ページ全体に加えて 2×2 に分けた拡大図も渡す (CLI が大きい画像を縮小して読むため)。`--split 1` で渡さない
- `--task drawing` では、Vision が使える環境なら Vision の読み取りを OCR 結果として使い、向きも直してから渡す
- 視覚モデルが返した値は、OCR が同じ値を読んでいるものだけを「裏付けあり」とする。2 文字以下の値は OCR の 1 つの読み取りと丸ごと一致したとき、それより長い値は別の数値や語の途中に当たらないときだけ (「5」が日付の一部に当たるだけでは裏付けにしない)。それ以外と、モデルが自信がないとした値は `(?)` を付けて要確認にする
- 個人名や印影の文字は取り出さないよう指示している
- 出力: `<名前>.vlm.md` (表)、`<名前>.vlm.json` (値ごとの裏付け、所要時間、トークン数)。1 ページごとに書き出し、失敗したページは `error` を持つ (終了コード 1)

## 用語集 (`dococr-glossary`)

OCR を始める前に、OCR が要らないファイルから固有名詞や型番を集めて用語集に書き出し、OCR の読み取りをそれと照らし合わせる。

```sh
dococr-glossary --root 入力フォルダ -o glossary.tsv     # 用語集だけを作る
dococr-ocr --root 入力フォルダ --list files.txt --out out --ndlocr-src ndlocr-lite/src
```

`dococr-ocr` は、`--root` があれば最初に用語集を作り、出力先の `glossary.tsv` に書き出してから OCR を始める。
すでに `glossary.tsv` があればそれを使うので、人が行を足したり消したりした内容は保たれる。`--glossary` で別のファイルを指定でき、`--no-glossary` で照合を止められる。

### 用語の集め方

- 対象: テキスト層を使える PDF、Word、Excel (旧形式は変換して読む) の本文と、ファイル名の先頭の番号・名称
- 型番: 英大文字で始まり数字を含む、英数字とハイフンの並び (`KX416-2`、`V-AB-016`、`SUS316L`)
- 用語: 漢字とカタカナの並び (`自動梱包ロボット`、`パレタイザー`)。ひらがなで区切れるので、名詞の複合語が取れる
- 本文の語は 2 回以上出たものだけを載せる。ファイル名の番号と名称は 1 回でも載せる
- 行の折り返しで切れた語は載せない
- 形態素解析はしていないので、一般的な語も入る。固有名詞だけに絞ってはいない

### 読み取りとの照合

| 場合 | 扱い |
|---|---|
| 用語集にない語が、用語集の語と**紛らわしい文字** 1 つだけ違う (`ボンプ` と `ポンプ`、長音と漢数字の一) | 補正し、`<!-- 用語集で補正 p.N: … -->` と注記する |
| 型番が、用語集の型番と紛らわしい文字 1 つだけ違う (`P-1B` と `P-18`、`V-AB-O16` と `V-AB-016`) | どちらも実在する番号のことがあるので書き換えない。信頼度の低い行のものだけ、要確認として挙げる。小文字や縦棒が混ざって型番として書けない読み取り (`V-AB-0l6`) は補正する |
| 型番のハイフンを長音や漢数字の一と読んだもの、大文字を小文字と読んだもの | 補正する |
| それ以外の 1 文字違い (`下部シャッター` と `上部シャッター`、`V-AB-076` と `V-AB-016`) | 別の実在する語のことがあるので書き換えない。信頼度の低い行のものと、用語集の語が資料に 5 回以上出ているものを、要確認として挙げる |
| 帳票で 2 つのエンジンの読みが食い違い、片方だけが用語集にある | 用語集にある方に確定する |
| 4 文字未満の語、候補が 2 つ以上ある語 | 何もしない |

補正と候補は、ファイルごとの `<名前>.glossary.json` に残る (`applied` が補正したかどうか)。

## ファイルの対応表 (`dococr-map`)

2 つのフォルダのファイルを、ファイル名の先頭にある番号で突き合わせる。台帳のファイル (1 つの番号に 1 ファイル) と、
関連ファイル (図面、取扱説明書など) が対象。図面の表題欄は読めないことが多いので、番号や名称はファイル名から取る。

```sh
dococr-map --items 台帳のフォルダ --related 図面のフォルダ -o map.md --csv map.csv
```

- 番号のハイフンの有無 (`TD-3A` と `TD3A`) は同じものとして扱い、表記ゆれとして記録する。
- `PA1A・B` のように 2 つの番号で 1 つのファイルは、両方に対応づける。
- 番号のない関連ファイルは、名称が同じものを候補として挙げる。同じ名称のものが複数あるので、確定はしない。
- 名称の違い、「(仮)」の表記、関連ファイルのない番号も一覧に残す。
- ファイル名の末尾から読み取る関連ファイルの種類 (既定は 外形図、構造図、取扱説明書 など) は、`--kinds` で替えられる。

## 採点 (`dococr-eval`)

構造化 OCR の出力を正解データと照らして採点する。改善のたびに同じ正解データで測り、前回より下がった指標があれば知らせる。

```sh
dococr-eval --gt gt.json --out out/ --save result.json
dococr-eval --gt gt.json --out out/ --baseline result.json   # 前回より下がれば終了コード 1
```

正解データには資料の内容が入るので、このリポジトリには置かない。形式は次のとおり。`output` は出力フォルダからの相対パス (拡張子なし)。`page` を省くとファイル全体で採点する。

```json
{"cases": [{
  "name": "計画概要書 (例)", "output": "フォルダ/ファイル名", "page": 1,
  "contains": ["ページのどこかに含まれる文字列"],
  "fields": {"題名": ["`## 題名` の本文に含まれる文字列"]},
  "pairs": [["型式", "`型式 | 値` と並ぶ行の値"]],
  "checkboxes": [1, 0, 1],
  "struck": ["取り消し線が付いている文字列"],
  "not_struck": ["取り消し線が付いていない文字列"],
  "struck_count": 10
}]}
```

- `checkboxes` は、ページ内のチェック欄を上から順に並べた状態 (1 = 選択、0 = 未選択)。
- 全角・半角、空白、区切りの記号の違いは比べない。数字に挟まれたピリオド (小数点) は比べる (`1.5` を `15` と読めば不正解)。
- 出力がないケースは、すべて不正解として数える。

## モジュールの構成

1 つのモジュールが 1 つの役割を持つ。モジュール全体で共有する状態は持たない。

| 役割 | モジュール |
| --- | --- |
| ライブラリの入口 | `api` (`extract_strikes`、`ocr_files`) |
| コマンド | `cli` (dococr-strike)、`pipeline` (dococr-ocr)、`form_reader` (dococr-form)、`convert` (dococr-convert)、`review` (dococr-review)、`evaluate` (dococr-eval)、`mapping` (dococr-map)、`glossary` (dococr-glossary)、`vlm` (dococr-vlm) |
| 入力の準備 | `convert` 旧形式の変換 / `route` PDF の経路判定 / `render` ページの画像化 |
| OCR | `ndl` モデルの読み込み / `line_ocr` 行単位の OCR と読み直し / `crosscheck` 複数エンジンでの照合 |
| 構造化 OCR | `docling_ocr` docling の OCR 段の差し替え / `pipeline` ファイルごとの処理の流れ / `export` Markdown の出力 / `drawing` 図面のページの読み取り / `figures` 図・写真の切り出し |
| 帳票 | `form_defs` 帳票の定義の読み込み / `form_cells` セル単位の帳票 / `form_regions` 欄単位の帳票 / `form_verify` 値の検証 / `form_grid` 定義のない罫線の帳票 / `form_reader` 帳票の判定 / `textlayer` テキスト層の行と空白 |
| 取り消し線 | `strike_docx` Word / `strike_xlsx` Excel / `strike_pdf` テキスト層のある PDF / `strike_image` スキャン画像 |
| チェック欄 | `checkbox` |
| 確認の一覧 | `review` |
| 採点 | `evaluate` |
| 用語集 | `glossary` 用語の収集と、読み取りとの照合 |
| 対応表 | `mapping` |
| 視覚モデルの試行 | `vlm` |
| 共通 | `types` 受け渡すデータの形 / `config` 基準値 / `textutil` 文字列と行の並び / `mdutil` 取り消し線の Markdown |

OCR の行は辞書で受け渡す。どの処理がどの項目を付けるかは `types.py` の `Line` に書いてある。
構造化 OCR では、docling の OCR 段がページごとの結果を `PageCollector` に入れ、`pipeline` がそれを受け取る。

## テスト

```bash
pip install -c constraints.txt -e ".[test]"       # docling なし。構造化 OCR のテストは飛ばされる
pip install -c constraints.txt -e ".[ocr,test]"   # すべてのテスト
pytest
```

テストは合成した Word / PDF / 画像と、架空の帳票・用語だけを使う。実資料や、特定の組織の帳票の定義・用語はリポジトリに含めない。

- `constraints.txt` は動作を確認した版。docling は内部構造に依存しているので、更新するときは `dococr-eval` で確かめる。
- GitHub Actions で、プルリクエストと main への反映のたびにテストを実行する (`.github/workflows/test.yml`)。docling を入れない環境と入れた環境の 2 通り。

## ライセンス

[MIT License](LICENSE)。

次のものは、このライセンスの対象ではない。

- `samples/mlit-kikai-r4/`: 国土交通省の文書を加工して作成したもの。[公共データ利用規約 (PDL1.0)](https://www.mlit.go.jp/link.html) に従い、出典 (国土交通省ウェブサイト) を示して使う (`samples/README.md`)。
- [NDLOCR-Lite](https://github.com/ndl-lab/ndlocr-lite): このリポジトリには含めていない。利用する側が別に取得し、そのライセンス (CC BY 4.0) に従う。
