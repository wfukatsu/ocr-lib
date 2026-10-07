"""PDF のテキスト層から、位置の付いた行を取り出す。

テキスト層が信用できる PDF でも、帳票のページは欄ごとに読む必要がある (docling の読み順では、
隣り合う欄の行が混ざる)。文字は OCR せずテキスト層のものを使い、位置だけを帳票の処理に渡す。
"""
from __future__ import annotations

import re
import unicodedata

from .config import DPI

MIN_RULES = 20  # 罫線がこれ未満のページは帳票の候補にしない (画像にして調べる手間を省く)


def ruled(page) -> bool:
    """罫線の多いページか (pdfplumber のページ)。"""
    return len(page.lines) + len(page.rects) >= MIN_RULES


def lines_of(page, dpi: int = DPI) -> list[dict]:
    """ページの文字列を、画像の画素の座標の行 ({"box", "text", "conf", "certain"}) にして返す。"""
    k = dpi / 72
    out = []
    for w in page.extract_words(x_tolerance=2, keep_blank_chars=True):
        text = w["text"].strip()
        if text:
            out.append({"box": [round(w["x0"] * k), round(w["top"] * k), round(w["x1"] * k), round(w["bottom"] * k)], "text": text, "conf": 1.0, "certain": True})
    return out


# ---- 空白の補正

_CJK = re.compile(r"[\u3000-\u30ff\u3400-\u9fff\uf900-\ufaff\uff00-\uffef]")
_MD_PREFIX = re.compile(r"^(\s*(?:#{1,6} |[-*+] (?:\[[ xX]\] )?|\d+\. )*)(.*)$", re.S)


def _key(ch: str) -> str:
    """照合用の 1 文字。全角・半角の違いは比べない。"""
    n = unicodedata.normalize("NFKC", ch)
    return n if len(n) == 1 else ch


class Spacing:
    """テキスト層の文字の並びと、文字の間に空白があるかどうか。

    docling がテキスト層から作る文字列には、文字の間隔や行の折り返しに由来する空白が入ることがある
    (「1 . 1 . 1 適用」、「官庁営 繕」)。pdfplumber で取り出した文字列を基準にして、空白の有無をそろえる。
    行の折り返しは、和文の文字どうしの間なら空白なし、それ以外は空白ありとみなす。
    """

    def __init__(self, text: str):
        chars, space_after = [], []
        gap = None  # 直前の文字との間にあった空白 ("space" / "newline")。改行を含めば "newline"
        for ch in text:
            if ch.isspace():
                gap = "newline" if ch == "\n" or gap == "newline" else "space"
                continue
            if chars and gap:
                wrap = gap == "newline" and _CJK.match(chars[-1]) and _CJK.match(ch)
                space_after[-1] = not wrap
            chars.append(ch)
            space_after.append(False)
            gap = None
        self.key = "".join(_key(c) for c in chars)
        self.space_after = space_after

    def fix(self, text: str) -> str:
        """text の空白を、テキスト層の並びにそろえて返す。テキスト層に同じ並びが見つからなければ、そのまま返す。"""
        chars = [c for c in text if not c.isspace()]
        if len(chars) < 2 or len(chars) == len(text):
            return text
        k = self.key.find("".join(_key(c) for c in chars))
        if k < 0:
            return text
        lead, trail = text[: len(text) - len(text.lstrip())], text[len(text.rstrip()) :]
        return lead + "".join(c + (" " if i + 1 < len(chars) and self.space_after[k + i] else "") for i, c in enumerate(chars)) + trail

    def fix_markdown(self, md: str) -> str:
        """Markdown の行ごとに空白をそろえる。見出しや箇条書きの記号は残し、表はセルごとに扱う。"""
        out = []
        for line in md.split("\n"):
            if line.lstrip().startswith("|"):
                cells = line.split("|")
                # セルの幅は、そろえたままにする
                line = "|".join(c if not c.strip() or set(c.strip()) <= set("-:") else (" " + self.fix(c.strip())).ljust(len(c)) for c in cells)
            elif line.strip():
                prefix, body = _MD_PREFIX.match(line).groups()
                line = prefix + self.fix(body)
            out.append(line)
        return "\n".join(out)
