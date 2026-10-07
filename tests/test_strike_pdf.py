from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from dococr import strike_pdf

FONT, SIZE = "HeiseiKakuGo-W5", 12


def make(tmp_path, draw):
    pdfmetrics.registerFont(UnicodeCIDFont(FONT))
    path = tmp_path / "t.pdf"
    c = canvas.Canvas(str(path), pagesize=(400, 300))
    c.setFont(FONT, SIZE)
    draw(c)
    c.save()
    return path


def hline(c, x0, x1, y):
    c.setLineWidth(0.6)
    c.line(x0, y, x1, y)


def test_line_through_text_is_strike(tmp_path):
    def draw(c):
        c.drawString(50, 250, "旧価格 1,000円")
        hline(c, 50, 50 + c.stringWidth("旧価格", FONT, SIZE), 250 + SIZE * 0.35)

    md, found = strike_pdf.extract(make(tmp_path, draw))
    assert "~~旧価格~~ 1,000円" in md
    assert found == [{"page": 1, "kind": "strike", "text": "旧価格", "certain": True}]


def test_underline_and_table_rule_are_not_strike(tmp_path):
    def draw(c):
        c.drawString(50, 250, "下線つきの文")
        hline(c, 50, 130, 250 - 2)  # 下線
        c.drawString(50, 200, "表の中の文")
        hline(c, 30, 370, 200 + SIZE + 4)  # 罫線
        hline(c, 30, 370, 200 - 6)

    md, found = strike_pdf.extract(make(tmp_path, draw))
    assert "~~" not in md and found == []


def test_ambiguous_line_is_reported_not_asserted(tmp_path):
    def draw(c):
        c.drawString(50, 250, "判定が難しい文")
        hline(c, 50, 140, 250 + SIZE * 0.6)  # 文字の上端に近い

    md, found = strike_pdf.extract(make(tmp_path, draw))
    assert "~~" not in md
    assert found and found[0]["certain"] is False and found[0]["page"] == 1
    assert "要確認 p.1" in md


def test_has_text_layer(tmp_path):
    assert strike_pdf.has_text_layer(make(tmp_path, lambda c: c.drawString(50, 250, "テキスト層のある文書です。" * 3)))
