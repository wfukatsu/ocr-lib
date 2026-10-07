"""モジュール間で受け渡すデータの形。

OCR の行は辞書で受け渡す。行検出で作られ、後段の処理が項目を書き足す。
どの処理がどの項目を付けるかを、ここに 1 か所で書く。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict


class Line(TypedDict, total=False):
    # line_ocr: 行検出と文字認識
    box: tuple[int, int, int, int]  # (x0, y0, x1, y1)。ページ画像の画素
    text: str
    conf: float  # 行検出の信頼度

    # checkbox: 行頭にチェック欄がある行
    checkbox: bool  # 選択されているか
    recovered: bool  # 四角を手がかりに読み直して補った行
    glyph_added: bool  # OCR が読み落とした行頭の記号を、画像の判定で補った

    # strike_image: 取り消し線
    struck: str | None  # "all" (行全体) / "part" (一部) / None
    md: str  # 取り消し線を ~~ で表した Markdown
    strike_fits: bool  # 線が、この行の文字だけを横切っているか (罫線ではなさそうか)

    # crosscheck: 短い値の照合
    ndl: str  # NDLOCR-Lite の読み
    alt: str | None  # 照合先 (Tesseract) の読み。照合していなければ None
    certain: bool  # 読みが確定したか
    cell: list[int]  # 3 つ目のエンジンの読みを探す範囲
    third: str  # 3 つ目のエンジンだけが出した別の読み
    by: str  # 確定させた方法 ("sequence" / "label" / "type" / "vote" / "glossary")

    # glossary: 用語集との照合
    glossary: list[dict]  # 補正の一覧 ({"from", "to"})


@dataclass
class PageResult:
    """構造化 OCR が 1 ページを処理した結果。"""

    stats: dict = field(default_factory=dict)  # ページの統計 (meta.json に出す)
    lines: list[Line] = field(default_factory=list)  # 行。box は docling のページ座標
    strike_review: list[dict] = field(default_factory=list)  # 取り消し線の要確認
    checks: dict = field(default_factory=lambda: {"items": [], "review": [], "recovered": 0})  # チェック欄の判定
    glossary: dict = field(default_factory=lambda: {"fixes": [], "suggestions": []})  # 用語集との照合 (補正したものと、候補)
