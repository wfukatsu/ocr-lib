"""構造化 OCR の結果を Markdown にする。"""
from __future__ import annotations

import re

import pdfplumber
from docling_core.types.doc import ContentLayer, PictureItem

from . import textlayer
from .checkbox import BOX_CHARS, CHECKED_CHARS
from .config import MIN_INK_COVERED
from .mdutil import merge_adjacent
from .textutil import join_rows
from .types import Line, PageResult

PAGE_BREAK = "\n<!-- page -->\n"
IMAGE_MARK = "<!-- image -->"


def to_task_list(md: str) -> str:
    """行頭の □ / ■ を、Markdown のタスクリストの記法 (``- [ ]`` / ``- [x]``) に直す。"""
    out = []
    for line in md.split("\n"):
        m = re.match(rf"^(\s*)(?:- )?(?:\[[ xX]\] )?([{BOX_CHARS}])\s*(.*)$", line)
        if m:
            line = f"{m.group(1)}- [{'x' if m.group(2) in CHECKED_CHARS else ' '}] {m.group(3)}"
        out.append(line)
    return "\n".join(out)


def insert_picture_text(md: str, blocks: list[str], images: list[str | None] | None = None) -> str:
    """docling が図と判定した領域 (帳票など) の位置に、切り出した画像への参照と、領域の中の文字を補う。

    images は図ごとの画像参照 (切り出していない図は None)。参照がない図は、目印のコメントを残す。
    """
    images = images or [None] * len(blocks)
    parts = md.split(IMAGE_MARK)
    if len(parts) - 1 != len(blocks):
        tail = [x for pair in zip(images, blocks) for x in pair if x]
        return md + "\n\n<!-- 図・帳票内の文字 -->\n\n" + "\n\n".join(tail)
    out = parts[0]
    for blk, image, rest in zip(blocks, images, parts[1:]):
        out += (image or IMAGE_MARK) + (f"\n\n```text\n{blk}\n```" if blk else "") + rest
    return out


def _pictures(doc, layers=None):
    """(ページ番号, 左上原点の範囲) を、Markdown に出る順で返す。"""
    kw = {"included_content_layers": layers} if layers else {}
    for item, _ in doc.iterate_items(**kw):
        if isinstance(item, PictureItem) and item.prov:
            prov = item.prov[0]
            yield prov.page_no, prov.bbox.to_top_left_origin(page_height=doc.pages[prov.page_no].size.height)


def ocr_markdown(doc, lines_by_page: dict[int, list[Line]], crop=None) -> str:
    """OCR した文書を Markdown にする。図と判定された領域の文字は、同じ高さのものを 1 行にまとめて補う。

    crop(ページ番号, 範囲) は図を画像に切り出して、Markdown の画像参照を返す (切り出さなければ None)。
    """
    layers = {ContentLayer.BODY, ContentLayer.FURNITURE}
    md = merge_adjacent(doc.export_to_markdown(page_break_placeholder=PAGE_BREAK, included_content_layers=layers, escape_underscores=False))
    md = to_task_list(md)  # 行頭の □ / ■ は ``- [ ]`` / ``- [x]`` にそろえる
    blocks, images = [], []
    for page_no, b in _pictures(doc, layers):
        images.append(crop(page_no, b) if crop else None)
        inside = [l for l in lines_by_page.get(page_no, []) if b.l <= (l["box"][0] + l["box"][2]) / 2 <= b.r and b.t <= (l["box"][1] + l["box"][3]) / 2 <= b.b]
        blocks.append(join_rows(inside, lambda l: l["md"]))
    return insert_picture_text(md, blocks, images)


