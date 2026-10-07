"""罫線のある帳票を、セル単位で読む (項目と値が並ぶ台帳など)。

表の構造を推定せず、罫線からセルを切り出す。文字は行検出を通さず、セル内の文字の行を
そのまま文字認識にかける。
"""
from __future__ import annotations

import cv2
import numpy as np

from .mdutil import escape
from .textutil import group_rows

DARK = 160  # 文字のインク
LINE_DARK = 215  # 罫線は薄いことがあるので緩く拾う


def find_cells(img: np.ndarray, dpi: int = 300, min_fill: float = 0.7) -> tuple[list[tuple[int, int, int, int]], np.ndarray]:
    """罫線で囲まれたセル (x, y, w, h) と、罫線のマスクを返す。

    min_fill は、セルの外接矩形のうち白地が占める割合の下限。中に別の枠 (押印欄や表) を含む
    大きな欄も拾うには下げる。
    """
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    lbw = (gray < LINE_DARK).astype(np.uint8)
    H, W = gray.shape
    # 文字の画より長い直線だけを罫線として残す
    hl = cv2.morphologyEx(lbw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (round(0.27 * dpi), 1)))
    vl = cv2.morphologyEx(lbw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, round(0.1 * dpi))))
    grid = cv2.dilate(hl | vl, np.ones((3, 3), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats((1 - grid).astype(np.uint8), 4)
    min_w, min_h = round(0.1 * dpi), round(0.06 * dpi)
    cells = [(int(x), int(y), int(w), int(h)) for x, y, w, h, a in stats[1:n] if w >= min_w and h >= min_h and w * h < 0.3 * W * H and a > min_fill * w * h]
    return cells, grid


def text_boxes(ink: np.ndarray, dpi: int = 300) -> list[tuple[int, int, int, int]]:
    """セル内のインクを、文字の行ごと・大きな空白ごとに分けた範囲 (x0, y0, x1, y1) を返す。"""
    rows = np.where(ink.any(axis=1))[0]
    if rows.size == 0:
        return []
    row_gap, min_h = round(0.017 * dpi), round(0.027 * dpi)
    bands, start, prev = [], rows[0], rows[0]
    for r in rows[1:]:
        if r - prev > row_gap:
            bands.append((start, prev))
            start = r
        prev = r
    bands.append((start, prev))
    out = []
    for a, b in bands:
        if b - a < min_h:
            continue
        cols = np.where(ink[a : b + 1].any(axis=0))[0]
        col_gap = 4.0 * (b - a + 1)  # 文字 4 つ分以上の空白は、罫線のない列の区切りとみなす (字間を空けた見出しは分けない)
        start, prev = cols[0], cols[0]
        for c in cols[1:]:
            if c - prev > col_gap:
                out.append((int(start), int(a), int(prev) + 1, int(b) + 1))
                start = c
            prev = c
        out.append((int(start), int(a), int(prev) + 1, int(b) + 1))
    return out


def crop_of(img: np.ndarray, box, dpi: int = 300) -> np.ndarray:
    """文字の範囲 (x0, y0, x1, y1) に、文字認識用の余白を足して切り出す。"""
    pad = round(0.017 * dpi)
    return img[max(box[1] - pad, 0) : box[3] + pad, max(box[0] - pad, 0) : box[2] + pad]


def read_cells(img: np.ndarray, reader, dpi: int = 300, **kw) -> list[dict]:
    """セル内の文字の行をすべて読み、{"box", "cell", "text", "certain", …} の一覧を返す。読めなかったものも含む。"""
    cells, grid = find_cells(img, dpi)
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    ink = ((gray < DARK) & (grid == 0)).astype(np.uint8)
    out = []
    for x, y, w, h in cells:
        for x0, y0, x1, y1 in text_boxes(ink[y : y + h, x : x + w], dpi):
            box = [x + x0, y + y0, x + x1, y + y1]
            out.append({"box": box, "cell": [x, y, x + w, y + h], **reader.read(crop_of(img, box, dpi), **kw)})
    return out


def to_rows(cells: list[dict]) -> list[list[dict]]:
    """読めたセルを、行ごとの並びにする。"""
    return group_rows([c for c in cells if c["text"]])


def read_form(img: np.ndarray, reader, dpi: int = 300) -> list[list[dict]]:
    """帳票を読み、行ごとのセルの並びを返す。セルは {"box", "text", "certain"}。"""
    return to_rows(read_cells(img, reader, dpi))


def to_markdown(rows: list[list[dict]]) -> str:
    lines = [" | ".join(escape(c["text"]) + ("" if c["certain"] else " (?)") for c in r) for r in rows]
    return "```text\n" + "\n".join(lines) + "\n```"


def is_form(img: np.ndarray, dpi: int = 300) -> bool:
    """罫線のセルがページの広い範囲を占めていれば帳票とみなす。

    セルが極端に多いページ (縮小して綴じ込んだ大きな表) は、セル単位で読んでも判読できないので除く。
    """
    cells, _ = find_cells(img, dpi, min_fill=0.35)
    H, W = img.shape[:2]
    return 20 <= len(cells) <= 400 and sum(w * h for _, _, w, h in cells) >= 0.4 * W * H
