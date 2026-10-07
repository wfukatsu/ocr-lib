from dococr import form_verify as fv
from helpers import CELL_FORM


def cell(text, ndl=None, alt=None, certain=True, x=0, y=0):
    return {"text": text, "ndl": ndl or text, "alt": alt, "certain": certain, "cell": [x, y, x + 100, y + 40], "box": [x, y, x + 50, y + 30]}


def numbered(readings):
    """1 列目に項目番号、2 列目に項目名が並ぶ表。readings は (NDL の読み, Tesseract の読み)。"""
    return [[cell(alt or ndl, ndl, alt, certain=ndl == alt, y=i * 40), cell("項目", x=100, y=i * 40)] for i, (ndl, alt) in enumerate(readings)]


def test_sequence_numbers_are_fixed_by_position():
    rows = numbered([("11", "01"), ("11", "02"), ("13", "03"), ("24", "04"), ("13", "05"), ("18", "06"), ("10", "07"), ("08", "08")])
    assert fv.fix_sequences(rows) == 7
    assert [r[0]["text"] for r in rows] == ["01", "02", "03", "04", "05", "06", "07", "08"]
    assert all(r[0]["certain"] and r[0]["by"] == "sequence" for r in rows)
    assert rows[0][0]["ndl"] == "11"  # 元の読み取りは残す


def test_sequence_does_not_fill_a_real_gap():
    # 06 が欠番。どのエンジンも 07 以降を読んで確定している行は、位置から決めた番号に書き換えない
    rows = numbered([(n, n) for n in ("01", "02", "03", "04", "05", "07", "08", "09")])
    assert fv.fix_sequences(rows) == 0 and [r[0]["text"] for r in rows] == ["01", "02", "03", "04", "05", "07", "08", "09"]
    assert all(r[0].get("by") is None for r in rows[5:])


def test_sequence_settles_an_unsure_row_between_rows_that_fit():
    # 3 行目はどのエンジンも 03 と読めていないが、確定しておらず、前後の行が連番に合っている
    rows = numbered([("01", "01"), ("02", "02"), ("08", "93"), ("04", "04"), ("05", "05"), ("06", "06")])
    assert fv.fix_sequences(rows) == 1 and rows[2][0]["text"] == "03" and rows[2][0]["by"] == "sequence"
    # 前の行が連番に合っていなければ、決めない
    rows = numbered([("01", "01"), ("02", "02"), ("03", "03"), ("04", "04"), ("05", "05"), ("09", "09"), ("18", "13"), ("11", "11")])
    assert fv.fix_sequences(rows) == 0 and rows[6][0]["text"] == "13"


def test_sequence_is_not_invented_without_enough_support():
    rows = numbered([("40", "40"), ("25", "13"), ("3480", "3480"), ("6", "60"), ("1", "11")])
    before = [r[0]["text"] for r in rows]
    assert fv.fix_sequences(rows) == 0 and [r[0]["text"] for r in rows] == before


def test_short_runs_are_left_alone():
    rows = numbered([("11", "01"), ("11", "02"), ("13", "03")])
    assert fv.fix_sequences(rows) == 0


def test_labels_are_settled_from_the_dictionary():
    labels = CELL_FORM["labels"]
    assert fv.match_label(cell("登録No", "登録No", "HlSRNo", False), labels) == "登録No"
    assert fv.match_label(cell("No", "10", "No", False), labels) == "No"
    assert fv.match_label(cell("定格消費電刀"), labels) == "定格消費電力"  # 1 文字の誤読
    assert fv.match_label(cell("10", "10", "40", False), labels) is None  # 値は見出しにしない
    assert fv.match_label(cell("KX416-2"), labels) is None


def test_typed_value_is_settled_or_flagged():
    rows = [[cell("重要度"), cell("C", "CO", "C", False, x=100)], [cell("重要度", y=40), cell("8", "8", "3", False, x=100, y=40)]]
    assert fv.apply_form(rows, CELL_FORM) == (0, 1)
    assert rows[0][1]["text"] == "C" and rows[0][1]["certain"] and rows[0][1]["by"] == "type"
    assert not rows[1][1]["certain"] and rows[1][1]["by"] == "type_mismatch"


def test_detect_form_needs_several_labels():
    rows = [[cell(lab)] for lab in CELL_FORM["labels"][:9]]
    assert fv.detect_form(rows, [CELL_FORM]) is CELL_FORM
    assert fv.detect_form(rows[:3], [CELL_FORM]) is None and fv.detect_form(rows) is None  # 定義がなければ、どの帳票でもない
