"""定義のない罫線の帳票 (測定記録、検査記録) を、セル単位で読む。

項目名の定義 (form_defs) がなくても、罫線のセルの並びをそのまま表として出せば、
項目と値の対応は保てる。表の構造を推定しないので、行の統合や値のずれが起きない。

- 行は、セルの上端がそろうものを 1 行にする。複数の行にまたがるセル (左端の名称など) は、2 行目以降に
  「〃」と出して、どの行も同じ列の並びになるようにする。
- 空のセルも出す。飛ばすと、右の値が左の列にずれる。
- セルの対角に引いた斜線 (該当なし) と、未使用の表に引いた長い斜線は「／」とする。
- 印影は読まずに「(印)」とし、丸印は「○」とする。
- 文章や図が入る背の高いセルは、行検出を通して読む。
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from .form_cells import DARK, crop_of, find_cells, text_boxes
from .form_regions import is_circle_mark
from .mdutil import escape

NAME = "罫線の帳票"
SLASH, DITTO, DASH, STAMP, CIRCLE = "／", "〃", "—", "(印)", "○"


def long_obliques(ink: np.ndarray, dpi: int = 300) -> np.ndarray:
    """複数のセルにまたがる長い斜線 (未使用の欄を消す線) のマスクを返す。

    文字の画は短いので、1 インチ以上続く斜めの線だけを拾う。
    """
    mask = np.zeros(ink.shape, np.uint8)
    segs = cv2.HoughLinesP(ink.astype(np.uint8) * 255, 1, np.pi / 360, threshold=round(0.5 * dpi), minLineLength=round(1.0 * dpi), maxLineGap=round(0.15 * dpi))  # 罫線を横切るところで途切れる
    for x1, y1, x2, y2 in [] if segs is None else segs.reshape(-1, 4):
        if 10 <= math.degrees(math.atan2(abs(int(y2) - int(y1)), abs(int(x2) - int(x1)))) <= 80:
            cv2.line(mask, (int(x1), int(y1)), (int(x2), int(y2)), 1, thickness=max(5, round(0.03 * dpi)))
    return mask


def is_slash(ink: np.ndarray, dpi: int = 300) -> bool:
    """セルのインクが、セルを横切る 1 本の斜線だけか (該当なしの印や、未使用の欄を消す線の一部)。

    文字の「1」や「/」と分けるため、両端がセルの縁に届いている、縦でも横でもないまっすぐな線に限る。
    離れた小さな汚れは無視する。
    """
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
    if n < 2:
        return False
    i = 1 + int(np.argmax(stats[1:, 4]))
    if stats[i, 4] < 0.1 * dpi or stats[i, 4] < 0.85 * ink.sum():
        return False
    ys, xs = np.nonzero(lab == i)
    pts = np.stack([xs, ys], axis=1).astype(float)
    center = pts.mean(axis=0)
    direction = np.linalg.svd(pts - center, full_matrices=False)[2][0]
    along = (pts - center) @ direction
    across = np.abs((pts - center) @ np.array([-direction[1], direction[0]]))
    if not 8 <= math.degrees(math.atan2(abs(direction[1]), abs(direction[0]))) <= 82 or (across <= max(3.0, 0.015 * dpi)).mean() < 0.95:
        return False
    h, w = ink.shape
    edge = 0.02 * dpi  # 罫線を除いた分、線の端は縁の少し内側で終わる
    at_edge = lambda q: min(q[0], q[1], w - 1 - q[0], h - 1 - q[1]) <= edge
    return bool(at_edge(pts[along.argmin()]) and at_edge(pts[along.argmax()]))


def is_dash(ink: np.ndarray, dpi: int = 300) -> bool:
    """セルのインクが、短い横棒 1 本だけか (値がないことを示す「—」)。"""
    ys, xs = np.nonzero(ink)
    if xs.size == 0:
        return False
    w, h = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    return w >= 0.05 * dpi and w >= 3 * h and xs.size >= 0.6 * w * h


def is_stamp(ink: np.ndarray, dpi: int = 300) -> bool | None:
    """文字の範囲のインクが印影か。True = 丸い枠が見える / None = 印影らしいが、かすれていて言い切れない / False = 違う。

    印影は読まない (文字として読むと、意味のない文字列になる)。縦横がほぼ同じで文字より大きく、外接する四角の
    四隅にインクがないものを印影らしいとする (文字や図は、四隅にもインクがある)。
    """
    ys, xs = np.nonzero(ink)
    if xs.size == 0:
        return False
    w, h = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    if not (0.25 * dpi <= min(w, h) and max(w, h) <= 1.0 * dpi and 0.7 <= w / h <= 1.4):
        return False
    k = max(2, round(0.12 * min(w, h)))
    box = ink[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    corners = box[:k, :k].sum() + box[:k, -k:].sum() + box[-k:, :k].sum() + box[-k:, -k:].sum()
    if corners > 0.02 * xs.size:
        return False
    # 輪の上にインクが並ぶ (中心からの距離が、半径の近くに集まる) なら、丸い枠が見えている
    r = np.hypot(xs - (xs.min() + w / 2), ys - (ys.min() + h / 2)) / (min(w, h) / 2)
    return True if corners == 0 and (r > 1.08).mean() < 0.02 and (r >= 0.8).mean() >= 0.3 else None


def read_grid(img: np.ndarray, reader, region_ocr=None, dpi: int = 300, cached: list[dict] | None = None, post=None) -> dict:
    """罫線の帳票を読み、{"rows": 行ごとのセルの並び, "review": 要確認の一覧, "items": 値の数} を返す。

    reader は 1 行の画像を読むもの (crosscheck.CellReader と同じ形)。region_ocr(img, box) は、範囲を行検出を通して
    読むもの (背の高いセルに使う。なければ、そのセルは 1 行として読む)。cached は read_cells(check=False) の結果で、
    渡すと、同じ範囲の文字認識をやり直さない。post(読んだ行の一覧) は、セルの文字列にまとめる前に行を補正するもの
    (用語集との照合、別のエンジンとの多数決)。
    セルは {"cell": (x0, y0, x1, y1), "text", "certain", "parts": 読んだ行の一覧}。
    """
    cells, grid = find_cells(img, dpi)
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    ink = ((gray < DARK) & (grid == 0)).astype(np.uint8)
    # セルごとの斜線を先に見つける。残したまま長い斜線を探すと、縦に並んだ斜線がつながって 1 本の線に見える
    slashed = {c for c in cells if is_slash(ink[c[1] : c[1] + c[3], c[0] : c[0] + c[2]], dpi)}
    rest = ink.copy()
    for x, y, w, h in slashed:
        rest[y : y + h, x : x + w] = 0
    strike = long_obliques(rest, dpi)
    clean = ink & (1 - strike)
    if strike.any():
        img = img.copy()
        img[strike > 0] = 255
    known = {tuple(c["box"]): c for c in cached or []}
    tall = round(0.3 * dpi)
    specks = 0.0003 * dpi * dpi
    out = []
    for x, y, w, h in cells:
        cell = {"cell": [x, y, x + w, y + h], "text": "", "certain": True, "parts": []}
        out.append(cell)
        sub, crossed = clean[y : y + h, x : x + w], bool(strike[y : y + h, x : x + w].any())
        if (x, y, w, h) in slashed:
            cell.update(text=SLASH, by="shape")
            continue
        boxes = text_boxes(sub, dpi)
        if not boxes:
            if crossed:
                cell.update(text=SLASH, by="shape")
            elif is_dash(sub, dpi):
                cell.update(text=DASH, by="shape")
            continue
        for x0, y0, x1, y1 in boxes:
            box = [x + x0, y + y0, x + x1, y + y1]
            if sub[y0:y1, x0:x1].sum() < specks:  # 文字の行と同じ高さにある、離れた汚れ
                continue
            stamp = is_stamp(sub[y0:y1, x0:x1], dpi)
            if stamp is not False:
                cell["parts"].append({"box": box, "text": STAMP, "certain": stamp is True, "by": "shape"})
            elif len(boxes) == 1 and is_circle_mark(sub[y0:y1, x0:x1]):
                cell["parts"].append({"box": box, "text": CIRCLE, "certain": True, "by": "shape"})  # 文字として読むと O や 0 になる
            elif y1 - y0 > tall and region_ocr is not None:
                # 文章や図が入るセル。1 行用の文字認識では読めないので、行検出を通す
                for ln in sorted(region_ocr(img, box), key=lambda l: (l["box"][1], l["box"][0])):
                    cell["parts"].append({"box": [int(v) for v in ln["box"]], "text": ln["text"], "certain": ln.get("conf", 1.0) >= 0.5, "by": "lines"})
            else:
                res = known.get(tuple(box)) if not crossed else None
                res = reader.check(dict(res), crop_of(img, box, dpi)) if res is not None else reader.read(crop_of(img, box, dpi))
                if res["text"]:
                    cell["parts"].append({**res, "box": box, "cell": cell["cell"]})
    if post is not None:
        post([p for c in out for p in c["parts"]])
    for cell in out:
        if cell["parts"]:
            cell["text"] = " ".join(p["text"] for p in cell["parts"])
            cell["certain"] = all(p["certain"] for p in cell["parts"])
    rows = to_rows(out, dpi)
    filled = [c for c in out if c["text"] and c.get("by") != "shape"]
    review = [c["text"] for c in filled if not c["certain"]]
    return {"rows": rows, "review": review, "items": len(filled), "cells": len(cells), "struck_lines": bool(strike.any())}


def to_rows(cells: list[dict], dpi: int = 300) -> list[list[dict]]:
    """セルを行ごとに並べる。行は上端がそろうセルの集まり。

    上の行から続くセルは {"ditto": 元のセルに文字があるか, "cell": 範囲} として入れる。
    """
    tol = 0.04 * dpi
    tops: list[float] = []
    for c in sorted(cells, key=lambda c: c["cell"][1]):
        if not tops or c["cell"][1] - tops[-1] > tol:
            tops.append(c["cell"][1])
    rows = []
    for i, top in enumerate(tops):
        nxt = tops[i + 1] if i + 1 < len(tops) else float("inf")
        row = []
        for c in cells:
            x0, y0, x1, y1 = c["cell"]
            if abs(y0 - top) <= tol:
                row.append(c)
            elif y0 < top - tol and y1 - top > (0.5 * (nxt - top) if nxt != float("inf") else tol):
                row.append({"ditto": bool(c["text"]), "cell": c["cell"]})  # 上の行から続いているセル
        rows.append(sorted(row, key=lambda c: c["cell"][0]))
    # 文字が 1 つもない行 (空の表の行など) も、列の並びを示すために残す。ただし、すべて「〃」の行は出さない
    return [r for r in rows if any("ditto" not in c for c in r)]


def show(cell: dict) -> str:
    if "ditto" in cell:
        return DITTO if cell["ditto"] else ""
    return escape(cell["text"]) + ("" if cell["certain"] else " (?)")


def to_markdown(rows: list[list[dict]]) -> str:
    """行ごとに、セルを ` | ` で並べる。空のセルも区切りを出す。末尾に続く空のセルは省く。"""
    lines = []
    for r in rows:
        texts = [show(c) for c in r]
        while texts and not texts[-1]:
            texts.pop()
        if texts:
            lines.append(" | ".join(texts))
    return "```text\n" + "\n".join(lines) + "\n```"
