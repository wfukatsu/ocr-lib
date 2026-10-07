"""PDF のページを画像にする。"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pypdfium2

from .config import DPI


def page_count(pdf: str | Path) -> int:
    d = pypdfium2.PdfDocument(str(pdf))
    n = len(d)
    d.close()
    return n


def render_page(pdf: str | Path, page_no: int, out: Path, quicklook: bool = False) -> Path:
    """PDF の 1 ページを 300dpi の PNG にする。

    quicklook=True は文字化け PDF 用。フォントに Unicode 対応表のない PDF は、pdfium や poppler で
    描画すると一部の文字が欠けるが、macOS の Quick Look なら欠けない (1 ページ目だけ描画できる)。
    """
    if quicklook:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "page.pdf"  # qlmanage は全角を含むパスで失敗することがある
            shutil.copy(pdf, src)
            subprocess.run(["qlmanage", "-t", "-s", "3600", "-o", tmp, str(src)], capture_output=True)
            png = Path(tmp) / "page.pdf.png"
            if png.exists():
                shutil.move(png, out)
                return out
    d = pypdfium2.PdfDocument(str(pdf))
    try:
        d[page_no - 1].render(scale=DPI / 72).to_pil().convert("RGB").save(out)
    finally:
        d.close()
    return out
