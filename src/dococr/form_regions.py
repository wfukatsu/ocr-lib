"""欄の中に文章や表が入る帳票を、見出しごとに読む (題名・概要・理由などの欄が並ぶ様式)。"""
from __future__ import annotations

import cv2
import numpy as np

from .form_cells import DARK, find_cells, text_boxes
from .mdutil import escape
from .textutil import join_rows, norm


def _label_score(text: str, label: str) -> float:
    """読み取りに含まれる見出しの文字の割合。縦書きの見出しは 1 文字ずつ誤読されやすいので、文字の重なりで照合する。"""
    rest, hit = list(text), 0
    for ch in label:
        if ch in rest:
            rest.remove(ch)
            hit += 1
    return hit / len(label)


def find_labels(cells: list[tuple], lines: list[dict], labels: list[str], dpi: int = 300) -> dict[str, tuple]:
    """見出しの欄を探し、{見出し: 欄 (x, y, w, h)} を返す。

    見出しと値が同じ欄に入っている場合 (間の罫線が拾えなかった場合) は、見出しの行の範囲を欄として返す。
    """
    cand = []
    for cell in cells:
        x, y, w, h = cell
        inside = [l for l in lines if x <= (l["box"][0] + l["box"][2]) / 2 <= x + w and y <= (l["box"][1] + l["box"][3]) / 2 <= y + h]
        text = norm("".join(l["text"] for l in sorted(inside, key=lambda l: (l["box"][1], l["box"][0]))))
        if not text or len(text) > 16:
            continue
        vertical = h > 1.8 * w and w < 0.4 * dpi  # 1 文字ずつ縦に並ぶ、幅の狭い欄
        for lab in labels:
            score = _label_score(text, lab) if vertical else (1.0 if text == lab else 0.0)
            if score >= 0.5:
                cand.append((score, len(lab), lab, cell))
        if not vertical:  # 欄の先頭の行が見出しそのもの
            first = min(inside, key=lambda l: l["box"][1])
            lab = norm(first["text"])
            if lab in labels and len(inside) > 1:
                fx0, fy0, fx1, fy1 = first["box"]
                cand.append((0.99, len(lab), lab, (x, y, w, fy1 - y + 2)))
    found: dict[str, tuple] = {}
    taken = set()
    for score, _, lab, cell in sorted(cand, key=lambda c: (-c[0], -c[1])):  # 一致の強い順、同点なら長い見出しを優先
        if lab not in found and cell not in taken:
            found[lab] = cell
            taken.add(cell)
    return found


def infer_labels(cells: list[tuple], found: dict[str, tuple], order: list[list[str]], dpi: int = 300) -> list[str]:
    """行検出が見落とした縦書きの見出しを、並び順から推定して found に足す。足した見出しを返す。

    order は、同じ段に左から並ぶ見出しの組。見つかった見出しと同じ段にある、縦長で幅の狭い空きの欄を、
    見つからなかった見出しの欄とみなす。
    """
    added = []
    for row in order:
        for i, lab in enumerate(row):
            known = [l for l in row if l in found]
            if lab in found or not known:
                continue
            _, ry, _, rh = found[known[0]]
            left = max((found[l][0] + found[l][2] for l in row[:i] if l in found), default=0)
            right = min((found[l][0] for l in row[i + 1 :] if l in found), default=float("inf"))
            cand = [c for c in cells if c not in found.values() and c[3] > 1.8 * c[2] and c[2] < 0.4 * dpi and left <= c[0] and c[0] + c[2] <= right
                    and c[3] >= 0.7 * rh and min(c[1] + c[3], ry + rh) - max(c[1], ry) > 0.7 * min(c[3], rh)]  # fmt: skip
            if len(cand) == 1:  # 候補が 1 つに決まる場合だけ
                found[lab] = cand[0]
                added.append(lab)
    return added


def is_circle_mark(ink: np.ndarray) -> bool:
    """行の範囲のインクが丸印 (○) 1 つか。英数字の O や 0 は縦長なので、縦横比で分ける。"""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
    if n < 2:
        return False
    i = 1 + int(np.argmax(stats[1:, 4]))
    x, y, w, h, area = stats[i]
    if not (0.9 <= w / h <= 1.1) or area < 0.9 * ink.sum():
        return False
    ys, xs = np.where(lab == i)
    d = np.hypot(xs - (x + w / 2), ys - (y + h / 2))
    return bool(d.std() < 0.13 * d.mean())  # インクが中心から同じ距離に並ぶ (輪になっている)


def clean_lines(img: np.ndarray, lines: list[dict], dpi: int = 300, grid: np.ndarray | None = None) -> list[dict]:
    """点線の交点を文字として読んだ小さな行を除き、丸印を ○ にそろえる。"""
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    ink = (gray < DARK) if grid is None else (gray < DARK) & (grid == 0)  # 罫線は除く
    tiny = 0.09 * dpi  # 約 2mm。帳票の文字はこれより大きい
    out = []
    for ln in lines:
        x0, y0, x1, y1 = (max(int(v), 0) for v in ln["box"])
        if x1 - x0 < tiny and y1 - y0 < tiny:
            continue
        if len(norm(ln["text"])) <= 3 and is_circle_mark(ink[y0:y1, x0:x1]):
            ln = {**ln, "text": "○", "certain": True, "by": "shape"}
        out.append(ln)
    return out


