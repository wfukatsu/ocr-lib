from dococr import strike_docx
from helpers import make, p, r

def test_strike_and_plain(tmp_path):
    md, found = strike_docx.extract(make(tmp_path, p(r("旧仕様を廃止し", "<w:strike/>"), r("、新仕様を採用する"))))
    assert md.strip() == "~~旧仕様を廃止し~~、新仕様を採用する"
    assert found == [{"where": "本文 段落1", "kind": "strike", "text": "旧仕様を廃止し"}]


def test_adjacent_runs_are_joined_but_not_across_plain_text(tmp_path):
    body = p(r("旧", "<w:strike/>"), r("住所", "<w:dstrike/>"), r(" と "), r("旧電話", "<w:strike/>"))
    md, found = strike_docx.extract(make(tmp_path, body))
    assert md.strip() == "~~旧住所~~ と ~~旧電話~~"
    assert [f["text"] for f in found] == ["旧住所", "旧電話"]


def test_strike_switched_off_and_style_inheritance(tmp_path):
    body = p(r("有効", '<w:strike w:val="0"/>'), r("無効", '<w:rStyle w:val="DelChild"/>'), r("有効2", '<w:rStyle w:val="DelChild"/><w:strike w:val="false"/>'))
    md, _ = strike_docx.extract(make(tmp_path, body))
    assert md.strip() == "有効~~無効~~有効2"


def test_tracked_deletion_is_distinguished(tmp_path):
    body = p(r("契約は"), f'<w:del w:id="1" w:author="a">{r("3月", tag="delText")}</w:del>', f'<w:ins w:id="2" w:author="a">{r("4月")}</w:ins>', r("に終了"))
    md, found = strike_docx.extract(make(tmp_path, body))
    assert md.strip() == "契約は~~3月~~<!-- 変更履歴による削除 -->4月に終了"
    assert found[0]["kind"] == "tracked"
    md, found = strike_docx.extract(make(tmp_path, body), tracked="skip")
    assert md.strip() == "契約は4月に終了" and found == []


def test_whitespace_stays_outside_and_tilde_is_escaped(tmp_path):
    md, _ = strike_docx.extract(make(tmp_path, p(r("a~~b "), r(" 旧 ", "<w:strike/>"), r("新"))))
    assert md.strip() == r"a\~\~b  ~~旧~~ 新"


def test_table_heading_and_header(tmp_path):
    tbl = f"<w:tbl><w:tr><w:tc>{p(r('項目'))}</w:tc><w:tc>{p(r('値'))}</w:tc></w:tr><w:tr><w:tc>{p(r('圧力'))}</w:tc><w:tc>{p(r('5', '<w:strike/>'), r('7'))}</w:tc></w:tr></w:tbl>"
    md, found = strike_docx.extract(make(tmp_path, p(r("仕様"), style="H1") + tbl, header=p(r("旧版", "<w:strike/>"))))
    assert "# 仕様" in md
    assert "| 圧力 | ~~5~~7 |" in md
    assert "<!-- ヘッダー -->\n\n~~旧版~~" in md
    assert {"where": "本文 表1 行2 列2", "kind": "strike", "text": "5"} in found
