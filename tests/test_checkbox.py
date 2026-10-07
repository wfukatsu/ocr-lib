import numpy as np

from dococr import checkbox

S = 34  # 四角の一辺 (300dpi で 8pt 程度)


def draw_box(img, x, y, kind):
    img[y : y + S, x : x + S] = 0
    if kind != "filled":
        img[y + 3 : y + S - 3, x + 3 : x + S - 3] = 255
    if kind == "ticked":  # 手書きのチェック。四角の中を斜めに横切る
        for i in range(6, S - 6):
            img[y + i - 2 : y + i + 2, x + i - 2 : x + i + 2] = 0


def text(img, x, y, w):
    for i in range(0, w, 40):  # 文字に見立てた、四角ではない塊
        img[y + 4 : y + S - 4, x + i : x + i + 12] = 0
        img[y + 14 : y + 18, x + i : x + i + 28] = 0


def page(kinds, missing_line=None):
    img = np.full((120 + 80 * len(kinds), 1200), 255, dtype=np.uint8)
    lines = []
    for i, kind in enumerate(kinds):
        y = 60 + 80 * i
        draw_box(img, 100, y, kind)
        text(img, 160, y, 600)
        if i != missing_line:
            lines.append({"box": (98, y - 3, 780, y + S + 3), "text": ("■" if kind == "filled" else "□") + f"項目{i}", "conf": 0.9})
    return np.stack([img] * 3, axis=2), lines


def test_find_boxes_tells_filled_from_empty():
    img, _ = page(["filled", "empty", "ticked"])
    boxes = sorted(checkbox.find_boxes(img), key=lambda b: b["box"][1])
    assert [b["checked"] for b in boxes] == [True, False, None]
    assert boxes[0]["box"][:2] == (100, 60)


def test_text_is_not_a_box():
    img = np.full((200, 1200), 255, dtype=np.uint8)
    text(img, 100, 60, 800)
    assert checkbox.find_boxes(np.stack([img] * 3, axis=2)) == []


def test_states_match_the_ocr_glyphs():
    img, lines = page(["filled", "empty", "filled"])
    res = checkbox.process(img, lines)
    assert [i["checked"] for i in sorted(res["items"], key=lambda i: i["box"][1])] == [True, False, True]
    assert all(i["verified"] for i in res["items"]) and res["review"] == []
    assert [l["checkbox"] for l in lines] == [True, False, True]


def test_mismatch_between_ocr_and_image_goes_to_review():
    img, lines = page(["filled", "empty"])
    lines[1]["text"] = "■項目1"  # OCR は ■ と読んだが、画像の四角は空
    res = checkbox.process(img, lines)
    assert lines[1]["checkbox"] is False  # 画像の判定を採る
    assert len(res["review"]) == 1 and "食い違う" in res["review"][0]["reason"]


def test_handwritten_tick_goes_to_review():
    img, lines = page(["ticked"])
    res = checkbox.process(img, lines)
    assert len(res["review"]) == 1 and "手書き" in res["review"][0]["reason"]


def test_glyph_dropped_by_ocr_is_restored_from_the_image():
    img, lines = page(["filled", "empty"])
    lines[0]["text"] = "項目0"  # OCR が行頭の ■ を読み落とした
    res = checkbox.process(img, lines)
    assert lines[0]["text"] == "■項目0" and lines[0]["checkbox"] is True and len(res["items"]) == 2


def test_missing_line_is_reread():
    img, lines = page(["filled", "empty", "filled"], missing_line=1)
    calls = []

    def reread(im, box):
        calls.append(box)
        return [{"box": (98, box[1] + 10, 780, box[3] - 10), "text": "□読み直した項目", "conf": 0.8}]

    res = checkbox.process(img, lines, reread=reread)
    assert res["recovered"] == 1 and len(calls) == 1 and len(lines) == 3
    assert [i["checked"] for i in sorted(res["items"], key=lambda i: i["box"][1])] == [True, False, True]


def test_missing_line_without_reread_goes_to_review():
    img, lines = page(["filled", "empty", "filled"], missing_line=1)
    res = checkbox.process(img, lines)
    assert res["recovered"] == 0 and "行を読めていない" in res["review"][0]["reason"]


def test_box_inside_a_sentence_is_ignored():
    img = np.full((200, 1200), 255, dtype=np.uint8)
    text(img, 100, 60, 200)
    draw_box(img, 340, 60, "empty")
    text(img, 400, 60, 400)
    lines = [{"box": (98, 57, 820, 97), "text": "注)□内に■印のある項目を適用する", "conf": 0.9}]
    res = checkbox.process(np.stack([img] * 3, axis=2), lines)
    assert res["items"] == [] and res["review"] == [] and "checkbox" not in lines[0]


def test_enclosed_kanji_at_the_start_of_a_line_is_not_a_checkbox():
    # 「国」は外側が四角で中に画があるので、手書きのチェックが入った四角に見える
    img = np.full((200, 900), 255, dtype=np.uint8)
    draw_box(img, 100, 80, "ticked")
    lines = [{"box": (98, 76, 620, 118), "text": "国土交通省の基準による", "conf": 0.9}]
    res = checkbox.process(img, lines)
    assert res["boxes"] == 1 and res["items"] == [] and res["review"] == [] and lines[0]["text"] == "国土交通省の基準による"
    # 行頭がその漢字でなければ、これまでどおり要確認にする
    lines = [{"box": (98, 76, 620, 118), "text": "適用する項目", "conf": 0.9}]
    res = checkbox.process(img, lines)
    assert len(res["review"]) == 1 and lines[0]["text"].startswith("□")
