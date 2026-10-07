import pytest

pytest.importorskip("docling")
from dococr import export  # noqa: E402
from dococr.types import PageResult  # noqa: E402


def test_to_task_list():
    md = "- ■b.養生を行うこと。\n- [ ] □e.測定を行うこと。\n□a.確認\n注)□内に■印のある項"
    assert export.to_task_list(md) == "- [x] b.養生を行うこと。\n- [ ] e.測定を行うこと。\n- [ ] a.確認\n注)□内に■印のある項"


def test_page_header_notes_pages_that_need_attention():
    base = {"page_collapsed": False, "ink_covered": 0.95}
    assert export.page_header(3, base) == "<!-- p.3 -->"
    assert "未読領域あり" in export.page_header(3, {**base, "ink_covered": 0.4})
    assert "崩壊" in export.page_header(3, {**base, "page_collapsed": True})
    assert export.page_header(3, {**base, "ink_covered": None}) == "<!-- p.3 -->"


def test_review_notes_list_only_uncertain_items_with_candidates():
    result = PageResult(strike_review=[{"candidate": "一部"}, {"candidate": ""}], checks={"items": [], "review": [{"text": "■b.項目", "reason": "食い違う"}], "recovered": 0})
    notes = export.review_notes(7, result)
    assert "要確認 p.7: 取り消し線の範囲が不確か: 一部 -->" in notes and "■b.項目 [食い違う]" in notes
    assert export.review_notes(7, PageResult()) == ""


def test_insert_picture_text():
    assert export.insert_picture_text("a\n<!-- image -->\nb", ["x | y"]) == "a\n<!-- image -->\n\n```text\nx | y\n```\nb"
    assert "図・帳票内の文字" in export.insert_picture_text("no marker", ["x"])


def test_insert_picture_text_puts_image_links_at_the_picture():
    md = "a\n<!-- image -->\nb\n<!-- image -->\nc"
    # 切り出した図は目印を画像参照に置き換え、切り出さなかった図 (小さいもの) は目印を残す
    assert export.insert_picture_text(md, ["x", ""], ["![図 p.1-1](f/p0001-01.png)", None]) == "a\n![図 p.1-1](f/p0001-01.png)\n\n```text\nx\n```\nb\n<!-- image -->\nc"
    # 図の数が合わないときも、画像参照を落とさない
    assert export.insert_picture_text("no marker", ["x"], ["![図](f.png)"]).endswith("![図](f.png)\n\nx")


def picture_doc():
    from docling_core.types.doc import BoundingBox, CoordOrigin, DoclingDocument, ProvenanceItem, Size

    doc = DoclingDocument(name="t")
    doc.add_page(page_no=1, size=Size(width=1000, height=2000))
    box = BoundingBox(l=100, t=300, r=700, b=900, coord_origin=CoordOrigin.TOPLEFT)
    doc.add_picture(prov=ProvenanceItem(page_no=1, bbox=box, charspan=(0, 0)))
    return doc


def test_ocr_markdown_crops_pictures_and_keeps_their_text():
    asked = []

    def crop(page_no, b):
        asked.append((page_no, b.l, b.t, b.r, b.b))
        return "![図 p.1-1](figures/t/p0001-01.png)"

    lines = [{"box": (200, 400, 400, 440), "md": "系統図", "text": "系統図"}, {"box": (200, 1500, 400, 1540), "md": "図の外", "text": "図の外"}]
    md = export.ocr_markdown(picture_doc(), {1: lines}, crop)
    assert asked == [(1, 100, 300, 700, 900)]
    assert md == "![図 p.1-1](figures/t/p0001-01.png)\n\n```text\n系統図\n```"
    assert export.ocr_markdown(picture_doc(), {1: lines}) == "<!-- image -->\n\n```text\n系統図\n```"


def test_form_page():
    md = export.form_page(2, {"form": "計画概要書", "markdown": "## 題名", "review": ["0 (別の読み: o)"]})
    assert md.startswith("<!-- p.2 帳票: 計画概要書 -->\n\n## 題名") and "読み取りが確定できなかった値: 0 (別の読み: o)" in md


def test_glossary_notes_list_fixes_and_untouched_candidates():
    terms = {"fixes": [{"from": "ロポット室内", "to": "ロボット室内"}] * 2, "suggestions": [{"from": "下部シャッター", "to": "上部シャッター"}]}
    notes = export.glossary_notes(4, terms)
    assert "<!-- 用語集で補正 p.4: ロポット室内 → ロボット室内 -->" in notes and "要確認 p.4: 用語集に 1 文字違いの語がある (書き換えていない): 下部シャッター → 上部シャッター" in notes
    assert export.glossary_notes(4, {"fixes": [], "suggestions": []}) == ""
