"""PDF のテキスト層が信用できるかを判定し、処理の経路を決める。

テキスト層の有無だけでは足りない。文字化けしたテキスト層や、スキャンに OCR 結果を重ねた
テキスト層は、あっても使えない。
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pdfplumber

TEXT = "text"  # テキスト層をそのまま使える
GARBLED = "garbled"  # テキスト層はあるが文字化けしている (フォントに Unicode 対応表がない)
OCR_LAYER = "ocr_layer"  # スキャン画像に OCR 結果のテキストを重ねたもの
IMAGE = "image"  # テキスト層がない

KIND_LABEL = {TEXT: "テキスト層を使用", GARBLED: "テキスト層が文字化けのため OCR", OCR_LAYER: "OCR 済みスキャンのため OCR をやり直し", IMAGE: "テキスト層がないため OCR"}

MIN_CHARS = 20  # 1 ページにこれ未満しか文字がなければテキスト層なしとみなす
SPARSE_CHARS = 150  # 画像が大きいページで、文字がこれ未満なら本文は画像とみなす
GARBLED_RATIO = 0.1
FULL_IMAGE_RATIO = 0.85  # ページをこの割合以上覆う画像があればスキャンとみなす


def _is_garbled_char(text: str) -> bool:
    if text.startswith("(cid:"):  # Unicode に対応付けられなかった文字
        return True
    # 対応表のないフォントの文字が Latin-1 の記号や私用領域に化けたもの
    return len(text) == 1 and (0x80 <= ord(text) <= 0xFF or 0xE000 <= ord(text) <= 0xF8FF or ord(text) < 0x20 and text not in "\t\n\r")


def classify_page(page) -> str:
    chars = [c for c in page.chars if not c["text"].isspace()]
    if len(chars) < MIN_CHARS:
        return IMAGE
    if sum(_is_garbled_char(c["text"]) for c in chars) / len(chars) > GARBLED_RATIO:
        return GARBLED
    area = page.width * page.height
    sizes = [(im["x1"] - im["x0"]) * (im["bottom"] - im["top"]) for im in page.images]
    if any(a >= FULL_IMAGE_RATIO * area for a in sizes):
        return OCR_LAYER
    # 見出しだけがテキストで、本文が画像のページ (スライドなど)
    if sum(sizes) >= 0.4 * area and len(chars) < SPARSE_CHARS:
        return IMAGE
    return TEXT


def classify(path: str | Path) -> dict:
    """PDF 全体の経路を返す。{"kind": …, "pages": ページ数, "page_kinds": ページの内訳, "ocr_pages": OCR が必要なページ}

    すべてのページを見る。OCR が必要なページが 2 割を超えれば、文書全体を OCR の経路に回す
    (多い順に GARBLED / OCR_LAYER / IMAGE を選ぶ)。2 割以下なら文書はテキスト層を使うが、
    OCR が必要なページ (本文の後ろに綴じたスキャンなど) は ocr_pages に挙げ、そのページだけ OCR する。
    抜き取りで判定すると、こうしたページを見落として、中身が何も出力されない。
    """
    with pdfplumber.open(path) as pdf:
        per_page = []
        for page in pdf.pages:
            per_page.append(classify_page(page))
            page.flush_cache()  # ページ数の多い PDF で、読んだ文字を持ち続けない
    kinds = Counter(per_page)
    need_ocr = {k: v for k, v in kinds.items() if k != TEXT}
    if sum(need_ocr.values()) > 0.2 * len(per_page):
        kind = max(need_ocr, key=need_ocr.get)
    else:
        kind = TEXT
    return {"kind": kind, "pages": len(per_page), "page_kinds": dict(kinds), "ocr_pages": [i for i, k in enumerate(per_page, 1) if k != TEXT]}


def is_image_file(path: str | Path) -> bool:
    return re.fullmatch(r"\.(png|jpe?g|tiff?|bmp|webp)", Path(path).suffix.lower()) is not None
