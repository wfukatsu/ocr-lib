import pytest

pytest.importorskip("docling")
from dococr import docling_ocr, pipeline  # noqa: E402
from dococr.types import PageResult  # noqa: E402


def test_parse_pages():
    assert pipeline.parse_pages("19-21") == (19, 21) and pipeline.parse_pages("5") == (5, 5) and pipeline.parse_pages(None) is None


def test_collector_is_looked_up_by_id():
    c = docling_ocr.PageCollector()
    cid = docling_ocr.register_collector(c)
    assert docling_ocr._COLLECTORS[cid] is c and docling_ocr.NdlOcrLiteOptions(collector_id=cid).collector_id == cid


def test_file_output_writes_markdown_and_reports(tmp_path):
    out = pipeline.FileOutput(header="<!-- 経路: x -->")
    out.pages_md += ["p1", "p2"]
    out.pages += [{"page": 1, "garbage": 2}, {"page": 2, "garbage": 1}]
    out.status.add("success")
    out.checks.append({"page": 1, "text": "■a", "checked": True})
    out.write(tmp_path, "doc", {"source": "s", "route": "image"})
    assert (tmp_path / "doc.md").read_text(encoding="utf-8") == "<!-- 経路: x -->\n\np1\n\n<!-- page -->\n\np2"
    import json

    meta = json.loads((tmp_path / "doc.meta.json").read_text(encoding="utf-8"))
    assert meta["garbage_dropped"] == 3 and meta["status"] == ["success"] and [p["page"] for p in meta["pages"]] == [1, 2]
    assert (tmp_path / "doc.checkbox.json").exists() and (tmp_path / "doc.strike.json").exists() and not (tmp_path / "doc.form_review.json").exists()


class FakeOcr:
    """読み直しを求められた領域と、返す行を記録する。"""

    garbage = 0

    def __init__(self, region_lines):
        self.region_lines, self.calls = region_lines, []

    def ocr_region(self, img, box):
        self.calls.append(box)
        return list(self.region_lines)


def line(text, x0, y0, x1, y1, conf=0.9):
    return {"box": (x0, y0, x1, y1), "text": text, "conf": conf}


def test_refine_rereads_tables_and_keeps_the_better_result():
    import numpy as np

    img = np.full((1000, 1000, 3), 255, dtype=np.uint8)
    lines = [line("本文の行", 50, 50, 500, 90), line("表の行", 100, 400, 300, 440)]
    ocr = FakeOcr([line("表の行をより長く読めた結果", 100, 400, 600, 440)])
    out, redo = docling_ocr.refine_with_layout(ocr, img, lines, [("text", (40, 40, 600, 100)), ("table", (80, 380, 700, 460))])
    assert redo == 1 and ocr.calls == [(80, 380, 700, 460)]  # 読めている本文の領域は読み直さない
    assert [l["text"] for l in out] == ["本文の行", "表の行をより長く読めた結果"]


def test_refine_does_not_fill_gaps_with_digit_fragments():
    import numpy as np

    img = np.full((1000, 1000, 3), 255, dtype=np.uint8)
    ocr = FakeOcr([line("41", 100, 400, 140, 440), line("0.00", 200, 400, 260, 440)])
    out, redo = docling_ocr.refine_with_layout(ocr, img, [], [("text", (80, 380, 700, 460))])
    assert out == [] and redo == 0 and len(ocr.calls) == 1


def test_glossary_is_built_before_ocr_and_reused_afterwards(tmp_path, capsys):
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "TK-9(回転式保管棚)_構造図.PDF").write_bytes(b"")
    terms = pipeline.prepare_glossary(None, str(src), out)
    assert "TK-9" in terms and "回転式保管棚" in terms and (out / "glossary.tsv").exists()
    # 人が直した用語集は作り直さない
    with open(out / "glossary.tsv", "a", encoding="utf-8") as f:
        f.write("手で足した語\t用語\t1\t\n")
    assert "手で足した語" in pipeline.prepare_glossary(None, str(src), out)
    assert "書き出しました" in capsys.readouterr().out
    assert pipeline.prepare_glossary(None, str(src), out, disabled=True) is None and pipeline.prepare_glossary(None, None, out) is None
    other = tmp_path / "g.tsv"
    other.write_text("用語\t種類\t出現回数\t出典\nKX416-2\t型番\t1\t\n", encoding="utf-8")
    assert "KX416-2" in pipeline.prepare_glossary(str(other), str(src), out)


def test_text_pdf_figures_are_cropped_from_the_rendered_page(tmp_path):
    from types import SimpleNamespace

    from PIL import Image
    from reportlab.pdfgen import canvas

    from dococr.figures import FigureWriter

    pdf = tmp_path / "t.pdf"
    c = canvas.Canvas(str(pdf), pagesize=(400, 600))
    c.rect(72, 600 - 72 - 144, 144, 144, fill=1)  # 左上から 1 インチの位置に、2 インチ角の黒い四角
    c.showPage()
    c.save()
    fig = FigureWriter(tmp_path, "t")
    crop = pipeline.pdf_cropper(str(pdf), fig)
    link = crop(1, SimpleNamespace(l=72, t=72, r=216, b=216))  # PDF の座標 (ポイント、左上原点)
    assert link == "![図 p.1-1](figures/t/p0001-01.png)"
    img = Image.open(tmp_path / "figures" / "t" / "p0001-01.png").convert("L")
    assert img.size == (624, 624) and img.getpixel((312, 312)) < 50 and img.getpixel((3, 3)) > 200  # 四角が中央にあり、余白は白
    assert crop(1, SimpleNamespace(l=0, t=0, r=20, b=20)) is None


def test_file_output_lists_figures_in_meta(tmp_path):
    import json

    from PIL import Image

    from dococr.figures import FigureWriter

    fig = FigureWriter(tmp_path, "doc")
    out = pipeline.FileOutput(header="h", figures=fig)
    out.pages_md.append(fig.page(Image.new("RGB", (10, 10)), 1))
    out.write(tmp_path, "doc", {})
    assert json.loads((tmp_path / "doc.meta.json").read_text(encoding="utf-8"))["figures"] == [{"page": 1, "file": "figures/doc/p0001.png", "box": None}]
    pipeline.FileOutput(header="h").write(tmp_path, "plain", {})
    assert json.loads((tmp_path / "plain.meta.json").read_text(encoding="utf-8"))["figures"] == []
