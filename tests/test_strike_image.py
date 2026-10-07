import numpy as np
from PIL import Image, ImageDraw, ImageFont

from dococr import strike_image
from dococr.mdutil import merge_adjacent


def page():
    """300dpi 相当。1 行目は取り消し線、2 行目は通常、3 行目は下線、全体を枠で囲む。"""
    img = Image.new("L", (1600, 700), 255)
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=44)
    boxes = []
    for i, text in enumerate(["STRUCK OUT LINE OF TEXT", "NORMAL LINE OF TEXT", "UNDERLINED LINE OF TEXT", "HALF STRUCK LINE OF TEXT"]):
        y = 100 + i * 130
        d.text((100, y), text, font=font, fill=0)
        l, t, r, b = d.textbbox((100, y), text, font=font)
        boxes.append((l, t, r, b))
    l, t, r, b = boxes[0]
    d.line((l - 5, (t + b) // 2, r + 5, (t + b) // 2), fill=0, width=4)  # 取り消し線
    l, t, r, b = boxes[2]
    d.line((l, b + 8, r, b + 8), fill=0, width=3)  # 下線
    l, t, r, b = boxes[3]
    d.line((l, (t + b) // 2, l + (r - l) // 2, (t + b) // 2), fill=0, width=4)  # 行の前半だけ
    d.rectangle((40, 40, 1560, 660), outline=0, width=4)  # 枠線
    return np.array(img), boxes


def test_detect_only_lines_crossing_text():
    img, boxes = page()
    strikes = strike_image.detect(img)
    ys = sorted(s["y"] + s["h"] // 2 for s in strikes)
    mids = [(boxes[0][1] + boxes[0][3]) // 2, (boxes[3][1] + boxes[3][3]) // 2]
    assert len(strikes) == 2
    assert all(abs(y - m) <= 4 for y, m in zip(ys, mids))


def test_erase_removes_the_line_but_keeps_text():
    img, boxes = page()
    strikes = strike_image.detect(img)
    out = strike_image.erase(img, strikes)
    assert strike_image.detect(out) == []
    l, t, r, b = boxes[0]
    assert (out[t:b, l:r] < 150).sum() > 0.5 * (img[t:b, l:r] < 150).sum() - (r - l) * 6


def test_mark_lines_whole_partial_and_review():
    img, boxes = page()
    strikes = strike_image.detect(img)
    lines = [{"box": b, "text": t} for b, t in zip(boxes, ["STRUCK OUT LINE OF TEXT", "NORMAL LINE OF TEXT", "UNDERLINED LINE OF TEXT", "HALF STRUCK LINE OF TEXT"])]
    review = strike_image.mark_lines(lines, strikes)
    assert lines[0]["md"] == "~~STRUCK OUT LINE OF TEXT~~" and lines[0]["struck"] == "all"
    assert lines[1]["md"] == "NORMAL LINE OF TEXT" and lines[2]["struck"] is None
    assert lines[3]["struck"] == "part" and lines[3]["md"].startswith("~~HALF STRUCK")
    assert len(review) == 1 and "推定" in review[0]["reason"]


def test_unmatched_strike_goes_to_review():
    review = strike_image.mark_lines([], [{"x": 10, "y": 10, "w": 200, "h": 4}])
    assert len(review) == 1 and "対応する行がない" in review[0]["reason"]


def test_merge_adjacent_struck_lines():
    assert merge_adjacent("~~一行目~~ ~~二行目~~ 通常") == "~~一行目 二行目~~ 通常"


def table_page(font_size=36, row_h=50):
    """文字のすぐ上下に罫線がある、行の詰まった表。"""
    img = Image.new("L", (1400, 600), 255)
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=font_size)
    for i in range(6):
        y = 60 + i * row_h
        d.line((60, y, 1340, y), fill=0, width=3)
        if i < 5:
            d.text((80, y + 4), "TIGHT ROW OF TEXT IN A RULED TABLE", font=font, fill=0)
    for x in (60, 700, 1340):
        d.line((x, 60, x, 60 + 5 * row_h), fill=0, width=3)
    return np.array(img)


def test_table_rules_are_not_strikes():
    assert strike_image.detect(table_page()) == []


def test_strike_inside_a_frame_is_still_detected():
    img, boxes = page()  # 枠で囲まれたページ。取り消し線は枠に接していない
    assert len(strike_image.detect(img)) == 2


def test_stroke_of_a_large_glyph_is_not_a_strike():
    img = Image.new("L", (1400, 500), 255)
    d = ImageDraw.Draw(img)
    d.text((100, 80), "EFH", font=ImageFont.load_default(size=300), fill=0)  # 横画が 100px を超える大きな文字
    assert strike_image.detect(np.array(img)) == []


def test_demote_in_regions():
    lines = [{"box": (100, 100, 500, 140), "text": "IN TABLE", "struck": "all", "md": "~~IN TABLE~~"}, {"box": (100, 400, 500, 440), "text": "BODY", "struck": "all", "md": "~~BODY~~"}]
    review = []
    assert strike_image.demote_in_regions(lines, [(50, 50, 600, 200)], review) == 1
    assert lines[0]["struck"] is None and lines[0]["md"] == "IN TABLE" and lines[1]["md"] == "~~BODY~~"
    assert review[0]["candidate"] == "IN TABLE" and "罫線" in review[0]["reason"]


def test_partial_range_is_settled_by_rereading_the_struck_span():
    # 線の範囲だけを読み直した文字列が、行の中の 1 か所にそのまま現れれば、その範囲で確定する
    text = "(2)ベルトの張りを目視で確認する。張力計で測定し、記録する。"
    lines = [{"box": (346, 1358, 1678, 1405), "text": text}]
    review = strike_image.mark_lines(lines, [{"x": 740, "y": 1379, "w": 370, "h": 6, "through": 0.4}], reread=lambda box: "目視で確認する。")
    assert lines[0]["md"] == "(2)ベルトの張りを~~目視で確認する。~~張力計で測定し、記録する。" and lines[0]["struck"] == "part" and review == []
    # 読み直しが少し違う場合は、最も長く一致する箇所から決め、要確認に残す
    lines = [{"box": (346, 1358, 1678, 1405), "text": text}]
    review = strike_image.mark_lines(lines, [{"x": 740, "y": 1379, "w": 370, "h": 6}], reread=lambda box: "日視で確認する。")
    assert "~~目視で確認する。~~" in lines[0]["md"] and len(review) == 1 and "照合" in review[0]["reason"]
    # 読み直しが当たらなければ、位置から按分する
    lines = [{"box": (346, 1358, 1678, 1405), "text": text}]
    review = strike_image.mark_lines(lines, [{"x": 740, "y": 1379, "w": 370, "h": 6}], reread=lambda box: "XYZ")
    assert lines[0]["struck"] == "part" and "位置からの推定" in review[0]["reason"]


def test_locate_ignores_spaces_and_needs_a_unique_match():
    assert strike_image._locate("1,200 1,500 m3/h 以上", "1,200") == (0, 5, True)
    assert strike_image._locate("A 以下 B 以下", "以下") == (2, 4, False)  # 2 か所にある
    assert strike_image._locate("点検は 6 か月ごとに実施する。", "6か月ごと") == (4, 10, True)
    assert strike_image._locate("本文", "") is None and strike_image._locate("本文の行", "別の文字列") is None


def test_by_width_counts_half_width_characters_as_half():
    # 「(2)」は全角 1.5 文字分。文字数で按分すると、後ろの範囲が 1 文字ずれる
    assert strike_image._by_width("(2)あいうえお", 0, 650, 350, 650) == (5, 8)


def test_strike_inside_a_table_cell_is_kept_when_it_fits_the_text():
    cell = {"box": (1439, 2073, 1857, 2134), "text": "定格の110%以下"}
    rule = {"box": (100, 2300, 500, 2340), "text": "罫線に近い行"}
    lines = [cell, rule]
    strikes = [{"x": 1451, "y": 2104, "w": 406, "h": 6, "through": 0.32}, {"x": 60, "y": 2318, "w": 1300, "h": 5, "through": 0.19}]
    review = strike_image.mark_lines(lines, strikes)
    table = (60, 1900, 1900, 2400)
    assert strike_image.demote_in_regions(lines, [table], review, tables=[table]) == 1
    assert cell["md"] == "~~定格の110%以下~~" and cell["struck"] == "all"  # 文字の幅に収まり、文字の画を横切っている
    assert rule["struck"] is None and rule["md"] == "罫線に近い行"  # 行の幅を越えて続く線は、罫線かもしれない
    # 表でない領域 (図、帳票) の中では、これまでどおり確定しない
    cell2 = {"box": (1439, 2073, 1857, 2134), "text": "定格の110%以下"}
    review = strike_image.mark_lines([cell2], strikes[:1])
    assert strike_image.demote_in_regions([cell2], [table], review) == 1 and cell2["struck"] is None
