import numpy as np
from PIL import Image, ImageDraw, ImageFont

from dococr import form_cells as fc


def form():
    """3 行 × 2 列の罫線の表。2 行目の右のセルは、罫線なしで 2 つの値が離れて並ぶ。"""
    img = Image.new("RGB", (1200, 500), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=36)
    for y in (50, 150, 250, 350):
        d.line((50, y, 1150, y), fill="black", width=3)
    for x in (50, 400, 1150):
        d.line((x, 50, x, 350), fill="black", width=3)
    d.text((70, 80), "TYPE", font=font, fill="black")
    d.text((420, 80), "KX416-2", font=font, fill="black")
    d.text((70, 180), "FLOW", font=font, fill="black")
    d.text((420, 180), "6", font=font, fill="black")
    d.text((800, 180), "R55071", font=font, fill="black")
    d.text((70, 280), "S P A C E D", font=font, fill="black")
    return np.array(img)


class FakeReader:
    """文字認識の代わりに、切り出した範囲の幅を返す。"""

    def read(self, crop):
        return {"text": f"w{crop.shape[1] // 50}", "certain": True, "ndl": "", "alt": None}


def test_find_cells():
    cells, grid = fc.find_cells(form())
    assert len(cells) == 6
    assert sorted({x for x, *_ in cells})[0] > 50 and grid.any()


def test_rows_follow_the_ruled_cells_and_wide_gaps_split_a_cell():
    rows = fc.read_form(form(), FakeReader())
    assert [len(r) for r in rows] == [2, 3, 1]  # 2 行目の右のセルは 2 つの値に分かれ、字間の広い見出しは分かれない
    assert rows[1][0]["cell"] != rows[1][1]["cell"] and rows[1][1]["cell"] == rows[1][2]["cell"]
    assert rows[0][0]["box"][0] < rows[0][1]["box"][0]


def test_text_boxes_ignore_specks():
    ink = np.zeros((60, 300), dtype=np.uint8)
    ink[10:40, 20:120] = 1
    ink[50:52, 200:210] = 1  # 罫線の欠片のような小さな汚れ
    assert fc.text_boxes(ink) == [(20, 10, 120, 40)]


def test_markdown_marks_uncertain_values():
    rows = [[{"text": "流量", "certain": True, "box": [0, 0, 1, 1]}, {"text": "6", "certain": False, "box": [2, 0, 3, 1]}]]
    assert fc.to_markdown(rows) == "```text\n流量 | 6 (?)\n```"


def test_is_form():
    assert not fc.is_form(form())  # セルが少ない表は帳票とみなさない
    assert not fc.is_form(np.full((500, 500, 3), 255, dtype=np.uint8))
