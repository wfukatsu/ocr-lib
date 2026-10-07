from dococr.textlayer import Spacing

PAGE = "1.1.1 適用\n(1) 標準仕様書は、官庁営\n繕を実施するための基準である。\n令和４年３月23日 国営設第222号\nSee the manual\nfor details. 減 圧 弁\n"


def test_spaces_follow_the_text_layer():
    s = Spacing(PAGE)
    assert s.fix("1 . 1 . 1 適用") == "1.1.1 適用"
    assert s.fix("(1) 標準仕様書は 、 官庁営 繕を実施するための基準である 。") == "(1) 標準仕様書は、官庁営繕を実施するための基準である。"  # 行の折り返しの空白も除く
    assert s.fix("令和４年３月 23 日 国営設第 222 号") == "令和４年３月23日 国営設第222号"
    assert s.fix("See the manual for details.") == "See the manual for details."  # 欧文の折り返しは空白
    assert s.fix("減 圧 弁") == "減 圧 弁"  # テキスト層にある空白は残す


def test_text_that_is_not_in_the_text_layer_is_left_alone():
    s = Spacing(PAGE)
    assert s.fix("別 の 文字列") == "別 の 文字列" and s.fix("適用") == "適用" and s.fix("") == ""


def test_markdown_markers_and_table_cells_are_kept():
    s = Spacing(PAGE)
    md = "## 1 . 1 . 1 適用\n\n- (1) 標準仕様書は 、 官庁営 繕を実施するための基準である 。\n\n| 項目        | 値     |\n|-----------|-------|\n| 1 . 1 . 1 適用 | 減 圧 弁 |"
    out = s.fix_markdown(md).split("\n")
    assert out[0] == "## 1.1.1 適用" and out[2] == "- (1) 標準仕様書は、官庁営繕を実施するための基準である。"
    assert out[5] == "|-----------|-------|" and [c.strip() for c in out[6].split("|")] == ["", "1.1.1 適用", "減 圧 弁", ""]
