import numpy as np
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from dococr import route

TEXT = "This page has a real text layer that can be used as it is. " * 3


def pdf(tmp_path, draw, name="t.pdf", pages=1):
    path = tmp_path / name
    c = canvas.Canvas(str(path), pagesize=(400, 300))
    for _ in range(pages):
        c.setFont("Helvetica", 9)
        draw(c)
        c.showPage()
    c.save()
    return path


def scan(c, w=400, h=300, x=0, y=0):
    img = Image.fromarray(np.full((60, 80, 3), 230, dtype=np.uint8))
    c.drawImage(ImageReader(img), x, y, width=w, height=h)


def invisible(c, text, x=20, y=250):
    t = c.beginText(x, y)
    t.setTextRenderMode(3)  # OCR ソフトが重ねる不可視テキスト
    t.textLine(text)
    c.drawText(t)


def test_text_layer_is_used(tmp_path):
    assert route.classify(pdf(tmp_path, lambda c: c.drawString(20, 250, TEXT)))["kind"] == route.TEXT


def test_no_text_layer(tmp_path):
    assert route.classify(pdf(tmp_path, scan))["kind"] == route.IMAGE


def test_ocr_text_over_full_page_scan(tmp_path):
    def draw(c):
        scan(c)
        invisible(c, TEXT)

    assert route.classify(pdf(tmp_path, draw))["kind"] == route.OCR_LAYER


def test_title_text_over_image_body_is_image(tmp_path):
    def draw(c):
        scan(c, w=360, h=200, x=20, y=20)
        c.drawString(20, 270, "Good example (2/5)  2023.4")

    assert route.classify(pdf(tmp_path, draw))["kind"] == route.IMAGE


def test_garbled_characters():
    assert route._is_garbled_char("(cid:3)") and route._is_garbled_char("Þ") and route._is_garbled_char("")
    assert not route._is_garbled_char("注") and not route._is_garbled_char("A")


def test_garbled_page(tmp_path):
    class Page:
        width, height, images = 400, 300, []
        chars = [{"text": "(cid:3)"}] * 30 + [{"text": "A"}] * 30

    assert route.classify_page(Page) == route.GARBLED


def test_mixed_document_goes_to_ocr_when_enough_pages_need_it(tmp_path):
    n = {"i": 0}

    def draw(c):
        n["i"] += 1
        scan(c) if n["i"] <= 2 else c.drawString(20, 250, TEXT)

    info = route.classify(pdf(tmp_path, draw, pages=5))
    assert info["kind"] == route.IMAGE and info["page_kinds"] == {route.IMAGE: 2, route.TEXT: 3} and info["ocr_pages"] == [1, 2]


def test_scanned_pages_in_a_long_text_document_are_listed_for_ocr(tmp_path):
    n = {"i": 0}

    def draw(c):
        n["i"] += 1
        scan(c) if n["i"] in (13, 31, 32) else c.drawString(20, 250, TEXT)

    # 抜き取りでは見つからない位置のページも挙げる。文書全体はテキスト層を使う
    info = route.classify(pdf(tmp_path, draw, pages=35))
    assert info["kind"] == route.TEXT and info["pages"] == 35 and info["ocr_pages"] == [13, 31, 32] and info["page_kinds"] == {route.TEXT: 32, route.IMAGE: 3}


def test_is_image_file():
    assert route.is_image_file("a.PNG") and route.is_image_file("a.tif") and not route.is_image_file("a.pdf")
