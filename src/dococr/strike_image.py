"""スキャン画像から取り消し線を検出する。

スキャン PDF では取り消し線は画像のピクセルでしかないので、ページ画像から長い横線を探し、
文字を横切っているものを取り消し線の候補にする。候補は OCR の前に消しておく
(線が残っていると行検出が崩壊する)。OCR 後に行の位置と照合して確定する。
"""
from __future__ import annotations

import difflib
import unicodedata

import cv2
import numpy as np

from .mdutil import escape

DARK = 150  # これより暗い画素をインクとみなす
MIN_THROUGH = 0.2  # 表の中の線を取り消し線とみなすのに要る、線の上下に文字の画が続く列の割合


def detect(img: np.ndarray, dpi: int = 300) -> list[dict]:
    """文字を横切る横線を返す。座標は画素 (x, y, w, h)。

    次のものは除く。
    - 下線 (下側に文字がない)、枠線 (上下どちらかに文字がない)
    - 表の罫線 (文字より高い縦線につながっている)
    - 大きな文字の横画 (周りの文字の高さに比べて短い)
    """
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    bw = (gray < DARK).astype(np.uint8)
    min_len = int(0.33 * dpi)  # 約 8mm (2 文字強)。文字の横画や短い罫を拾わない長さ
    max_thick = int(0.047 * dpi)  # 二重取り消し線まで
    reach = int(0.04 * dpi)  # 線の上下を調べる範囲
    # スキャンの傾きを許すため、縦に少し膨らませてから横長の形だけを残す
    dil = cv2.dilate(bw, np.ones((3, 1), np.uint8))
    horiz = cv2.morphologyEx(dil, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (min_len, 1)))
    # 文字より高い縦線は、表や枠の罫線とみなす
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(0.25 * dpi))))
    vert = cv2.dilate(vert, np.ones((3, 1), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(horiz, 8)
    out = []
    for x, y, w, h, _ in stats[1:n]:
        if w < min_len or h > max_thick or y < reach:
            continue
        up = bw[y - reach : y - 2, x : x + w].any(axis=0).mean()
        dn = bw[y + h + 2 : y + h + reach, x : x + w].any(axis=0).mean()
        if not (up > 0.2 and dn > 0.2):  # 線の上下両方に文字のインクがあること
            continue
        # 縦の罫線につながっていれば表の罫線。枠のすぐ内側で終わる取り消し線を除かないよう、接しているものだけを見る
        if vert[y : y + h, max(x - 2, 0) : x + w + 2].any():
            continue
        if w < 2.0 * _text_height(bw, x, y, w, h, dpi):  # 文字 2 つ分に満たない線は、大きな文字の横画
            continue
        out.append({"x": int(x), "y": int(y), "w": int(w), "h": int(h), "through": round(_through(bw, x, y, w, h), 2)})
    return out


def _through(bw: np.ndarray, x: int, y: int, w: int, h: int) -> float:
    """線のすぐ上とすぐ下の両方にインクがある列の割合のうち、小さい方。

    文字を横切る線では、文字の画が線の上下に続く。文字に近いだけの罫線では、片側が空く。
    """
    near = 5
    up = bw[max(y - near, 0) : max(y - 1, 0), x : x + w].any(axis=0).mean() if y > 1 else 0.0
    dn = bw[y + h + 1 : y + h + near, x : x + w].any(axis=0).mean()
    return float(min(up, dn))


def _text_height(bw: np.ndarray, x: int, y: int, w: int, h: int, dpi: int) -> int:
    """線の周りの文字の高さ。線の上下に、インクのある行がどこまで続くかで測る。"""
    win = int(0.7 * dpi)
    top = max(y - win, 0)
    rows = bw[top : y + h + win, x : x + w].any(axis=1)
    a = y - top
    while a > 0 and (rows[a - 1] or (a > 1 and rows[a - 2])):
        a -= 1
    b = y - top + h
    while b < len(rows) and (rows[b] or (b + 1 < len(rows) and rows[b + 1])):
        b += 1
    return b - a


def erase(img: np.ndarray, strikes: list[dict]) -> np.ndarray:
    """取り消し線を消した画像を返す。文字の縦画が線を横切っている列は残し、文字を削らない。"""
    out = img.copy()
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    bw = gray < DARK
    for s in strikes:
        x, y, w, h = s["x"], s["y"], s["w"], s["h"]
        up = bw[max(y - 3, 0) : max(y - 1, 0), x : x + w].any(axis=0)
        dn = bw[y + h + 1 : y + h + 3, x : x + w].any(axis=0)
        band = out[max(y - 1, 0) : y + h + 1, x : x + w]
        band[:, ~(up & dn)] = 255
    return out


def _locate(text: str, part: str) -> tuple[int, int, bool] | None:
    """行の文字列 text の中で、線の範囲だけを読み直した文字列 part が当たる範囲 (開始, 終了, 確かか) を返す。

    空白は比べない (行と、切り出した範囲とで、空白の読み方が変わる)。part が 1 か所だけにそのまま
    現れれば確か。そうでなければ、最も長く一致する箇所から範囲を決め、確かではないとする。
    """
    idx = [i for i, ch in enumerate(text) if not ch.isspace()]  # 空白を除いた文字の、元の位置
    flat, part = "".join(text[i] for i in idx), "".join(part.split())
    if not part or not flat:
        return None
    k = flat.find(part)
    if k >= 0 and flat.find(part, k + 1) < 0:
        return idx[k], idx[k + len(part) - 1] + 1, True
    m = difflib.SequenceMatcher(None, flat, part, autojunk=False).find_longest_match(0, len(flat), 0, len(part))
    if m.size < max(2, 0.6 * len(part)):
        return None
    a, b = max(m.a - m.b, 0), min(m.a - m.b + len(part), len(flat))
    return idx[a], idx[b - 1] + 1, False


def _by_width(text: str, x0: float, x1: float, a: float, b: float) -> tuple[int, int]:
    """線の位置 (a, b) から文字の範囲を按分する。半角の文字は、全角の半分の幅として数える。"""
    widths = [1.0 if unicodedata.east_asian_width(ch) in "FWA" else 0.5 for ch in text]
    unit = (x1 - x0) / sum(widths)
    edges = [x0]
    for w in widths:
        edges.append(edges[-1] + w * unit)
    nearest = lambda x: min(range(len(edges)), key=lambda i: abs(edges[i] - x))
    return nearest(a), nearest(b)


def mark_lines(lines: list[dict], strikes: list[dict], reread=None) -> list[dict]:
    """OCR の行 (box = x0, y0, x1, y1) と取り消し線を照合し、要確認の一覧を返す。

    行には ``struck`` ("all" / "part" / None) と Markdown 化した ``md`` を書き込む。
    行の幅のほぼ全体を線が通っていれば行全体を取り消しとする。一部だけなら、線の範囲の文字を決めて
    ``~~`` を付ける。reread(box) は、指定した範囲だけを文字認識にかけて文字列を返す関数。線の範囲を
    読み直した文字列が、行の中の 1 か所にそのまま現れれば、その範囲で確定する。reread がないか、
    一致しなければ、線の位置から範囲を按分で推定し、推定であることを要確認として返す。
    どの行にも対応しない線も要確認として返す。

    行には ``strike_fits`` (線が、この行の文字だけを横切っているか) も書き込む。罫線は、行の幅を
    越えて続くか、文字の上下どちらかに寄っている。
    """
    review: list[dict] = []
    used = set()
    for ln in lines:
        x0, y0, x1, y1 = ln["box"]
        h, w = y1 - y0, x1 - x0
        text = ln["text"]
        ln["struck"], ln["md"] = None, escape(text)
        if h <= 0 or w <= 0 or not text:
            continue
        spans, fits = [], True
        for i, s in enumerate(strikes):
            cy = s["y"] + s["h"] / 2
            if y0 + 0.2 * h <= cy <= y0 + 0.8 * h and min(x1, s["x"] + s["w"]) - max(x0, s["x"]) > 0:
                spans.append((max(x0, s["x"]), min(x1, s["x"] + s["w"])))
                used.add(i)
                fits &= s.get("through", 0.0) >= MIN_THROUGH and y0 + 0.3 * h <= cy <= y0 + 0.7 * h and x0 - h <= s["x"] and s["x"] + s["w"] <= x1 + h
        if not spans:
            continue
        ln["strike_fits"] = fits
        a, b = min(p[0] for p in spans), max(p[1] for p in spans)
        cover = sum(q - p for p, q in spans) / w
        if cover >= 0.8:
            ln["struck"], ln["md"] = "all", f"~~{escape(text)}~~"
        elif cover >= 0.15:
            pad = max(2, round(0.08 * h))
            found = _locate(text, reread((a - pad, y0, b + pad, y1))) if reread and len(spans) == 1 else None
            if found:
                i0, i1, sure = found
                reason = "行の一部に取り消し線。範囲は、線の範囲を読み直した文字列との照合による推定"
            else:
                # 文字ごとの座標がないので、行の幅に対する線の位置から文字の範囲を按分する
                (i0, i1), sure = _by_width(text, x0, x1, a, b), False
                reason = "行の一部に取り消し線。範囲は位置からの推定"
            if i1 > i0:
                ln["struck"] = "part"
                ln["md"] = escape(text[:i0]) + f"~~{escape(text[i0:i1])}~~" + escape(text[i1:])
                if not sure:
                    review.append({"reason": reason, "text": text, "candidate": text[i0:i1], "box": list(ln["box"])})
    for i, s in enumerate(strikes):
        if i not in used:
            review.append({"reason": "取り消し線らしい線があるが、対応する行がない", "text": "", "candidate": "", "box": [s["x"], s["y"], s["x"] + s["w"], s["y"] + s["h"]]})
    return review


def demote_in_regions(lines: list[dict], regions: list[tuple], review: list[dict], tables: list[tuple] = ()) -> int:
    """表・図・帳票と判定された領域の中の取り消しを、確定から要確認に下げる。下げた数を返す。

    こうした領域では、文字に近い罫線や写真の縁が取り消し線の条件を満たすことがある。
    tables (表の領域) の中では、線がその行の文字だけを横切っている (``strike_fits``) ものは下げない。
    セルの中の取り消し線は、罫線と違って、文字の画の上下にまたがり、セルの文字の幅に収まる。
    """
    inside = lambda ln, boxes: any(x0 <= (ln["box"][0] + ln["box"][2]) / 2 <= x1 and y0 <= (ln["box"][1] + ln["box"][3]) / 2 <= y1 for x0, y0, x1, y1 in boxes)
    n = 0
    for ln in lines:
        if not ln.get("struck"):
            continue
        if ln.get("strike_fits") and inside(ln, tables) and not inside(ln, [r for r in regions if r not in tables]):
            continue
        if inside(ln, regions):
            review.append({"reason": "表・図の中の線。罫線の可能性があるため確定しない", "text": ln["text"], "candidate": ln["text"], "box": list(ln["box"])})
            ln["struck"], ln["md"] = None, escape(ln["text"])
            n += 1
    return n
