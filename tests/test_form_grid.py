import numpy as np
from PIL import Image, ImageDraw, ImageFont

from dococr import form_grid as fg


def cell(w=105, h=64):
    return np.zeros((h, w), np.uint8)


def line(ink, p, q, width=3):
    im = Image.fromarray(ink * 255)
    ImageDraw.Draw(im).line((*p, *q), fill=255, width=width)
    return (np.array(im) > 0).astype(np.uint8)


def test_slash_is_a_straight_oblique_line_from_edge_to_edge():
    assert fg.is_slash(line(cell(), (40, 63), (70, 0)))  # 急な斜線 (幅はセルの一部だけ)
    assert fg.is_slash(line(cell(), (0, 50), (104, 26)))  # 未使用の欄を消す長い線の一部 (ゆるい傾き)
    speck = line(cell(), (40, 63), (70, 0))
    speck[30:32, 90:93] = 1
    assert fg.is_slash(speck)  # 離れた小さな汚れは無視する
    assert not fg.is_slash(line(cell(), (50, 50), (60, 15)))  # 文字の「/」は、縁に届かない
    assert not fg.is_slash(line(cell(), (52, 0), (52, 63)))  # 縦の線 (「1」や罫線の残り)
    assert not fg.is_slash(cell())
    two = line(line(cell(), (20, 63), (40, 0)), (60, 63), (80, 0))
    assert not fg.is_slash(two)  # 線が 2 本あるものは、斜線 1 本ではない


def test_dash_is_a_short_horizontal_bar():
    ink = cell()
    ink[30:34, 30:75] = 1
    assert fg.is_dash(ink) and not fg.is_dash(cell()) and not fg.is_dash(line(cell(), (40, 63), (70, 0)))


def ring(size=140, width=5, arc=None):
    im = Image.new("L", (size + 20, size + 20), 0)
    d = ImageDraw.Draw(im)
    if arc:
        d.arc((10, 10, 10 + size, 10 + size), *arc, fill=255, width=width)
    else:
        d.ellipse((10, 10, 10 + size, 10 + size), outline=255, width=width)
    return (np.array(im) > 0).astype(np.uint8)


def test_stamp_is_recognised_by_its_round_frame_and_faint_ones_are_left_unsure():
    assert fg.is_stamp(ring()) is True
    faint = ring(width=2)  # 枠が薄く、中の文字のインクの方が多い
    faint[50:110, 50:110] = 1
    assert fg.is_stamp(faint) is None
    text = np.zeros((150, 150), np.uint8)
    text[10:140, 10:140] = 1  # 四隅までインクがあるもの (大きな文字や図)
    assert fg.is_stamp(text) is False
    assert fg.is_stamp(ring(size=40)) is False  # 文字ほどの大きさの丸は印影ではない


def form():
    """左端のセルが 3 行にまたがる表。2 行目に空のセルと斜線のセル、3 行目に背の高い説明のセルがある。

    x: 50 | 350 | 650 | 950 | 1250      y: 50, 150, 250 (3 行目は 250〜550)
    """
    img = Image.new("RGB", (1300, 1000), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=36)
    for y in (50, 150, 250, 550):
        d.line((350 if y in (150, 250) else 50, y, 1250, y), fill="black", width=3)
    for x in (50, 350, 650, 950, 1250):
        d.line((x, 50, x, 550), fill="black", width=3)
    for (x, y), t in {(100, 280): "NAME", (400, 80): "BEFORE", (700, 80): "9.8", (1000, 80): "9.7", (400, 180): "AFTER", (1000, 180): "9.5"}.items():
        d.text((x, y), t, font=font, fill="black")
    d.line((655, 245, 945, 155), fill="black", width=3)  # 2 行目の 3 列目は斜線 (該当なし)
    for i in range(4):  # 3 行目の 2 列目は、4 行の説明と図 (図があるので、行ごとには分けられない)
        d.text((370, 270 + i * 60), "NOTE", font=font, fill="black")
    d.line((500, 270, 630, 530), fill="black", width=3)
    d.line((630, 270, 500, 530), fill="black", width=3)
    return np.array(img)


class Reader:
    def __init__(self):
        self.read_calls, self.check_calls = 0, 0

    def read(self, crop, check=True):
        self.read_calls += 1
        return {"text": f"w{crop.shape[1] // 50}", "certain": True, "ndl": "", "alt": None}

    def check(self, res, crop):
        self.check_calls += 1
        return res


def test_rows_follow_cell_tops_and_keep_columns_aligned():
    asked = []

    def region_ocr(img, box):
        asked.append(box)
        return [{"box": (box[0], box[1] + 60, box[2], box[1] + 100), "text": "二行目", "conf": 0.9}, {"box": (box[0], box[1], box[2], box[1] + 40), "text": "一行目", "conf": 0.3}]

    res = fg.read_grid(form(), Reader(), region_ocr)
    rows = res["rows"]
    assert [len(r) for r in rows] == [4, 4, 4]
    assert "ditto" not in rows[0][0] and rows[1][0] == {"ditto": True, "cell": rows[0][0]["cell"]} and "ditto" in rows[2][0]  # 3 行にまたがる左端のセル
    assert rows[1][2]["text"] == fg.SLASH and rows[1][2]["by"] == "shape"
    assert rows[2][2]["text"] == "" and rows[2][3]["text"] == ""  # 空のセルも列として残る
    # 背の高いセルは行検出を通して読み、上から順につなぐ。信頼度の低い行があれば要確認
    assert len(asked) == 1 and rows[2][1]["text"] == "一行目 二行目" and not rows[2][1]["certain"] and res["review"] == ["一行目 二行目"]
    md = fg.to_markdown(rows).splitlines()
    assert md[1].count(" | ") == 3 and md[2].startswith("〃 | ") and md[2].split(" | ")[2] == "／" and md[3] == "〃 | 一行目 二行目 (?)"
    assert res["items"] == 7  # 形で決めた斜線は、読んだ値に数えない


def test_cached_readings_are_reused_and_post_can_correct_them():
    from dococr.form_cells import read_cells

    img = form()
    first = Reader()
    cached = read_cells(img, first, check=False)
    reader = Reader()

    def post(parts):
        for p in parts:
            if p["text"] == "w1":
                p["text"] = "補正"

    res = fg.read_grid(img, reader, None, cached=cached, post=post)
    # 文字認識はやり直さず、照合だけを足す (斜線のセルは照合しない)
    assert reader.read_calls == 0 and reader.check_calls == first.read_calls - 1
    assert any(c.get("text") == "補正" for r in res["rows"] for c in r)


def test_long_strike_over_unused_rows_becomes_slashes():
    img = Image.new("RGB", (1700, 500), "white")
    d = ImageDraw.Draw(img)
    for y in (50, 150, 250, 350):
        d.line((50, y, 1650, y), fill="black", width=3)
    for x in range(50, 1651, 200):
        d.line((x, 50, x, 350), fill="black", width=3)
    d.text((80, 80), "ITEM", font=ImageFont.load_default(size=36), fill="black")
    d.line((260, 345, 1640, 55), fill="black", width=3)  # 未使用の欄を消す長い斜線
    res = fg.read_grid(np.array(img), Reader())
    texts = [c.get("text") for r in res["rows"] for c in r]
    # 線が通ったセルは「／」になり、線の切れ端を文字として読まない
    assert texts[0].startswith("w") and texts.count(fg.SLASH) >= 7 and set(texts) == {texts[0], fg.SLASH, ""} and res["review"] == []