def text_markdown(doc, pdf: str, crop=None) -> str:
    """テキスト層から Markdown にする。docling が図と判定した領域 (帳票など) の文字は、位置を保って補う。

    文字の間の空白は、テキスト層の並びにそろえる (textlayer.Spacing)。
    """
    md = doc.export_to_markdown(page_break_placeholder=PAGE_BREAK, escape_underscores=False)
    blocks, images = [], []
    with pdfplumber.open(pdf) as plumb:
        pages = [plumb.pages[n - 1] for n in sorted(doc.pages) if 1 <= n <= len(plumb.pages)]
        parts = md.split(PAGE_BREAK)
        if len(parts) == len(pages):  # ページごとに照らす
            md = PAGE_BREAK.join(textlayer.Spacing(page.extract_text() or "").fix_markdown(part) for page, part in zip(pages, parts))
        else:
            md = textlayer.Spacing("\n".join(page.extract_text() or "" for page in pages)).fix_markdown(md)
        for page_no, b in _pictures(doc):
            images.append(crop(page_no, b) if crop else None)
            page = plumb.pages[page_no - 1]
            words = page.crop((max(0, b.l), max(0, b.t), min(page.width, b.r), min(page.height, b.b))).extract_words(x_tolerance=2, keep_blank_chars=True)
            items = [{"box": (w["x0"], w["top"], w["x1"], w["bottom"]), "md": w["text"].strip()} for w in words if w["text"].strip()]
            blocks.append(join_rows(items, lambda i: i["md"]))
    return insert_picture_text(md, blocks, images)


def page_header(page_no: int, stats: dict) -> str:
    """ページの先頭に置く注記。注意が必要なページは理由を書く。"""
    notes = []
    if stats.get("page_collapsed"):
        notes.append("行検出が崩壊したため分割して再 OCR したページ。誤読を含む可能性が高い")
    cov = stats.get("ink_covered")
    if cov is not None and cov < MIN_INK_COVERED:
        notes.append(f"未読領域あり (文字領域のインクのうち行として読めたのは {round(cov * 100)}%)")
    return f"<!-- p.{page_no}" + ((" 注意: " + " / ".join(notes)) if notes else "") + " -->"


def review_notes(page_no: int, result: PageResult) -> str:
    """判定が不確かな箇所を、断定せずページ番号付きで示す。"""
    out = ""
    # 行に対応しない線は罫線や印影のことが多いので、候補の文字列があるものだけを本文に注記する (全件は strike.json)
    strikes = [it["candidate"] for it in result.strike_review if it["candidate"]]
    if strikes:
        out += f"\n\n<!-- 要確認 p.{page_no}: 取り消し線の範囲が不確か: " + " / ".join(strikes) + " -->"
    out += glossary_notes(page_no, result.glossary)
    checks = result.checks["review"]
    if checks:
        out += f"\n\n<!-- 要確認 p.{page_no}: チェック欄の判定が不確か: " + " / ".join((it["text"][:20] or "(行を読めていない)") + f" [{it['reason']}]" for it in checks) + " -->"
    return out


def glossary_notes(page_no: int, terms: dict) -> str:
    """用語集で補正した語と、書き換えずに候補として挙げた語の注記。"""
    pairs = lambda items: " / ".join(dict.fromkeys(f"{i['from']} → {i['to']}" for i in items))
    out = ""
    if terms.get("fixes"):
        out += f"\n\n<!-- 用語集で補正 p.{page_no}: {pairs(terms['fixes'])} -->"
    if terms.get("suggestions"):
        out += f"\n\n<!-- 要確認 p.{page_no}: 用語集に 1 文字違いの語がある (書き換えていない): {pairs(terms['suggestions'])} -->"
    return out


def form_page(page_no: int, form: dict) -> str:
    """帳票として読んだページの Markdown。"""
    note = f"\n\n<!-- 要確認 p.{page_no}: 読み取りが確定できなかった値: " + " / ".join(form["review"]) + " -->" if form["review"] else ""
    return f"<!-- p.{page_no} 帳票: {form['form']} -->\n\n{form['markdown']}{note}{glossary_notes(page_no, form.get('glossary') or {})}"
