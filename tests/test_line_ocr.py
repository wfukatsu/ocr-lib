"""行単位の OCR と共通処理のうち、モデルなしで検証できる部分のテスト。"""
import numpy as np
import pytest

from dococr import line_ocr as dn
from dococr import textutil


def page(boxes, rules=()):
    """boxes の範囲を、文字に見立てた点の集まりで埋める (長い直線にならないようにする)。rules は罫線。"""
    img = np.full((400, 600, 3), 255, dtype=np.uint8)
    dots = (np.indices((400, 600)) // 6 % 2 == 0).all(axis=0)
    for x0, y0, x1, y1 in boxes:
        img[y0:y1, x0:x1][dots[y0:y1, x0:x1]] = 0
    for x0, y0, x1, y1 in rules:
        img[y0:y1, x0:x1] = 0
    return img


def test_ink_covered_counts_ink_inside_lines():
    img = page([(50, 50, 250, 70), (50, 150, 250, 170)])
    assert dn.ink_covered(img, [{"box": (50, 50, 250, 70)}, {"box": (50, 150, 250, 170)}]) == 1.0
    assert dn.ink_covered(img, [{"box": (50, 50, 250, 70)}]) == pytest.approx(0.5, abs=0.1)
    assert dn.ink_covered(page([]), []) == 1.0


def test_ink_covered_ignores_figures_and_gives_up_on_figure_only_pages():
    img = page([(50, 50, 250, 110), (300, 100, 580, 380)])  # 文字の行と、大きな図
    assert dn.ink_covered(img, [{"box": (50, 50, 250, 110)}], figures=[(300, 100, 580, 380)]) == 1.0
    assert dn.ink_covered(img, [{"box": (50, 50, 250, 110)}]) < 0.2
    assert dn.ink_covered(page([(300, 100, 580, 380)]), [], figures=[(290, 90, 590, 390)]) is None


def test_ink_covered_ignores_ruled_lines():
    # 帳票では罫線がインクの多くを占める。罫線は読む対象ではないので数えない
    rules = [(20, 30, 580, 34), (20, 200, 580, 204), (20, 30, 24, 204), (576, 30, 580, 204)]
    img = page([(50, 50, 250, 110)], rules)
    assert dn.ink_covered(img, [{"box": (50, 50, 250, 110)}]) == 1.0
    assert dn.ink_covered(img, []) == 0.0


def test_overlap_and_tile_duplicate_check():
    assert dn.overlap((0, 0, 10, 10), (0, 0, 10, 5)) == 0.5
    assert dn.overlap((0, 0, 10, 10), (20, 20, 30, 30)) == 0
    assert dn.iou((0, 0, 100, 10), (0, 0, 40, 10)) == 1.0  # 短い方がすべて含まれていれば重複とみなす


def test_garbage_from_collapsed_line_detection_is_detected():
    assert dn.is_garbage("the the the the the the the the the and the the the the the")
    assert dn.is_garbage("TOTAL TO TO TO TO TO TO TO THE THE THE TO THE TO TO TO")
    assert not dn.is_garbage("NIKKISO METERING PUMP OUTLINE DRAWING TYPE ABH ABJ ANSI CLASS 150")
    assert not dn.is_garbage("この文書は、サンプル株式会社が管理する設備の点検の手順を示すものである。")
    # 図の線を文字として読んだもの
    assert dn.is_garbage("CON TO CON TO CON TONSTONTERSCON CON PRON PRON INGESTR CON INGESTOR")
    assert dn.is_garbage("( ) ( ( ( ( ( ) ( ) ( ) ( ) (1) (1) (1) (1) 118 (1) 11) 11) 1998)")
    assert dn.is_garbage("00000000000000000000000000000000000000000000")
    # 数字の並ぶ表の行や、括弧のある短い値は捨てない
    assert not dn.is_garbage("25 3 25 3 25 3 25 3 25 3 25 3 25 3 25 3")
    assert not dn.is_garbage("(1) (2) (3)") and not dn.is_garbage("1,000 1,000 1,000 1,000 1,000 1,000 1,000")


def test_join_rows_groups_items_at_the_same_height():
    items = [
        {"box": (300, 100, 360, 120), "md": "240"},
        {"box": (50, 102, 200, 122), "md": "第2塔-A"},
        {"box": (50, 160, 200, 180), "md": "第2塔-B"},
    ]
    assert textutil.join_rows(items, lambda i: i["md"]) == "第2塔-A | 240\n第2塔-B"
    assert [[i["md"] for i in r] for r in textutil.group_rows(items)] == [["第2塔-A", "240"], ["第2塔-B"]]


def test_norm():
    assert textutil.norm("ＡＢ　１ 2") == "AB12" and textutil.norm(None) == ""


def test_page_with_only_ruled_lines_is_not_reread_and_does_not_fail():
    """空欄の帳票は、読めた割合を出せない (インクが罫線だけ)。読むべき文字がないので、そのまま返す。"""

    class Ocr(dn.PageLineOcr):
        def __init__(self):
            self.garbage, self.calls = 0, 0

        def ocr_array(self, img, ox, oy):
            self.calls += 1
            return []

    img = np.full((3000, 2000, 3), 255, np.uint8)
    for y in range(200, 2800, 200):
        img[y : y + 3, 100:1900] = 0
    for x in range(100, 1901, 300):
        img[200:2603, x : x + 3] = 0
    assert dn.ink_covered(img, []) is None
    ocr = Ocr()
    assert ocr.read_page(img, 300) == ([], False) and ocr.calls == 1
