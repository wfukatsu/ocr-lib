"""ページが定義済みの帳票かを判定し、帳票として読む。

usage:
  dococr-form 帳票.pdf --ndlocr-src <ndlocr-lite/src> --out-dir out [--forms forms.json]
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from . import crosscheck, form_defs, form_grid, form_verify, render, route
from .crosscheck import CellReader, ShortLineChecker
from .form_cells import crop_of, is_form, read_cells, to_markdown, to_rows
from .form_defs import FormDefs
from .form_regions import read_regions, regions_markdown
from .line_ocr import PageLineOcr


def _review(rows: list[list[dict]]) -> list[str]:
    return [c["text"] + (f" (別の読み: {c['third']})" if c.get("third") else "") for r in rows for c in r if not c["certain"]]


EMPTY_TERMS = {"fixes": [], "suggestions": []}  # 用語集と照合していない場合の結果


def _region_result(form: dict, res: dict) -> dict:
    return {"form": form["name"], "markdown": regions_markdown(res, form), "items": res["lines"], "review": res["review"], "data": {"form": form["name"], **res}}


def read_text_form(img: np.ndarray, lines: list[dict], dpi: int = 300, forms: FormDefs = FormDefs()) -> dict | None:
    """テキスト層のあるページを、欄の中に文章や表が入る帳票として読む。定義済みの帳票でなければ None。

    lines はテキスト層から取った行 (画素の座標)。文字は OCR しないので誤読がなく、欄への割り当てだけを行う。
    """
    if not forms.regions or not is_form(img, dpi):
        return None
    for form in forms.regions:
        res = read_regions(img, lambda _img: [dict(l) for l in lines], form, dpi, clean=False)
        if res["labels_found"] >= form["min_labels"]:
            return _region_result(form, res)
    return None


class FormReader:
    """ページを帳票として読む。

    forms は帳票の定義 (form_defs)。まずセルごとに値が入る帳票として読み、定義に当たらなければ、欄の中に
    文章や表が入る帳票として読む。どちらでもなければ、定義のない罫線の帳票 (測定記録、検査記録など) として、
    セルの並びをそのまま表にする。

    罫線の表が続く文書では、ほとんどのページがどちらの帳票でもない。そうしたページで時間をかけないよう、
    帳票かどうかは 1 つのエンジンの読みだけで見分け、別のエンジンとの照合は帳票と分かってから行う。
    """

    def __init__(self, ndlocr_src: str, use_vision: bool = True, cross_check: bool = True, glossary=None, grid: bool = True, forms: FormDefs = FormDefs()):
        self.glossary = glossary
        self.forms = forms
        self.grid = grid  # 定義のない罫線の帳票も、セル単位で読む
        self._terms = EMPTY_TERMS  # 欄単位の帳票を読んだときの、用語集との照合の結果
        self.reader = CellReader(ndlocr_src, cross_check=cross_check, glossary=glossary)
        self.page_ocr = PageLineOcr(ndlocr_src)
        self.use_vision = use_vision

    def read(self, img: np.ndarray, dpi: int = 300, strict: bool = True) -> dict | None:
        """{"form": 帳票名, "markdown": …, "items": 読んだ値の数, "review": 要確認の一覧, "data": JSON に出す内容}

        strict=True は、ほかの種類のページが混ざる入力向け。罫線のセルが広い範囲を占めるページだけを対象にし、
        それ以外は None を返す。strict=False は、帳票だと分かっている入力向け。
        定義済みの帳票でなければ、罫線の帳票として読む (grid=False の場合、strict=True では None を返し、
        strict=False ではセルを読んだ順に並べた結果を返す。"form" は None)。
        """
        if strict and not is_form(img, dpi):
            return None
        cells = read_cells(img, self.reader, dpi, check=False)
        if form_verify.detect_form([cells], self.forms.cells) is None:
            for form in self.forms.regions:
                # 帳票だと分かっている入力では、見出しが 2/3 見つかればよい
                need = form["min_labels"] if strict else max(1, round(form["min_labels"] * 2 / 3))
                res = read_regions(img, lambda im: self._lines(im, dpi), form, dpi, checker=ShortLineChecker(self.reader, self.use_vision), reader=self.reader, min_labels=need)
                if res is not None and res["labels_found"] >= need:
                    return _region_result(form, res) | {"glossary": self._terms}
            if self.grid:
                return self._grid(img, cells, dpi)
            if strict:
                return None
        for c in cells:  # 短い値を別のエンジンと照合する
            self.reader.check(c, crop_of(img, c["box"], dpi))
        rows = to_rows(cells)
        terms = self.glossary.apply([c for r in rows for c in r]) if self.glossary is not None else EMPTY_TERMS
        stats = form_verify.verify(rows, img, use_vision=self.use_vision, forms=self.forms.cells)
        return {"form": stats["form"], "markdown": to_markdown(rows), "items": stats["items"], "review": _review(rows), "glossary": terms, "data": {"verify": stats, "rows": rows}}

    def _grid(self, img: np.ndarray, cells: list[dict], dpi: int) -> dict:
        """定義のない罫線の帳票として読む。cells は、帳票を見分けるときに読んだ結果 (文字認識をやり直さない)。"""
        terms = dict(EMPTY_TERMS)

        def post(parts: list[dict]):
            if self.glossary is not None:
                terms.update(self.glossary.apply(parts))
            lines = crosscheck.vision_lines(img) if self.use_vision and any(not p["certain"] for p in parts) else None
            if lines:
                crosscheck.vote([parts], lines)

        res = form_grid.read_grid(img, self.reader, self.page_ocr.ocr_region, dpi, cached=cells, post=post)
        return {"form": form_grid.NAME, "markdown": form_grid.to_markdown(res["rows"]), "items": res["items"], "review": res["review"], "glossary": terms, "data": {"form": form_grid.NAME, **res}}

    def _lines(self, img: np.ndarray, dpi: int) -> list[dict]:
        """ページ全体を行単位で OCR する。読めた割合が低いページは分割して読み直す。"""
        lines, _ = self.page_ocr.read_page(img, dpi)
        lines = [{**ln, "box": list(ln["box"])} for ln in lines]
        self._terms = self.glossary.apply(lines) if self.glossary is not None else EMPTY_TERMS
        return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--ndlocr-src", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--forms", help="帳票の定義 (JSON)。省略すると、罫線のセルの並びをそのまま表にする")
    ap.add_argument("--no-cross-check", action="store_true", help="短い値を Tesseract と照合しない")
    ap.add_argument("--no-vision", action="store_true", help="食い違った値の多数決に macOS の Vision を使わない")
    ap.add_argument("--no-grid", action="store_true", help="定義のない帳票を、罫線のセルの並びの表にしない (読んだ順に並べる)")
    a = ap.parse_args(argv)
    forms = FormReader(a.ndlocr_src, use_vision=not a.no_vision, cross_check=not a.no_cross_check, grid=not a.no_grid, forms=form_defs.load(a.forms))
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for src in a.inputs:
        src = Path(src)
        mds, report = [], []
        with tempfile.TemporaryDirectory() as tmp:
            if route.is_image_file(src):
                pages = [(1, src)]
            else:
                info = route.classify(src)
                ql = info["kind"] == route.GARBLED and info["pages"] == 1 and platform.system() == "Darwin" and shutil.which("qlmanage") is not None
                pages = [(n, render.render_page(src, n, Path(tmp) / f"p{n}.png", ql)) for n in range(1, info["pages"] + 1)]
            for pno, png in pages:
                res = forms.read(np.array(Image.open(png).convert("RGB")), strict=False)
                head = f"<!-- p.{pno}" + (f" 帳票: {res['form']}" if res["form"] else "") + " -->"
                note = f"\n\n<!-- 要確認 p.{pno}: 読み取りが確定できなかった値: " + " / ".join(res["review"]) + " -->" if res["review"] else ""
                mds.append(f"{head}\n\n{res['markdown']}{note}")
                report.append({"page": pno, "items": res["items"], "review": res["review"], **res["data"]})
        (out / f"{src.stem}.md").write_text("\n\n".join(mds) + "\n", encoding="utf-8")
        (out / f"{src.stem}.form.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{src.stem}: 項目 {sum(p['items'] for p in report)} 要確認 {sum(len(p['review']) for p in report)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
