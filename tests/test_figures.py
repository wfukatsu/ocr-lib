from PIL import Image

from dococr import cli, strike_docx
from dococr.figures import FigureWriter
from helpers import make, p, r

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16  # 中身は見ないので、目印になるバイト列でよい
BLIP = '<w:r><w:drawing><a:blip xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="{}"/></w:drawing></w:r>'


def test_crop_saves_region_with_margin_and_returns_link(tmp_path):
    fig = FigureWriter(tmp_path, "TK-9 (希釈槽)")
    img = Image.new("RGB", (2000, 3000), "white")
    link = fig.crop(img, 3, (300, 600, 900, 1200))
    assert link == "![図 p.3-1](figures/TK-9%20%28%E5%B8%8C%E9%87%88%E6%A7%BD%29/p0003-01.png)"  # 空白や括弧でリンクが切れない
    saved = Image.open(tmp_path / "figures" / "TK-9 (希釈槽)" / "p0003-01.png")
    assert saved.size == (624, 624)  # 600 画素に、両側 12 画素 (0.04 インチ) の余白
    assert fig.crop(img, 3, (0, 0, 700, 700)).startswith("![図 p.3-2]") and fig.crop(img, 4, (0, 0, 700, 700)).startswith("![図 p.4-1]")
    assert [f["page"] for f in fig.saved] == [3, 3, 4] and fig.saved[0]["box"] == [288, 588, 912, 1212]


def test_crop_skips_small_regions_and_clips_to_page(tmp_path):
    fig = FigureWriter(tmp_path, "doc")
    img = Image.new("RGB", (1000, 1000), "white")
    assert fig.crop(img, 1, (100, 100, 220, 900)) is None and fig.saved == []  # 幅 120 画素 (約 10mm) は印影や記号
    assert not (tmp_path / "figures").exists()
    fig.crop(img, 1, (0, 0, 1000, 1000))
    assert Image.open(tmp_path / "figures" / "doc" / "p0001-01.png").size == (1000, 1000)


def test_whole_page_is_saved_as_one_image(tmp_path):
    fig = FigureWriter(tmp_path, "図面")
    assert fig.page(Image.new("RGB", (400, 300), "white"), 2) == "![図 p.2 (ページ全体)](figures/%E5%9B%B3%E9%9D%A2/p0002.png)"
    assert fig.crop(Image.new("RGB", (2000, 2000), "white"), 2, (0, 0, 900, 900)).startswith("![図 p.2-1]")  # ページ全体は連番に数えない


def add_image(path, rid="rId9", target="media/image1.png"):
    """helpers.make で作った .docx に、画像とその関係を足す。"""
    import zipfile

    with zipfile.ZipFile(path) as z:
        files = {n: z.read(n) for n in z.namelist()}
    rels = files["word/_rels/document.xml.rels"].decode()
    rels = rels.replace("</Relationships>", f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{target}"/></Relationships>')
    files["word/_rels/document.xml.rels"] = rels.encode()
    files[f"word/{target}"] = PNG
    with zipfile.ZipFile(path, "w") as z:
        for n, data in files.items():
            z.writestr(n, data)
    return path


def test_docx_images_are_extracted_in_place(tmp_path):
    body = p(r("系統図を示す。")) + p(BLIP.format("rId9")) + p(r("旧図", "<w:strike/>"), BLIP.format("rId9"))
    path = add_image(make(tmp_path, body))
    fig = FigureWriter(tmp_path / "out", "仕様書")
    md, found = strike_docx.extract(path, figures=fig)
    link = "![図 image1](figures/%E4%BB%95%E6%A7%98%E6%9B%B8/image1.png)"
    assert md == f"系統図を示す。\n\n{link}\n\n~~旧図~~{link}\n"
    assert (tmp_path / "out" / "figures" / "仕様書" / "image1.png").read_bytes() == PNG
    assert len(fig.saved) == 1 and [f["text"] for f in found] == ["旧図"]  # 同じ画像は 1 度だけ書き出す
    # 置き場所を渡さなければ、これまでどおり文字だけを出す
    assert strike_docx.extract(path)[0] == "系統図を示す。\n\n~~旧図~~\n"


def test_cli_puts_docx_images_next_to_the_markdown(tmp_path):
    path = add_image(make(tmp_path, p(BLIP.format("rId9"))))
    assert cli.main([str(path), "-o", str(tmp_path / "out.md")]) == 0
    assert "(figures/out/image1.png)" in (tmp_path / "out.md").read_text(encoding="utf-8") and (tmp_path / "figures" / "out" / "image1.png").exists()
    assert cli.main([str(path), "-o", str(tmp_path / "plain.md"), "--no-figures"]) == 0
    assert (tmp_path / "plain.md").read_text(encoding="utf-8").strip() == "" and not (tmp_path / "figures" / "plain").exists()
