from types import SimpleNamespace

import pytest
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

pytest.importorskip("docling")
from dococr import export, pipeline  # noqa: E402
from helpers import FORMS  # noqa: E402

W, H = landscape(A4)
COLS = [40, 110, 300, 370, 560, 630, W - 40]  # 見出し・値の欄が 3 組
ROWS = [H - 40, H - 120, H - 300, H - 360, H - 420, H - 540]
GRID = [
    ["題名", "1 号機\n空調機更新工事", "予算額", "4,280", "期間", "自 2025年8月1日\n至 2026年3月31日"],
    ["作業概要", "1. 準備\n2. 部品交換", "変更理由", "風量の低下が顕著である\nことを確認した。", "妥当性評価", "故障した場合\n空調が停止する。"],
    ["拠点名", "分類", "稼働区分", "設備区分", "補足", "概要図"],
    ["1 号", "更新", "平常時", "その他", "", ""],
    ["年度計画", "2025年度", "", "", "", ""],
]


def form_page(c):
    c.setFont("HeiseiKakuGo-W5", 10)
    for r, row in enumerate(GRID):
        for i, text in enumerate(row):
            x0, x1, y1, y0 = COLS[i], COLS[i + 1], ROWS[r], ROWS[r + 1]
            c.rect(x0, y0, x1 - x0, y1 - y0)
            for n, line in enumerate(text.split("\n")):
                c.drawString(x0 + 6, y1 - 18 - 14 * n, line)


def make(tmp_path, *pages):
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    path = tmp_path / "t.pdf"
    c = canvas.Canvas(str(path), pagesize=(W, H))
    for draw in pages:
        draw(c)
        c.showPage()
    c.save()
    return str(path)


def plain_page(c):
    c.setFont("HeiseiKakuGo-W5", 10)
    c.drawString(60, H - 80, "本文だけのページ")


def test_text_layer_form_is_read_field_by_field(tmp_path):
    forms = pipeline.text_form_pages(make(tmp_path, form_page, plain_page), 1, 2, FORMS)
    assert list(forms) == [1] and forms[1]["form"] == "計画概要書" and forms[1]["review"] == []
    f = forms[1]["data"]["fields"]
    assert f["題名"] == "1 号機\n空調機更新工事" and f["予算額"] == "4,280" and f["期間"] == "自 2025年8月1日\n至 2026年3月31日"
    # 隣り合う欄の行が混ざらない
    assert f["変更理由"] == "風量の低下が顕著である\nことを確認した。" and f["妥当性評価"] == "故障した場合\n空調が停止する。"
    assert (f["拠点名"], f["分類"], f["稼働区分"], f["設備区分"]) == ("1 号", "更新", "平常時", "その他")


def _engines(forms=SimpleNamespace(forms=FORMS)):
    calls = []

    def convert(src, raises_on_error=False, **kw):
        calls.append(kw)
        return SimpleNamespace(document=SimpleNamespace(iterate_items=lambda: [], kw=kw), status=SimpleNamespace(value="success"))

    return SimpleNamespace(text=SimpleNamespace(convert=convert), forms=forms), calls


def test_mixed_text_pdf_reads_forms_as_forms_and_the_rest_from_the_text_layer(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "text_markdown", lambda doc, pdf, crop=None: f"本文 {doc.kw['page_range']}")
    engines, calls = _engines()
    out = pipeline.FileOutput(header="h")
    pipeline.read_text_pdf(engines, make(tmp_path, form_page, plain_page), None, out, tmp_path, "t", 2)
    assert out.pages_md[0].startswith("<!-- p.1 帳票: 計画概要書 -->") and "## 題名\n\n1 号機" in out.pages_md[0]
    assert out.pages_md[1] == "<!-- p.2 -->\n\n本文 (2, 2)" and calls == [{"page_range": (2, 2)}]
    assert out.pages[0]["form"] == "計画概要書" and (tmp_path / "json" / "t.p0001.form.json").exists()


def test_pages_without_a_text_layer_are_read_by_ocr(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "text_markdown", lambda doc, pdf, crop=None: f"本文 {doc.kw['page_range']}")
    read = []
    monkeypatch.setattr(pipeline, "read_image_page", lambda engines, src, pno, output, out, name: (read.append(pno), output.pages_md.append(f"OCR {pno}")))
    engines, calls = _engines(forms=None)
    out = pipeline.FileOutput(header="h")
    pipeline.read_text_pdf(engines, make(tmp_path, plain_page, plain_page, plain_page), None, out, tmp_path, "t", 3, ocr_pages=[2])
    assert out.pages_md == ["<!-- p.1 -->\n\n本文 (1, 1)", "OCR 2", "<!-- p.3 -->\n\n本文 (3, 3)"] and read == [2]
    # 対象のページの外にある分は、読まない
    out = pipeline.FileOutput(header="h")
    pipeline.read_text_pdf(engines, make(tmp_path, plain_page, plain_page, plain_page), (1, 1), out, tmp_path, "t", 3, ocr_pages=[2])
    assert out.pages_md == ["本文 (1, 1)"] and read == [2]


def test_text_pdf_without_forms_is_converted_in_one_go(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "text_markdown", lambda doc, pdf, crop=None: "本文")
    engines, calls = _engines()
    out = pipeline.FileOutput(header="h")
    pipeline.read_text_pdf(engines, make(tmp_path, plain_page), None, out, tmp_path, "t", 1)
    assert out.pages_md == ["本文"] and calls == [{}] and out.pages == []
    # 帳票として読まない設定では、帳票のページもテキスト層のまま
    engines, calls = _engines(forms=None)
    out = pipeline.FileOutput(header="h")
    pipeline.read_text_pdf(engines, make(tmp_path, form_page), None, out, tmp_path, "t", 1)
    assert out.pages_md == ["本文"] and calls == [{}]
