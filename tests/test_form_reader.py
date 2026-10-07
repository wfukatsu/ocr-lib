import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

pytest.importorskip("pypdfium2")
from dococr import form_reader  # noqa: E402
from helpers import CELL_FORM, FORMS  # noqa: E402


def ruled_page(rows=8, cols=4):
    """罫線の表が全面にあり、どのセルにも文字があるページ。"""
    img = Image.new("RGB", (cols * 400 + 100, rows * 150 + 100), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=36)
    for r in range(rows + 1):
        d.line((50, 50 + r * 150, 50 + cols * 400, 50 + r * 150), fill="black", width=3)
    for c in range(cols + 1):
        d.line((50 + c * 400, 50, 50 + c * 400, 50 + rows * 150), fill="black", width=3)
    for r in range(rows):
        for c in range(cols):
            d.text((90 + c * 400, 100 + r * 150), "TYPE", font=font, fill="black")
    return np.array(img)


class Reader:
    """文字認識の代わりに、決めた順に文字列を返す。照合 (時間のかかる処理) を何回行ったかを数える。"""

    tesseract, glossary = None, None

    def __init__(self, texts):
        self.texts, self.i, self.checked = texts, 0, 0

    def read(self, crop, check=True):
        text = self.texts[self.i % len(self.texts)]
        self.i += 1
        res = {"text": text, "certain": True, "ndl": text, "alt": None}
        return self.check(res, crop) if check else res

    def check(self, res, crop):
        self.checked += 1
        return res


class PageOcr:
    def __init__(self, lines=()):
        self.lines, self.calls = list(lines), 0

    def read_page(self, img, dpi):
        self.calls += 1
        return [dict(l) for l in self.lines], False

    def ocr_region(self, img, box):
        return []


def reader_with(texts, lines=(), grid=False):
    forms = form_reader.FormReader.__new__(form_reader.FormReader)
    forms.glossary, forms._terms, forms.use_vision, forms.grid, forms.forms = None, form_reader.EMPTY_TERMS, False, grid, FORMS
    forms.reader, forms.page_ocr = Reader(texts), PageOcr(lines)
    return forms


def test_page_that_is_no_known_form_is_given_up_without_cross_checking():
    forms = reader_with(["測定値", "12.5", "良", "否"])
    assert forms.read(ruled_page()) is None
    # セルは 1 つのエンジンで 1 度ずつ読むだけ。照合も、欄の読み直しもしない
    assert forms.reader.i == 32 and forms.reader.checked == 0 and forms.page_ocr.calls == 1


def test_known_form_is_cross_checked_after_it_is_recognised():
    forms = reader_with(CELL_FORM["labels"][:16])
    res = forms.read(ruled_page())
    assert res["form"] == "備品台帳" and res["items"] == 32
    assert forms.reader.checked == 32 and forms.page_ocr.calls == 0  # 帳票と分かってから照合する。行単位の OCR は要らない


def test_unknown_form_is_still_read_cell_by_cell_when_the_input_is_known_to_be_a_form():
    forms = reader_with(["測定値", "12.5"])
    res = forms.read(ruled_page(), strict=False)
    assert res["form"] is None and res["items"] == 32 and forms.reader.checked == 32


def test_page_that_is_no_known_form_is_read_as_a_ruled_grid():
    forms = reader_with(["測定値", "12.5", "良", "否"], grid=True)
    res = forms.read(ruled_page())
    assert res["form"] == "罫線の帳票" and res["items"] == 32 and res["markdown"].splitlines()[1] == "測定値 | 12.5 | 良 | 否"
    # 帳票を見分けるときに読んだ結果を使い、文字認識はやり直さない。照合は 1 度ずつ
    assert forms.reader.i == 32 and forms.reader.checked == 32
