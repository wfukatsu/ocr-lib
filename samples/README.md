# サンプル

文書を dococr で読んだ結果。出力は手を加えていない (誤読や誤判定もそのまま残している)。
ただし `*.meta.json` の `source` は、実行した環境のパスを元文書の場所に書き換えた。

| サンプル | 元文書 | 見られるもの |
| --- | --- | --- |
| [公開されている仕様書](#公開されている仕様書-mlit-kikai-r4) | 国土交通省の標準仕様書 (PDF) | 経路判定、テキスト層の経路と OCR の経路の違い |
| [取り消し線](#取り消し線-strike) | このリポジトリで作った架空の作業要領書 (Word / Excel / PDF / スキャン PDF) | 形式ごとの取り消し線の抽出と、要確認の出方 |
| [手書き](#手書き-handwriting) | このリポジトリで作った架空の点検記録と連絡メモ (画像だけの PDF) | 手書きの値を、標準の OCR、macOS の Vision、視覚モデルがそれぞれどこまで読めるか |

# 公開されている仕様書 (`mlit-kikai-r4/`)

## 元文書

| 項目 | 内容 |
| --- | --- |
| 文書 | 公共建築工事標準仕様書（機械設備工事編）令和４年版 (国土交通省大臣官房官庁営繕部、PDF、360 ページ) |
| 場所 | <https://www.mlit.go.jp/gobuild/content/001879206.pdf> |
| 掲載ページ | <https://www.mlit.go.jp/gobuild/gobuild_tk6_000021.html> |
| 取得日 | 2026-10-07 (SHA-256: `19ffa5936909d16c1e5e8704b4c6d4c1232b19f7843bbe297d9a48c05feed8e1`) |
| 利用条件 | [公共データ利用規約 (PDL1.0)](https://www.mlit.go.jp/link.html) |

元文書の PDF は、このリポジトリには置いていない。上の場所から取得する。

出典：国土交通省ウェブサイト (<https://www.mlit.go.jp/gobuild/gobuild_tk6_000021.html>)。
このフォルダの Markdown と JSON は、上の文書を dococr で加工して作成したもので、国土交通省が作成したものではない。

## 変換後のファイル

| 経路 | ページ | 変換後の Markdown | 併せて出るファイル |
| --- | --- | --- | --- |
| テキスト層を使用 (OCR なし) | 1〜12 | [`mlit-kikai-r4/text-layer/kikai_r4_p001-012.md`](mlit-kikai-r4/text-layer/kikai_r4_p001-012.md) | `kikai_r4_p001-012.meta.json` |
| OCR (`--force-ocr`、用語集つき) | 9〜11 | [`mlit-kikai-r4/ocr/kikai_r4_p009-011_ocr.md`](mlit-kikai-r4/ocr/kikai_r4_p009-011_ocr.md) | `…_ocr.meta.json` / `…_ocr.glossary.json` / `…_ocr.strike.json` / [`glossary.tsv`](mlit-kikai-r4/ocr/glossary.tsv) |

ページごとの docling の出力 (`json/`) は、大きいので置いていない。

## 再現の手順

```bash
mkdir src_pdf && curl -L -o src_pdf/kikai_r4.pdf https://www.mlit.go.jp/gobuild/content/001879206.pdf

# テキスト層を使う経路 (この PDF は文字を取り出せるので、OCR しない)
dococr-ocr --ndlocr-src ndlocr-lite/src --out samples/mlit-kikai-r4/text-layer \
    --pages 1-12 --name kikai_r4_p001-012 src_pdf/kikai_r4.pdf

# 文書のテキスト層から用語集を作る (3,340 語)
dococr-glossary --root src_pdf -o samples/mlit-kikai-r4/ocr/glossary.tsv

# 同じ文書を、ページを画像にして OCR で読む。用語集と照らし合わせる
dococr-ocr --ndlocr-src ndlocr-lite/src --out samples/mlit-kikai-r4/ocr --glossary samples/mlit-kikai-r4/ocr/glossary.tsv \
    --pages 9-11 --force-ocr --name kikai_r4_p009-011_ocr src_pdf/kikai_r4.pdf
```

`constraints.txt` の版と NDLOCR-Lite (`636d1cf`)、macOS で実行した。所要時間は、テキスト層の 12 ページが約 30 秒、用語集が約 30 秒、OCR の 3 ページが約 40 秒 (モデルの読み込みを含む)。

## 結果から分かること

9〜11 ページは両方の経路で読んでいるので、見比べられる。

- **テキスト層の経路**: 文字は元文書のとおりで、誤読がない。見出し、箇条書き、表 (表1.1.1 機材の試験) が Markdown になる。
  文字の間の空白は、テキスト層の並びにそろえている (`1.1.1 適用`)。
- **テキスト層の経路で崩れる表**: 12 ページの表は、左端の見出しが縦書き (「送風機」「ポンプ類」を 1 文字ずつ縦に並べたもの) で、
  docling が列を取り違えて、セルの中身がばらばらになる。縦書きには対応していない。
- **OCR の経路**: 表も Markdown の表になる。誤読がある (「監督職員」→「監督報員」、「合板」→「今板」、「工事現場」→「工事院婦」、「(ｱ)」→「(了)」)。
- **用語集による補正**: カタカナの取り違え 2 か所を補正した (「吸収冷温水機コニット」→「…ユニット」、「シーリングディフェーザー」→「…ディフューザー」)。
  補正した箇所は、Markdown の `用語集で補正` の注記と `*.glossary.json` に残る。
  上の漢字の誤読は補正されない。「今板」「院婦」は 2 文字で、4 文字未満の語は 1 文字違いの別の語が多いので扱わない。
  「監督報員」は、行の折り返しで「監督報」と「員」に分かれて読まれていて、語として照らし合わせられない。
- **経路判定**: 文書全体の判定は「テキスト層を使用」で、360 ページのうち 2 ページ (p.294、p.312) はテキスト層を使えないため OCR の対象になる (Markdown の先頭の注記)。

# 取り消し線 (`strike/`)

取り消し線の入った公開文書は見つからなかったので、架空の作業要領書の改訂案を作った。
同じ内容を 4 つの形式にしてあり、形式ごとの確実さの違いを見比べられる。

## 元文書

[`strike/make_sample.py`](strike/make_sample.py) が作る。内容は架空で、実在の文書や組織とは関係がない。

| 元文書 | 形式 | 取り消し線の入れ方 |
| --- | --- | --- |
| [`strike/source/youryou.docx`](strike/source/youryou.docx) | Word | 文字の書式 |
| [`strike/source/youryou.xlsx`](strike/source/youryou.xlsx) | Excel (2 シート) | セルの書式と、セル内の一部の文字の書式 |
| [`strike/source/youryou_text.pdf`](strike/source/youryou_text.pdf) | テキスト層のある PDF | 文字の上に引いた線 |
| [`strike/source/youryou_scan.pdf`](strike/source/youryou_scan.pdf) | 画像だけの PDF (300dpi、少しぼかしてある) | 画像の中の線 |

取り消し線は 6 か所ある: 行全体が 3 か所、行の一部が 1 か所、表のセルの一部が 1 か所、表のセル全体が 1 か所。
取り消し線ではない線として、下線 (「異音のないこと」) と表の罫線を入れてある。

スキャン PDF は、紙を読み取ったものではなく、画像に描いて作ったもの。傾き、かすれ、手書きの線はない。

## 変換後のファイル

| 元文書 | 変換後の Markdown | 取り消し線の一覧 |
| --- | --- | --- |
| Word | [`strike/output/youryou.docx.md`](strike/output/youryou.docx.md) | `youryou.docx.strike.json` |
| Excel | [`strike/output/youryou.xlsx.md`](strike/output/youryou.xlsx.md) | `youryou.xlsx.strike.json` |
| テキスト層のある PDF | [`strike/output/youryou_text.pdf.md`](strike/output/youryou_text.pdf.md) | `youryou_text.pdf.strike.json` |
| スキャン PDF | [`strike/output/scan/youryou_scan.md`](strike/output/scan/youryou_scan.md) | `scan/youryou_scan.strike.json` (ほかに `scan/youryou_scan.meta.json`) |

## 再現の手順

```bash
python samples/strike/make_sample.py samples/strike/source   # python-docx、reportlab、pillow と日本語のフォントが要る

dococr-strike samples/strike/source/youryou.docx -o samples/strike/output/youryou.docx.md --report samples/strike/output/youryou.docx.strike.json --no-figures
dococr-strike samples/strike/source/youryou.xlsx -o samples/strike/output/youryou.xlsx.md --report samples/strike/output/youryou.xlsx.strike.json
dococr-strike samples/strike/source/youryou_text.pdf -o samples/strike/output/youryou_text.pdf.md --report samples/strike/output/youryou_text.pdf.strike.json
dococr-strike samples/strike/source/youryou_scan.pdf --out-dir samples/strike/output/scan --ndlocr-src ndlocr-lite/src
```

スキャン PDF の画像は、フォントによって変わる。置いてあるものは、macOS のヒラギノ角ゴシック W3 で作った。

## 結果から分かること

| 取り消し線 | Word | Excel | テキスト層のある PDF | スキャン PDF |
| --- | --- | --- | --- | --- |
| 行全体 (3 か所) | ○ | ○ | ○ | ○ |
| 行の一部「目視で確認する。」 | ○ | ○ | ○ | ○ |
| 表のセルの一部「1,200」 | ○ | ○ | ○ | ○ |
| 表のセル全体「定格の 110 % 以下」 | ○ | ○ | ○ | ○ |
| 下線・罫線を取り消し線にしない | ○ | ○ | ○ | ○ |

- **どの形式でも、6 か所すべてを範囲も正しく取り出した。要確認はない。**
  Excel は、取り消し線を含むセルだけをシート名とセル番地つきで出す。テキスト層のある PDF は、表が Markdown の表にならず、行ごとの文字列になる。
- **スキャン PDF の行の一部**: 文字ごとの座標がないので、線の範囲だけを切り出して読み直し、その文字列 (「目視で確認する。」) が
  行の中の 1 か所にそのまま現れることを確かめて、範囲を確定している。一致しなければ、位置からの推定として要確認に挙がる。
- **スキャン PDF の表の中**: 線がセルの文字の幅に収まり、文字の画を横切っているものは、罫線ではなく取り消し線として確定している。
  行の幅を越えて続く線や、文字の上下どちらかに寄った線は、これまでどおり確定せず要確認に挙げる。
- **スキャン PDF の誤読**: 「ベルト」を「ペルト」と読んでいる。取り消し線とは関係のない、文字認識の誤り。3 文字の語なので、用語集を渡しても補正されない (4 文字未満の語は扱わない)。
  空白も元文書と違う (`6 か月` → `6か月`)。
- **このサンプルで確かめられていないこと**: 紙を読み取った画像の傾き、かすれ、手書きの線。

# 手書き (`handwriting/`)

活字の帳票に手書きで値を書き込んだページと、手書きだけのメモのページを、3 つの手段で読んだ。

## 元文書

[`handwriting/make_sample.py`](handwriting/make_sample.py) が作る。内容は架空で、実在の文書や組織とは関係がない。

| 元文書 | 内容 |
| --- | --- |
| [`handwriting/source/tenken_tegaki.pdf`](handwriting/source/tenken_tegaki.pdf) | 画像だけの PDF (300dpi、2 ページ)。p.1 は点検記録、p.2 は連絡メモ |
| [`handwriting/source/expected.json`](handwriting/source/expected.json) | 手書きで書き込んだ内容 (正解) |

p.1 の手書きは、欄外の番号 (`No. 27`)、表の上の 4 つの欄、測定値と判定の 5 行、チェック欄のチェック 2 つ、所見の 2 行。
p.2 は、題名のほかはすべて手書き (4 行)。

**手書きは人が書いたものではない。** 手書き風のフォント (Yomogi、SIL Open Font License 1.1) の文字を、
1 文字ずつ傾き・大きさ・位置をばらつかせて描いた。字の形はそろっていて、続け字、かすれ、にじみ、紙の傾きはない。
人が書いた文字より読みやすいはずで、ここでの結果は上限の目安として見る。フォントは同梱していない。

## 変換後のファイル

| 手段 | 変換後のファイル | 併せて出るファイル |
| --- | --- | --- |
| 標準の OCR (`dococr-ocr`) | [`handwriting/output/ocr/tenken_tegaki.md`](handwriting/output/ocr/tenken_tegaki.md) | `tenken_tegaki.meta.json` / `tenken_tegaki.checkbox.json` / `tenken_tegaki.strike.json` |
| macOS の Vision | [`handwriting/output/vision/tenken_tegaki.vision.txt`](handwriting/output/vision/tenken_tegaki.vision.txt) | |
| 視覚モデル (`dococr-vlm`、p.1 のみ) | [`handwriting/output/vlm/tenken_tegaki.vlm.md`](handwriting/output/vlm/tenken_tegaki.vlm.md) | `tenken_tegaki.vlm.json` |

## 再現の手順

```bash
python samples/handwriting/make_sample.py samples/handwriting/source --hand-font Yomogi-Regular.ttf   # pillow が要る

dococr-ocr --ndlocr-src ndlocr-lite/src --out samples/handwriting/output/ocr --no-glossary samples/handwriting/source/tenken_tegaki.pdf

# 視覚モデル。ページ画像を社外に送信する (ここでは架空の文書なので送っている)
dococr-vlm --task measurement --pages 1 --ndlocr-src ndlocr-lite/src --out samples/handwriting/output/vlm \
    --provider claude-code --allow-external samples/handwriting/source/tenken_tegaki.pdf
```

Vision でページ全体を読むコマンドはない (`dococr-ocr` が Vision を使うのは、図面のページと帳票の値の多数決だけ)。
置いてある結果は、ページを 300dpi の画像にして `dococr.crosscheck.vision_read` に渡し、`dococr.textutil.join_rows` で行にまとめたもの。

## 結果から分かること

| 手書きの箇所 | 標準の OCR | Vision | 視覚モデル (p.1) |
| --- | --- | --- | --- |
| 欄外の番号 `No. 27` | ○ (題名の行に、崩れた `16-27` と二重に出る) | ○ | ○ |
| 上の 4 つの欄 (日付、氏名、設備名、天候) | 4 / 4 | 4 / 4 | 3 / 4 (点検者が空) |
| 測定値 (5 行) | 4 / 5 (`50` → `15`) | 5 / 5 | 5 / 5 |
| 判定 (5 行、1 文字) | 3 / 5 (`否` → `KD`、`良` → `表`) | 5 / 5 | 5 / 5 |
| チェック欄 (3 つ、うち 2 つにチェック) | × (一覧に出ない。行が崩れ、「給油」が落ちる) | × (記号を `M` `ロ` `k` と読む) | ○ (3 つとも正しい) |
| 所見 (2 行) | 2 / 2 | 2 / 2 | 2 / 2 |
| メモ (p.2、4 行) | 4 / 4 (3 行目が誤ってチェック欄になる) | 4 / 4 | 読んでいない |

- **そろった字の手書きは、標準の OCR でも文として読める。** 所見とメモの 6 行は 1 文字も誤っていない。
- **標準の OCR は、短い値を誤る。** 2 文字の数値と 1 文字の判定で 3 か所。前後の文字がないので、形の近い別の文字になる。
  誤った 3 か所は要確認にも挙がっていない (`meta.json` の `low_conf` は 0)。
- **標準の OCR は、手書きのチェックを取れていない。** チェックが四角からはみ出していると、画像から四角として見つからない (見つかったのは、チェックのない「ベルト交換」の四角だけ)。
  その四角も行の途中にあるので、チェック欄として扱われない。結果として 3 つとも一覧に出ず、要確認にも挙がらない。
  チェックの入った四角は「図」と読まれ、行の文字も崩れる。
- **標準の OCR の誤検出**: p.2 の「部品が届きしだい交換します。」が、未チェックのチェック欄になった。
  手書きの大きな字では、行頭の「部」の中の「口」がチェック欄の四角と同じ大きさになり、空の四角として拾われる。
- **Vision は、手書きの文字をすべて正しく読んだ。** 誤りは活字の側にある (`12.5 A` → `125A`、`70 ℃` → `7O°C`、`1 MΩ` → `1M2`)。
  チェックの有無は分からない。
- **視覚モデルは、チェックの有無まで取れた。** 一方で、点検者の欄 (「山田 太郎」) を空で返した。値の抜けは、出力からは気づけない。
  1 ページで約 23 秒、0.22 USD。
- **活字の誤読** (標準の OCR): 「空調」→「空謂」、「70 ℃ 以下」→「70以下」、「所見」→「見所」。手書きとは関係がない。

### 字の形による違い

同じ内容を、ほかの手書き風のフォントでも作って標準の OCR で読んだ (出力は置いていない)。
欄外の番号、上の 4 つの欄、測定値、所見、メモの 16 か所のうち、正しく読めた数は次のとおり。

| フォント | 字の形 | 正しく読めた数 |
| --- | --- | --- |
| Yomogi (置いてあるサンプル) | ペン字、そろっている | 15 / 16 |
| Zen Kurenaido | ペン字、そろっている | 15 / 16 |
| Hachi Maru Pop | 丸文字 | 12 / 16 |
| Yuji Boku | 筆 | 11 / 16 |
| Darumadrop One | 太い崩した字 | 5 / 16 |

字の形が活字から離れるほど読めなくなる。丸文字や筆の字では、文の行も誤る。

### このサンプルで確かめられていないこと

- 人が書いた文字。続け字、くせ字、かすれ、にじみ、紙の傾き、罫線にかかった字。
- Vision と視覚モデルの、字の形による違い (上の比較は標準の OCR だけ)。
