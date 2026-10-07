"""チェック欄 (□ / ■) の状態を画像から判定し、OCR の結果と照合する。

仕様書などでは、□ を ■ に置き換えて適用する項目を示す。OCR は □ と ■ を文字として読むが、
行ごと読み落とすことがある。ページ画像から四角を直接探し、次のことを行う。

- OCR が読んだ記号と、画像の四角の塗りつぶしが食い違えば要確認にする
- 四角があるのに OCR の行がない項目は、その行を読み直して補う
"""
from __future__ import annotations

import re

import cv2
import numpy as np

DARK = 150
BOX_CHARS = "□■☐☑☒▢▣◻◼"
CHECKED_CHARS = "■☑☒▣◼"
LEADING_BOX = re.compile(rf"^\s*([{BOX_CHARS}])")
ENCLOSED_KANJI = "国回因団図囲園圏困固圓圖國"  # 外側が四角の漢字。中に画があるので、手書きのチェックが入った四角に見える


def find_boxes(img: np.ndarray, dpi: int = 300) -> list[dict]:
    """文字ほどの大きさの四角を探す。{"box": (x0, y0, x1, y1), "fill": 内側の塗りの割合, "checked": bool | None}

    checked は、塗りつぶされていれば True、中が空なら False、どちらとも言えなければ None
    (手書きのチェックや、かすれた塗りつぶし)。
    """
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    bw = (gray < DARK).astype(np.uint8)
    lo, hi = int(0.07 * dpi), int(0.2 * dpi)  # 8pt〜14pt 程度の文字の大きさ
    n, _, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
    out = []
    for x, y, w, h, area in stats[1:n]:
        if not (lo <= w <= hi and lo <= h <= hi and 0.8 <= w / h <= 1.25):
            continue
        comp = bw[y : y + h, x : x + w]
        t = max(2, round(0.12 * min(w, h)))
        # 四辺に沿ってインクがあること (四角の輪郭)
        edges = [comp[:t].any(axis=0).mean(), comp[-t:].any(axis=0).mean(), comp[:, :t].any(axis=1).mean(), comp[:, -t:].any(axis=1).mean()]
        if min(edges) < 0.85:
            continue
        inner = comp[2 * t : h - 2 * t, 2 * t : w - 2 * t]
        fill = float(inner.mean()) if inner.size else 0.0
        checked = True if fill >= 0.6 else False if fill <= 0.08 else None
        out.append({"box": (int(x), int(y), int(x + w), int(y + h)), "fill": round(fill, 2), "checked": checked})
    return out


def _line_for(box: tuple, lines: list[dict]) -> dict | None:
    """四角を行頭に持つ行。四角の中心が行の高さの中にあり、行の左端の近くにあるもの。"""
    x0, y0, x1, y1 = box
    cy, size = (y0 + y1) / 2, x1 - x0
    best = None
    for ln in lines:
        lx0, ly0, lx1, ly1 = ln["box"]
        if ly0 <= cy <= ly1 and lx0 - 2.5 * size <= x0 <= lx0 + 1.5 * size:
            if best is None or abs(lx0 - x0) < abs(best["box"][0] - x0):
                best = ln
    return best


def process(img: np.ndarray, lines: list[dict], reread=None, dpi: int = 300) -> dict:
    """チェック欄を判定し、行に結果を書き込む。{"items": […], "review": […], "recovered": 補った行の数}

    行には "checkbox" (True / False) を書き込む。reread(img, box) は、指定した範囲を読み直して行を返す関数。
    """
    boxes = find_boxes(img, dpi)
    items, review, recovered = [], [], 0
    xs = []  # 行と対応がついた四角の左端。チェック欄の列の位置
    pending = []
    for b in boxes:
        ln = _line_for(b["box"], lines)
        if ln is None:
            pending.append(b)
            continue
        m = LEADING_BOX.match(ln["text"])
        if m is None:
            size = b["box"][2] - b["box"][0]
            if abs(b["box"][0] - ln["box"][0]) > 0.6 * size:
                continue  # 行頭の四角ではない (文中の記号や、図の一部)
            if b["checked"] is None and ln["text"].lstrip()[:1] in ENCLOSED_KANJI:
                continue  # 四角に見えたのは、行頭の漢字そのもの (「国」など)
            # 四角は行の左端にあるのに、OCR が記号を読み落とした。画像の判定で記号を補う
            ln["text"] = ("■" if b["checked"] else "□") + ln["text"]
            ln["glyph_added"] = True
        xs.append(b["box"][0])
        _judge(ln, b, m.group(1) if m else None, items, review)
    # 四角はあるのに行がない項目。チェック欄の列にそろっているものだけを対象にする
    size_tol = lambda b: 0.6 * (b["box"][2] - b["box"][0])
    for b in pending:
        if not any(abs(b["box"][0] - x) <= size_tol(b) for x in xs):
            continue
        x0, y0, x1, y1 = b["box"]
        h = y1 - y0
        new = reread(img, (x0 - h // 2, y0 - h // 2, img.shape[1] - 1, y1 + h // 2)) if reread else []
        new = [l for l in new if not any(_same(l, o) for o in lines)]
        if new:
            first = min(new, key=lambda l: l["box"][0])
            first["recovered"] = True
            lines.extend(new)
            recovered += 1
            m = LEADING_BOX.match(first["text"])
            _judge(first, b, m.group(1) if m else None, items, review)
        else:
            review.append({"reason": "チェック欄の四角があるが、行を読めていない", "text": "", "box": list(b["box"]), "image_checked": b["checked"]})
    # 画像で四角が見つからなかったが、OCR が行頭に記号を読んだ行
    for ln in lines:
        m = LEADING_BOX.match(ln["text"])
        if m and "checkbox" not in ln:
            ln["checkbox"] = m.group(1) in CHECKED_CHARS
            items.append({"text": ln["text"], "checked": ln["checkbox"], "box": list(ln["box"]), "verified": False})
    return {"items": items, "review": review, "recovered": recovered, "boxes": len(boxes)}


def _same(a: dict, b: dict) -> bool:
    ax0, ay0, ax1, ay1 = a["box"]
    bx0, by0, bx1, by1 = b["box"]
    iy = min(ay1, by1) - max(ay0, by0)
    ix = min(ax1, bx1) - max(ax0, bx0)
    return iy > 0.5 * min(ay1 - ay0, by1 - by0) and ix > 0.5 * min(ax1 - ax0, bx1 - bx0)


def _judge(ln: dict, b: dict, glyph: str | None, items: list, review: list):
    ocr_checked = None if glyph is None else glyph in CHECKED_CHARS
    img_checked = b["checked"]
    if img_checked is None:
        state, ok, reason = ocr_checked, False, "四角の中にインクがあるが、塗りつぶしではない (手書きのチェックの可能性)"
    elif ocr_checked is None:
        state, ok, reason = img_checked, True, ""  # OCR が記号を読めていない行は、画像の判定を採る
    elif ocr_checked != img_checked:
        state, ok, reason = img_checked, False, "OCR が読んだ記号と、画像の四角の塗りが食い違う"
    else:
        state, ok, reason = img_checked, True, ""
    ln["checkbox"] = bool(state)
    items.append({"text": ln["text"], "checked": bool(state), "box": list(ln["box"]), "verified": ok, "fill": b["fill"], **({"recovered": True} if ln.get("recovered") else {})})
    if not ok:
        review.append({"reason": reason, "text": ln["text"], "box": list(ln["box"]), "image_checked": img_checked, "fill": b["fill"]})
