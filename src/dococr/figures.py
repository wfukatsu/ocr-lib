"""ファイルの中の図や写真を画像ファイルに切り出し、Markdown から参照できるようにする。

画像は Markdown と同じフォルダの ``figures/<ファイル名>/`` に置き、Markdown には相対パスの
``![図 p.3-1](figures/…/p0003-01.png)`` を書く。Markdown の中に画像そのものは埋め込まない
(base64 にすると Markdown が数十 MB になり、文字の検索や差分の確認ができなくなる)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from .config import DPI

MIN_SIDE_INCH = 0.5  # 縦か横がこれ未満の領域は切り出さない (印影、記号、汚れ)
PAD_INCH = 0.04  # 図の縁が欠けないよう、領域の外側に足す余白


@dataclass
class FigureWriter:
    """1 つの Markdown から参照する画像を書き出す。"""

    out: Path  # Markdown を置くフォルダ
    name: str  # Markdown のファイル名 (拡張子なし)
    saved: list[dict] = field(default_factory=list)  # 書き出した画像 ({"page", "file", "box"})

    @property
    def dir(self) -> Path:
        return self.out / "figures" / self.name

    def _link(self, alt: str, filename: str, page_no: int | None, box=None) -> str:
        rel = f"figures/{self.name}/{filename}"
        self.saved.append({"page": page_no, "file": rel, "box": box})
        # ファイル名に空白や括弧があるとリンクが切れるので、パスは符号化する
        return f"![{alt}]({quote(rel)})"

    def crop(self, img, page_no: int, box: tuple[float, float, float, float], dpi: int = DPI) -> str | None:
        """ページ画像から box (画素。x0, y0, x1, y1) を切り出し、Markdown の画像参照を返す。小さすぎる領域は None。"""
        x0, y0, x1, y1 = box
        if min(x1 - x0, y1 - y0) < MIN_SIDE_INCH * dpi:
            return None
        pad = PAD_INCH * dpi
        area = (max(0, round(x0 - pad)), max(0, round(y0 - pad)), min(img.width, round(x1 + pad)), min(img.height, round(y1 + pad)))
        n = sum(f["page"] == page_no and f["box"] is not None for f in self.saved) + 1
        filename = f"p{page_no:04d}-{n:02d}.png"
        self.dir.mkdir(parents=True, exist_ok=True)
        img.crop(area).save(self.dir / filename)
        return self._link(f"図 p.{page_no}-{n}", filename, page_no, list(area))

    def page(self, img, page_no: int) -> str:
        """ページ全体を図として書き出す (図面や写真が主のページ)。"""
        filename = f"p{page_no:04d}.png"
        self.dir.mkdir(parents=True, exist_ok=True)
        img.save(self.dir / filename)
        return self._link(f"図 p.{page_no} (ページ全体)", filename, page_no)

    def raw(self, data: bytes, filename: str) -> str:
        """ファイルに埋め込まれていた画像を、そのまま書き出す (Word など)。"""
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / filename).write_bytes(data)
        return self._link(f"図 {Path(filename).stem}", filename, None)
