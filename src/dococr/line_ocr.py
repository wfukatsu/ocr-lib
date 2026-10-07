"""ページ画像を行単位で OCR する (NDLOCR-Lite の行検出と文字認識)。

行検出は入力の切り方で結果が大きく変わり、ページによってはほとんど行を返さない。
読めた割合が低いページは、帯状と格子状に分割して読み直し、結果を合わせる。
"""
from __future__ import annotations

import re

import cv2
import numpy as np

from .config import MIN_INK_COVERED

TILE = 2600  # NDLOCR-Lite の行検出は 1024px に縮小して動くので、大きい領域は分割する
OVERLAP = 240
PAD = 12  # 領域の外側に足す余白 (px)
CANVAS = 1400  # 小さい領域はこの大きさの白地に置く (行検出が領域を 1024px に拡大してしまうのを防ぐ)


def is_garbage(text: str) -> bool:
    """行検出が崩壊したときや、図の線を文字として読んだときに出る、意味のない繰り返しを捨てる。

    - 英単語の繰り返し (「CON TO CON TO CON …」)
    - 括弧の繰り返し (「( ) ( ) (1) (1) …」)
    - 同じ文字の長い連続 (「0000000000…」)
    """
    if len(text) < 30:
        return False
    if re.search(r"(\S)\1{29,}", text) or (len(re.findall(r"[()]", text)) >= 10 and re.fullmatch(r"[\s()\d\-]+", text)):
        return True
    words = re.findall(r"[A-Za-z]+", text)
    if len(words) < 8:
        return False
    ascii_ratio = sum(c.isascii() for c in text) / len(text)
    return ascii_ratio > 0.9 and len(set(w.lower() for w in words)) / len(words) <= 0.5


def overlap(a, b) -> float:
    """a と b の重なりが a の面積に占める割合。"""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy / ((a[2] - a[0]) * (a[3] - a[1]) or 1)


def ink_covered(page_img: np.ndarray, lines: list[dict], figures: list[tuple] = (), dpi: float = 300) -> float | None:
    """文字領域のインクのうち、OCR の行の中に入っている割合。低ければ読めていない領域がある。

    図・写真と判定された領域 (figures) のインクと、罫線・枠線のインクは数えない。
    ページのインクのほとんどが図なら、判定できないので None を返す。
    """
    dark = page_img.mean(axis=2) < 140
    all_ink = int(dark.sum())
    # 文字の画より長い直線は罫線・枠線。帳票では罫線がインクの半分以上を占め、読めていても割合が下がる
    d8 = dark.astype(np.uint8)
    rules = cv2.morphologyEx(d8, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (round(0.27 * dpi), 1))) | cv2.morphologyEx(d8, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, round(0.25 * dpi))))
    dark &= cv2.dilate(rules, np.ones((3, 3), np.uint8)) == 0
    for x0, y0, x1, y1 in figures:
        dark[max(0, y0) : y1, max(0, x0) : x1] = False
    total = int(dark.sum())
    if all_ink == 0:
        return 1.0
    if total < 0.05 * all_ink:
        return None
    mask = np.zeros(dark.shape, dtype=bool)
    for ln in lines:
        x0, y0, x1, y1 = ln["box"]
        mask[max(0, y0 - 4) : y1 + 4, max(0, x0 - 4) : x1 + 4] = True
    return float((dark & mask).sum()) / total


def iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]) or 1) if inter else 0.0


