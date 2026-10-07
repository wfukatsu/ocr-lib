"""ライブラリとして呼ぶときの入口。

重い依存 (docling、NDLOCR-Lite) は、それを使う関数を呼んだときに読み込む。
"""
from __future__ import annotations

from pathlib import Path

from . import form_defs, route
from .form_defs import FormDefs


class NeedsOcr(Exception):
    """テキスト層を使えない PDF を、OCR なしで読もうとした。kind は route の経路の種類。"""

    def __init__(self, kind: str):
        super().__init__(f"この PDF は OCR が必要です ({route.KIND_LABEL[kind]})")
        self.kind = kind


def extract_strikes(path: str | Path, tracked: str = "mark", figures=None) -> tuple[str, list[dict]]:
    """Word / Excel / テキスト層のある PDF から取り消し線を抽出し、(Markdown, 取り消し線と要確認箇所の一覧) を返す。

    OCR は使わない。テキスト層を使えない PDF は NeedsOcr を送出するので、ocr_files で読む。
    tracked は Word の変更履歴による削除の扱い ("mark" = 区別して出力 / "skip" = 出力しない)。
    figures (figures.FigureWriter) を渡すと、Word に埋め込まれた画像を取り出して Markdown から参照する。
    """
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".docx", ".doc"):
        from . import strike_docx

        return strike_docx.extract(path, tracked=tracked, figures=figures)
    if ext in (".xlsx", ".xlsm", ".xls"):
        from . import strike_xlsx

        return strike_xlsx.extract(path)
    if ext == ".pdf":
        from . import strike_pdf

        kind = route.classify(path)["kind"]
        if kind != route.TEXT:
            raise NeedsOcr(kind)
        return strike_pdf.extract(path)
    raise ValueError(f"未対応の形式です: {ext}")


def ocr_files(
    inputs: list[str | Path],
    out_dir: str | Path,
    ndlocr_src: str,
    *,
    forms: FormDefs | str | Path | None = None,
    glossary: str | Path | None = None,
    root: str | Path | None = None,
    pages: tuple[int, int] | None = None,
    force_ocr: bool = False,
    use_forms: bool = True,
    grid: bool = True,
    drawings: bool = True,
    figures: bool = True,
) -> list[str]:
    """PDF や画像を構造化 OCR で読み、out_dir に Markdown と JSON を書き出す。読めなかった入力の一覧を返す。

    forms は帳票の定義 (FormDefs か、JSON のパス)。glossary は用語集 (TSV) のパスで、省略すると root があれば
    その中の OCR が要らないファイルから作る。root を指定すると、出力先に相対パスのフォルダ構成を再現する。
    """
    from . import pipeline

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    defs = forms if isinstance(forms, FormDefs) else form_defs.load(forms)
    terms = pipeline.prepare_glossary(str(glossary) if glossary else None, str(root) if root else None, out)
    engines = pipeline.build_engines(ndlocr_src, use_forms=use_forms, drawings=drawings, terms=terms, figures=figures, grid=grid, forms=defs)
    return pipeline.run(engines, [str(i) for i in inputs], out, root=str(root) if root else None, pages=pages, force_ocr=force_ocr)
