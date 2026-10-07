"""Excel (.xlsx / .xls) から取り消し線付きのセルを抽出する。

Excel の取り消し線は、セル全体の書式か、セル内の一部の文字の書式 (リッチテキスト) として
保存されている。どちらも書式から確実に読める。
"""
from __future__ import annotations

import tempfile
import warnings
from pathlib import Path

import openpyxl
from openpyxl.cell.rich_text import CellRichText, TextBlock

from .convert import to_modern
from .mdutil import STRIKE, Seg, render


def _text(value) -> str:
    return "" if value is None else str(value)


def cell_segs(cell) -> list[Seg]:
    """セルの内容を、取り消し線の有無で分けた Seg の並びにする。"""
    whole = bool(cell.font is not None and cell.font.strike)
    value = cell.value
    if isinstance(value, CellRichText):
        segs = []
        for part in value:
            if isinstance(part, TextBlock):
                # 文字ごとの書式がある部分は、その書式だけで決まる (セルの書式は引き継がない)
                strike = bool(part.font.strike) if part.font is not None else whole
                segs.append(Seg(part.text, STRIKE if strike else None))
            else:
                segs.append(Seg(str(part), STRIKE if whole else None))
        return segs
    return [Seg(_text(value), STRIKE if whole else None)]


def extract(path: str | Path) -> tuple[str, list[dict]]:
    """(Markdown, 取り消し線付きセルの一覧) を返す。

    シートは大きいことがあるので、Markdown には取り消し線を含むセルだけを、シート名とセル番地つきで出す。
    """
    path = Path(path)
    found: list[dict] = []
    md: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        path = to_modern(path, tmp)  # 旧形式 .xls は .xlsx に変換してから読む
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # 拡張機能に関する openpyxl の警告
            wb = openpyxl.load_workbook(path, rich_text=True)  # read_only ではセル内の一部の文字の書式が読めない
        for ws in wb.worksheets:
            rows = []
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is None:
                        continue
                    segs = cell_segs(cell)
                    struck = "".join(s.text for s in segs if s.kind)
                    if not struck.strip():
                        continue
                    whole = all(s.kind for s in segs if s.text.strip())
                    text = "".join(s.text for s in segs)
                    cell_md = render(segs).replace("\r", "").replace("\n", "<br>").replace("|", r"\|")
                    found.append({"sheet": ws.title, "cell": cell.coordinate, "kind": "cell" if whole else "partial", "text": text, "struck": struck, "md": cell_md})
                    rows.append(f"| {cell.coordinate} | {cell_md} |")
            if rows:
                hidden = "" if ws.sheet_state == "visible" else " (非表示シート)"
                md.append(f"## {ws.title}{hidden}\n\n| セル | 内容 |\n| --- | --- |\n" + "\n".join(rows))
        wb.close()
    if not md:
        md.append("取り消し線付きのセルはありません。")
    return "\n\n".join(md) + "\n", found
