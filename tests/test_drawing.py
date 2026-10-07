import numpy as np

from dococr import drawing, evaluate


def _reader(by_shape):
    """画像の形 (高さ, 幅) ごとに、決まった読み取りを返す。呼ばれた回数も数える。"""
    calls = []

    def read(img):
        calls.append(img.shape[:2])
        return by_shape[len(calls) - 1]

    return read, calls


WIDE = [("薬液タンク 構造図", 0.9, (10, 10, 300, 40)), ("SAMPLE WORKS", 0.8, (10, 60, 200, 90))]
TALL = [("薬液", 0.9, (10, 10, 40, 300))]


def test_is_drawing_when_text_coverage_is_undefined():
    assert drawing.is_drawing({"ink_covered": None}) and not drawing.is_drawing({"ink_covered": 0.9})


def test_read_picks_the_rotation_with_horizontal_text_and_most_characters():
    read, calls = _reader([TALL, WIDE, TALL, WIDE[:1]])
    res = drawing.read(np.zeros((100, 200, 3), np.uint8), read)
    assert len(calls) == 4 and calls[0] == (100, 200) and calls[1] == (200, 100)
    assert res["rotation"] == 90 and [l["text"] for l in res["lines"]] == ["薬液タンク 構造図", "SAMPLE WORKS"]


def test_read_returns_none_without_vision():
    assert drawing.read(np.zeros((10, 10, 3), np.uint8), lambda img: None) is None


def test_markdown_marks_the_reading_as_reference_and_keeps_page_split_intact():
    res = {"rotation": 90, "lines": [{"text": "構造図", "conf": 0.9, "box": [10, 10, 100, 40]}, {"text": "A~~B", "conf": 0.9, "box": [200, 12, 300, 42]}]}
    md = drawing.to_markdown(3, res)
    assert "要確認 p.3" in md and "90 度回して読んだ" in md and "構造図 | A\\~\\~B" in md
    for text in (md, drawing.to_markdown(3, None), drawing.to_markdown(3, {"rotation": 0, "lines": []})):
        # ページの区切りの注記 (<!-- p.N …) と紛れない
        assert list(evaluate.split_pages("<!-- p.3 -->\n\n本文\n\n" + text)) == [3]
    assert "画像のまま扱う" in drawing.to_markdown(3, None)
