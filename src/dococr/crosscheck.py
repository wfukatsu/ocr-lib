"""複数の OCR エンジンの結果を照合する。

1〜4 文字の値は誤読しやすいので、NDLOCR-Lite に加えて Tesseract でも読む。食い違った値は、
macOS の Vision を 3 つ目として多数決をとる。
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile

import cv2
import numpy as np
from PIL import Image

from . import ndl, textutil

Image.MAX_IMAGE_PIXELS = None
SHORT = 4  # この文字数以下の値は別エンジンと照合する
ASCII_VALUE = re.compile(r"[0-9A-Za-z.,\-+/°℃%()]+")
JAPANESE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
UNITS = {"C", "%", "mm", "A"}  # 照合先だけが読んだ単位


def reconcile(main: str, other: str | None) -> tuple[str, bool]:
    """2 つの OCR 結果から採用する文字列と、確かかどうかを返す。"""
    norm = lambda s: textutil.norm(s).replace("°C", "℃").replace("°", "").replace("℃", "C")
    degree = lambda s: "°" in s or "℃" in s
    if other is None:
        return main, True  # 照合していない
    a, b = norm(main), norm(other)
    if a == b:
        return (other if degree(other) and not degree(main) else main), True  # 度の記号を読めた方を採る
    # 照合先 (Tesseract) は短い日本語を読めないことが多い。その場合は元の結果を採るが、確かめられていないので要確認にする。
    # (「無」を「無異」と読むような誤りが実際にあるので、確定にはしない。3 つ目のエンジンとの多数決で確定させる)
    if not b or (JAPANESE.search(a) and not JAPANESE.search(b)):
        return main, False
    # 数値は同じで、単位の有無だけが違う
    if a and b.startswith(a) and b[len(a) :] in UNITS:
        return other, True
    # 英数字だけの値は Tesseract の方が正確
    if ASCII_VALUE.fullmatch(b) and not JAPANESE.search(a):
        return other, False
    # 一方がもう一方を含む日本語は、長い方を採る (1 文字欠けの補完)
    if JAPANESE.search(a) and JAPANESE.search(b) and a in b:
        return other, False
    return main, False


def tesseract_line(exe: str, crop: np.ndarray) -> str:
    """1 行の画像を Tesseract で読む。"""
    big = cv2.resize(cv2.copyMakeBorder(crop, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255, 255, 255)), None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        Image.fromarray(big).save(f.name)
        res = subprocess.run([exe, f.name, "-", "-l", "jpn+eng", "--psm", "7"], capture_output=True, text=True)
    return res.stdout.strip().replace(" ", "")


def vision_read(img: np.ndarray) -> list[tuple[str, float, tuple[float, float, float, float]]] | None:
    """macOS の Vision でページ全体を読み、(文字列, 信頼度, 画素の範囲) を返す。使えなければ None。"""
    try:
        from ocrmac import ocrmac
    except ImportError:
        return None
    H, W = img.shape[:2]
    out = []
    for text, conf, (x, y, w, h) in ocrmac.OCR(Image.fromarray(img), language_preference=["ja-JP"], recognition_level="accurate").recognize():
        out.append((text, float(conf), (x * W, (1 - y - h) * H, (x + w) * W, (1 - y) * H)))  # Vision の座標は左下が原点
    return out


def vision_lines(img: np.ndarray) -> list[tuple[str, tuple[float, float, float, float]]] | None:
    """macOS の Vision でページ全体を読み、(文字列, 画素の範囲) を返す。使えなければ None。"""
    res = vision_read(img)
    return None if res is None else [(text, box) for text, _, box in res]


def settle(cell: dict, text: str, by: str):
    cell.update(text=text, certain=True, by=by)


def vote(rows: list[list[dict]], lines: list[tuple[str, tuple]]) -> int:
    """食い違ったままの値を、3 つ目のエンジンの結果との多数決で確定させる。確定させた数を返す。"""
    settled = 0
    for r in rows:
        for c in r:
            if c["certain"] or c.get("alt") is None:
                continue
            cx0, cy0, cx1, cy1 = c["cell"]
            # このセルの中にほぼ収まっている Vision の読み取り
            third = {textutil.norm(t) for t, (x0, y0, x1, y1) in lines if (min(x1, cx1) - max(x0, cx0)) > 0.6 * (x1 - x0) and (min(y1, cy1) - max(y0, cy0)) > 0.6 * (y1 - y0)}
            for key in ("ndl", "alt"):
                if c.get(key) and textutil.norm(c[key]) in third:
                    settle(c, c[key], "vote")
                    settled += 1
                    break
            else:
                if third:  # どれとも一致しなければ、候補として残す
                    c["third"] = " / ".join(sorted(third))
    return settled


def settle_with_glossary(res: dict, glossary) -> dict:
    """食い違った 2 つの読みのうち、片方だけが用語集にあれば、それに確定させる。"""
    if glossary is not None and not res["certain"]:
        picked = glossary.pick(res["ndl"], res["alt"])
        if picked is not None:
            settle(res, picked, "glossary")
    return res


class CellReader:
    """行の画像を文字にする。NDLOCR-Lite の認識器を使い、短い値は Tesseract と照合する。"""

    def __init__(self, ndlocr_src: str, cross_check: bool = True, glossary=None):
        self.glossary = glossary  # 用語集。2 つの読みが食い違ったとき、片方だけが用語集にあればそれを採る
        _, _, self.rec30, self.rec50, self.rec100 = ndl.load(ndlocr_src)
        self.tesseract = shutil.which("tesseract") if cross_check else None
        self.short = SHORT

    def read(self, crop: np.ndarray, check: bool = True) -> dict:
        """{"text": 採用した文字列, "certain": 確かか, "ndl": NDLOCR-Lite の結果, "alt": 照合先の結果 (照合していなければ None)}

        check=False は NDLOCR-Lite だけで読む。照合 (行ごとに Tesseract を起動する) は時間がかかるので、
        帳票かどうかを見分ける段階では行わず、帳票と分かってから check() で足す。
        """
        h, w = crop.shape[:2]
        ratio = w / max(h, 1)
        rec = self.rec30 if ratio < 9 else self.rec50 if ratio < 14 else self.rec100
        ndl = rec.read(crop).strip()
        res = {"text": ndl, "certain": True, "ndl": ndl, "alt": None}
        return self.check(res, crop) if check else res

    def check(self, res: dict, crop: np.ndarray) -> dict:
        """read(check=False) の結果のうち短い値を照合先でも読み、採用する読みを決める。res を書き換えて返す。"""
        alt = self.second_opinion(crop) if len(res["ndl"]) <= self.short else None
        text, certain = reconcile(res["ndl"], alt)
        res.update(text=text, certain=certain, alt=alt)
        return settle_with_glossary(res, self.glossary)

    def second_opinion(self, crop: np.ndarray) -> str | None:
        """照合先 (Tesseract) の読み。使えなければ None。"""
        return tesseract_line(self.tesseract, crop) if self.tesseract else None


class ShortLineChecker:
    """行単位の OCR 結果のうち、数字・英数字だけの 1〜4 文字の行を別のエンジンと照合する。"""

    def __init__(self, reader: CellReader, use_vision: bool = True):
        self.reader, self.use_vision = reader, use_vision

    def __call__(self, img: np.ndarray, lines: list[dict]):
        if not self.reader.tesseract:
            return
        for ln in lines:
            # 照合するのは数字・英数字だけの短い行 (金額や数量)。「1式」のような日本語まじりの行は、
            # 照合先が読めずに要確認ばかりになるので対象にしない
            t = textutil.norm(ln["text"])
            if len(ln["text"]) > SHORT or not ASCII_VALUE.fullmatch(t) or not re.search(r"[0-9A-Za-z]", t):  # 「--」のような記号だけの行も除く
                continue
            x0, y0, x1, y1 = ln["box"]
            ln["ndl"], ln["alt"] = ln["text"], self.reader.second_opinion(img[max(y0, 0) : y1, max(x0, 0) : x1])
            ln["text"], ln["certain"] = reconcile(ln["ndl"], ln["alt"])
            settle_with_glossary(ln, self.reader.glossary)
            ln["cell"] = [x0 - 8, y0 - 8, x1 + 8, y1 + 8]  # 多数決で、この行に当たる 3 つ目の読み取りを探す範囲
        third = vision_lines(img) if self.use_vision else None
        if third:
            vote([[l for l in lines if "alt" in l]], third)