def reread_low_cells(img: np.ndarray, grid: np.ndarray, cells: list[tuple], lines: list[dict], reader, dpi: int = 300) -> list[dict]:
    """行検出がうまく読めなかった 1〜2 行の欄を、行検出を通さずセル単位で読み直す。

    - 確定できなかった行がある欄。字間を空けた日付 (「自 2023 年 6 月 1 日」) は、行検出が数字と単位を
      ばらばらに拾う。読み直しがすべて確定できた場合だけ置き換える。
    - 文字があるのに行が 1 つもない欄。行検出が欄ごと見落とすことがある (右上の事業所名・費目など)。
      ほかに読み取りがないので、確定できなかった値も要確認として採る。
    """
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    ink = ((gray < DARK) & (grid == 0)).astype(np.uint8)
    pad = round(0.017 * dpi)
    out = list(lines)
    for x, y, w, h in cells:
        if h > 0.6 * dpi or w < 0.3 * dpi:
            continue
        inside = [l for l in out if x <= (l["box"][0] + l["box"][2]) / 2 <= x + w and y <= (l["box"][1] + l["box"][3]) / 2 <= y + h]
        if inside and all(l.get("certain", True) for l in inside):
            continue
        fresh = []
        for x0, y0, x1, y1 in text_boxes(ink[y : y + h, x : x + w], dpi):
            res = reader.read(img[max(y + y0 - pad, 0) : y + y1 + pad, max(x + x0 - pad, 0) : x + x1 + pad])
            if res["text"]:
                fresh.append({"box": [x + x0, y + y0, x + x1, y + y1], "conf": 1.0, **res, "by": "cell"})
        if fresh and (not inside or all(l["certain"] for l in fresh)):
            out = [l for l in out if all(l is not i for i in inside)] + fresh
    return out


def read_regions(img: np.ndarray, line_ocr, form: dict, dpi: int = 300, checker=None, reader=None, clean: bool = True, min_labels: int = 0) -> dict | None:
    """欄ごとに文章や表が入る帳票を読む。{"fields": {見出し: 文字列}, "rest": 残りの行, …}

    罫線から見出しの欄を探し、その右隣 (次の見出しまで) か真下の範囲に入る行を、その見出しの値とする。
    行はページ全体を行単位で OCR して得る。

    min_labels は、この帳票とみなすのに要る見出しの数。行を読んだ時点で見出しがその 1/3 に満たなければ、
    この帳票ではないとして None を返す。短い値の照合と欄の読み直しは、罫線の表が続く文書では 1 ページに
    数百回の文字認識になるので、帳票ではないページでは行わない (読み直しで足せる見出しは数個まで)。
    """
    H, W = img.shape[:2]
    cells, grid = find_cells(img, dpi, min_fill=0.35)
    lines = line_ocr(img)
    if clean:  # OCR の誤読の補正。テキスト層から取った行には要らない
        lines = clean_lines(img, lines, dpi, grid)
    if min_labels and len(find_labels(cells, lines, list(form["labels"]), dpi)) < max(1, min_labels // 3):
        return None
    if checker is not None:
        checker(img, lines)
    if reader is not None:
        lines = reread_low_cells(img, grid, cells, lines, reader, dpi)
    found = find_labels(cells, lines, list(form["labels"]), dpi)
    inferred = infer_labels(cells, found, form.get("order", []), dpi)
    center = lambda l: ((l["box"][0] + l["box"][2]) / 2, (l["box"][1] + l["box"][3]) / 2)
    in_label = lambda l: any(x <= center(l)[0] <= x + w and y <= center(l)[1] <= y + h for x, y, w, h in found.values())
    fields, used = {}, set()
    for lab, (x, y, w, h) in found.items():
        if form["labels"][lab] == "below":
            box = (x, y + h, x + w, y + h + 1.3 * h)
        else:
            # 右隣から、同じ高さにある次の見出しの手前まで
            nxt = [x2 for l2, (x2, y2, w2, h2) in found.items() if l2 != lab and x2 >= x + w and min(y + h, y2 + h2) - max(y, y2) > 0.3 * min(h, h2)]
            box = (x + w, y, min(nxt) if nxt else W, y + h)
        mine = [l for l in lines if not in_label(l) and box[0] <= center(l)[0] <= box[2] and box[1] <= center(l)[1] <= box[3]]
        fields[lab] = _rows(mine)
        used |= {id(l) for l in mine}
    rest = [l for l in lines if id(l) not in used and not in_label(l)]
    review = [l["text"] + (f" (別の読み: {l['third']})" if l.get("third") else "") for l in lines if not l.get("certain", True) and not in_label(l)]
    return {"fields": fields, "rest": _rows(rest), "review": review, "labels_found": len(found) - len(inferred), "inferred": inferred, "cells": len(cells), "lines": len(lines)}


def _rows(lines: list[dict], sep: str = "\n") -> str:
    """行を上から並べ、同じ高さの行は左から ` | ` でつなぐ。確定できなかった値には ` (?)` を付ける。"""
    return join_rows(lines, lambda l: escape(l["text"]) + ("" if l.get("certain", True) else " (?)"), sep)


def regions_markdown(res: dict, form: dict) -> str:
    out = [f"## {lab}\n\n{res['fields'][lab] or '(空欄)'}" for lab in form["labels"] if lab in res["fields"]]
    missing = [lab for lab in form["labels"] if lab not in res["fields"]]
    if missing:
        out.append("<!-- 要確認: 見出しの欄が見つからなかった項目: " + " / ".join(missing) + " -->")
    if res.get("inferred"):
        out.append("<!-- 要確認: 見出しを読めず、欄の並びから推定した項目: " + " / ".join(res["inferred"]) + " -->")
    if res["rest"]:
        out.append(f"## その他\n\n```text\n{res['rest']}\n```")
    return "\n\n".join(out)