class PageLineOcr:
    def __init__(self, ndlocr_src: str):
        from . import ndl

        self.ndl, self.det, self.rec30, self.rec50, self.rec100 = ndl.load(ndlocr_src)
        self.garbage = 0  # 行検出の崩壊で捨てた行の数

    def ocr_array(self, img: np.ndarray, ox: int, oy: int) -> list[dict]:
        """img (RGB) を OCR し、ページ画像座標の行リストを返す。"""
        if img.shape[0] < 16 or img.shape[1] < 16 or (img.mean(axis=2) < 140).mean() < 0.002:
            return []
        h, w = img.shape[:2]
        # 行検出は入力を正方形 1024px に変形するので、小さい領域や細長い領域は白地の正方形に置いて縮尺と縦横比を保つ
        if h < CANVAS or w < CANVAS or max(h, w) / min(h, w) > 1.6:
            side = max(h + 80, w + 80, CANVAS)
            canvas = np.full((side, side, 3), 255, dtype=np.uint8)
            canvas[40 : 40 + h, 40 : 40 + w] = img
            img, ox, oy = canvas, ox - 40, oy - 40
        res = self.ndl._run_ocr_on_image_array(self.det, self.rec30, self.rec50, self.rec100, "region.png", img, "", False)
        lines = []
        for ln in res["json_lines"]:
            text = ln["text"].strip()
            (x0, y0), _, _, (x1, y1) = ln["boundingBox"]
            if not text or x1 <= x0 or y1 <= y0:
                continue
            if is_garbage(text):
                self.garbage += 1
                continue
            lines.append({"box": (x0 + ox, y0 + oy, x1 + ox, y1 + oy), "text": text, "conf": float(ln["confidence"])})
        return lines

    def read_strip(self, page_img: np.ndarray, box) -> str:
        """1 行の一部の範囲を、行検出を通さずに文字認識にかける。"""
        x0, y0, x1, y1 = (max(int(v), 0) for v in box)
        crop = page_img[y0:y1, x0:x1]
        if crop.shape[0] < 8 or crop.shape[1] < 8:
            return ""
        ratio = crop.shape[1] / crop.shape[0]
        rec = self.rec30 if ratio < 9 else self.rec50 if ratio < 14 else self.rec100
        return rec.read(crop).strip()

    def ocr_region(self, page_img: np.ndarray, box, tile_h: int = int(TILE * 1.5), tile_w: int | None = None) -> list[dict]:
        H, W = page_img.shape[:2]
        x0, y0, x1, y1 = max(0, box[0] - PAD), max(0, box[1] - PAD), min(W, box[2] + PAD), min(H, box[3] + PAD)
        # 横方向は行を途中で切らないよう、A3 相当までは分割しない
        if tile_w is None:
            tile_w = (x1 - x0) if x1 - x0 <= 5200 else TILE
        if x1 - x0 <= tile_w and y1 - y0 <= tile_h:
            return self.ocr_array(page_img[y0:y1, x0:x1], x0, y0)
        out: list[dict] = []
        for ty in range(y0, max(y1 - OVERLAP, y0 + 1), tile_h - OVERLAP):
            for tx in range(x0, max(x1 - OVERLAP, x0 + 1), max(tile_w - OVERLAP, 1)):
                for ln in self.ocr_array(page_img[ty : min(ty + tile_h, y1), tx : min(tx + tile_w, x1)], tx, ty):
                    dup = next((o for o in out if iou(o["box"], ln["box"]) > 0.5), None)
                    if dup is None:
                        out.append(ln)
                    elif len(ln["text"]) > len(dup["text"]):
                        dup.update(ln)
        return out

    def read_page(self, page_img: np.ndarray, dpi: float = 300, figures: list[tuple] = ()) -> tuple[list[dict], bool]:
        """ページ全体を読み、(行, 行検出が崩壊したか) を返す。figures は図・写真と判定された領域。"""
        H, W = page_img.shape[:2]
        g0 = self.garbage
        lines = self.ocr_region(page_img, (0, 0, W, H))
        collapsed = self.garbage > g0
        score = lambda ls: sum(len(l["text"]) * l["conf"] for l in ls)
        covered = ink_covered(page_img, lines, figures, dpi)
        if covered is None:  # 図面のようにページのほとんどが図の場合は、図も含めた割合で判断する
            covered = ink_covered(page_img, lines, dpi=dpi)
        # 罫線だけのページ (空欄の帳票) は、図を含めても割合を出せない。読むべき文字がないので読み直さない
        if collapsed or (covered is not None and covered < MIN_INK_COVERED):
            # 帯状と格子状に分割して読み直し、結果を合わせる
            strips = self.ocr_region(page_img, (0, 0, W, H), tile_h=round(4.3 * dpi))
            tiles = self.ocr_region(page_img, (0, 0, W, H), tile_h=H // 2 + OVERLAP, tile_w=W // 2 + OVERLAP)
            sets = sorted(([] if collapsed else [lines]) + [strips, tiles], key=score, reverse=True)
            lines = list(sets[0])
            for extra in sets[1:]:  # 既にある行と重ならない行だけを足す
                lines += [e for e in extra if not any(overlap(e["box"], l["box"]) > 0.3 for l in lines)]
        return lines, collapsed
