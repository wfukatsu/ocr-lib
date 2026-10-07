"""テキスト層のある PDF から、取り消し線付きの文字列を抽出する。

PDF には取り消し線という文字書式がなく、文字の上に引かれた線や注釈として表現される。
そのため、水平線の位置と文字の位置を照合して対象を推定する。
"""
from __future__ import annotations

from pathlib import Path

import pdfplumber

from .mdutil import STRIKE, UNCERTAIN, Seg, render

# 線が文字の高さのどこを通るか (0 = 上端, 1 = 下端)
SURE_BAND = (0.25, 0.75)  # この範囲を横切れば取り消し線とみなす
MAYBE_BAND = (0.12, 0.88)  # ここまでは要確認。これより外は下線・罫線
SURE_COVER = 0.5  # 文字幅のうち線が重なる割合
MAYBE_COVER = 0.2


def _hsegments(page) -> list[dict]:
    """ページ内の水平線を (x0, x1, y, thickness, source) で集める。y は上端からの距離。"""
    segs = []
    for ln in page.lines:
        if abs(ln["top"] - ln["bottom"]) <= 1.5 and ln["x1"] - ln["x0"] >= 2:
            segs.append({"x0": ln["x0"], "x1": ln["x1"], "y": (ln["top"] + ln["bottom"]) / 2, "t": ln.get("linewidth") or 0.5, "src": "line"})
    for rc in page.rects:  # 細い塗りつぶし矩形として描かれた線
        if rc["bottom"] - rc["top"] <= 2 and rc["x1"] - rc["x0"] >= 2:
            segs.append({"x0": rc["x0"], "x1": rc["x1"], "y": (rc["top"] + rc["bottom"]) / 2, "t": rc["bottom"] - rc["top"], "src": "rect"})
    for an in page.annots:
        if (an.get("data") or {}).get("Subtype") is not None and str(an["data"]["Subtype"]).strip("/'") == "StrikeOut":
            segs.append({"x0": an["x0"], "x1": an["x1"], "y": (an["top"] + an["bottom"]) / 2, "t": 0.5, "src": "annot"})
    return segs


def _classify(ch: dict, segs: list[dict]) -> str | None:
    h, w = ch["bottom"] - ch["top"], ch["x1"] - ch["x0"]
    if h <= 0 or w <= 0:
        return None
    best = None
    for s in segs:
        cover = (min(ch["x1"], s["x1"]) - max(ch["x0"], s["x0"])) / w
        rel = (s["y"] - ch["top"]) / h
        if s["src"] == "annot":  # 注釈は対象範囲が明示されている
            if cover >= SURE_COVER and 0 <= rel <= 1:
                return STRIKE
            continue
        if cover >= SURE_COVER and SURE_BAND[0] <= rel <= SURE_BAND[1]:
            return STRIKE
        if cover >= MAYBE_COVER and MAYBE_BAND[0] <= rel <= MAYBE_BAND[1]:
            best = UNCERTAIN
    return best


def _line_segs(chars: list[dict], segs: list[dict]) -> list[Seg]:
    out: list[Seg] = []
    prev = None
    for ch in chars:
        kind = None if ch["text"].isspace() else _classify(ch, segs)
        if prev is not None and ch["x0"] - prev["x1"] > 0.2 * ch.get("size", 10) and not ch["text"].isspace() and not prev["text"].isspace():
            out.append(Seg(" ", kind if out and out[-1].kind == kind else None))
        if ch["text"].isspace() and out:
            kind = out[-1].kind  # 取り消し線付き文字列の間の空白は、前の文字に合わせる
        out.append(Seg(ch["text"], kind))
        prev = ch
    # 末尾の空白は取り消し範囲に含めない
    while out and out[-1].text.isspace():
        out.pop()
    return out


def has_text_layer(path: str | Path, pages: int = 3) -> bool:
    with pdfplumber.open(path) as pdf:
        return any(len(p.chars) > 20 for p in pdf.pages[:pages])


def extract(path: str | Path) -> tuple[str, list[dict]]:
    """(Markdown, 取り消し線と要確認箇所の一覧) を返す。"""
    md: list[str] = ["<!-- 取り消し線は、線と文字の座標の重なりから推定したもの -->"]
    found: list[dict] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            segs = _hsegments(page)
            lines = page.extract_text_lines(layout=False, strip=False, return_chars=True)
            body, review = [], []
            for ln in lines:
                lsegs = _line_segs(ln["chars"], segs)
                body.append(render(lsegs))
                buf, kind = "", None
                for s in [*lsegs, Seg("", "__end__")]:
                    if s.kind != kind:
                        if kind in (STRIKE, UNCERTAIN) and buf.strip():
                            found.append({"page": page.page_number, "kind": kind, "text": buf.strip(), "certain": kind == STRIKE})
                            if kind == UNCERTAIN:
                                review.append(buf.strip())
                        buf, kind = "", s.kind
                    buf += s.text
            md.append(f"<!-- p.{page.page_number} -->")
            md.append("\n".join(body))
            if review:
                md.append(f"<!-- 要確認 p.{page.page_number}: 線と文字列の対応が曖昧: " + " / ".join(review) + " -->")
    return "\n\n".join(md) + "\n", found
