"""構造化 OCR: 入力ファイルの経路を決め、ページごとに読み、結果を書き出す。

入力はファイルごとに経路を決める (route.py)。テキスト層が信用できる PDF は OCR しない。
それ以外は 1 ページずつ 300dpi の画像にしてから読む。PDF のまま docling に渡すと、
ぼやけたページ画像が OCR に使われ、文字化けした (または OCR 由来の) テキスト層が表の中身に混ざる。

usage:
  dococr-ocr --ndlocr-src <ndlocr-lite/src> --out <dir> [--pages 1-3] <pdf|画像>...
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pdfplumber
from PIL import Image

from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

from . import drawing, export, form_defs, glossary, route, textlayer
from .config import DPI
from .docling_ocr import NdlOcrLiteOptions, PageCollector, register_collector, register_engine
from .figures import FigureWriter
from .form_reader import FormReader, read_text_form
from .render import render_page
from .types import PageResult

# 帳票として読んだページなど、OCR 段を通らなかったページの統計の既定値
EMPTY_STATS = {
    "regions": 0, "lines": 0, "regions_reocr": 0, "page_collapsed": False, "garbage": 0, "ink_covered": None,
    "checkboxes": 0, "checkbox_review": 0, "checkbox_recovered": 0, "strike_lines": 0, "struck": 0, "strike_review": 0, "low_conf": 0,
    "glossary_fixes": 0, "glossary_suggestions": 0,
}  # fmt: skip


@dataclass
class Engines:
    """読み取りに使う部品。1 度作って、すべてのファイルで使い回す。"""

    ocr: DocumentConverter  # ページ画像を OCR する
    text: DocumentConverter  # テキスト層から読む
    collector: PageCollector  # OCR 段がページごとの結果を入れる
    forms: FormReader | None  # 帳票として読む (使わない場合は None)
    drawings: bool = True  # 図面のページを Vision で読む
    figures: bool = True  # 図や写真を画像に切り出して、Markdown から参照する


def build_engines(ndlocr_src: str, use_forms: bool = True, drawings: bool = True, terms: glossary.Glossary | None = None, figures: bool = True, grid: bool = True, forms: form_defs.FormDefs = form_defs.FormDefs()) -> Engines:
    register_engine()
    collector = PageCollector(glossary=terms)
    opts = PdfPipelineOptions()
    opts.do_ocr = True
    opts.ocr_options = NdlOcrLiteOptions(ndlocr_src=ndlocr_src, collector_id=register_collector(collector))
    opts.do_table_structure = True
    opts.table_structure_options.do_cell_matching = True
    opts.images_scale = 1.0
    ocr = DocumentConverter(format_options={InputFormat.IMAGE: ImageFormatOption(pipeline_options=opts)})
    plain = PdfPipelineOptions()
    plain.do_ocr = False
    plain.do_table_structure = True
    # 既定のバックエンドは一部の PDF で英数字を取り出せないので、pdfium を使う
    text = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=plain, backend=PyPdfiumDocumentBackend)})
    return Engines(ocr=ocr, text=text, collector=collector, forms=FormReader(ndlocr_src, glossary=terms, grid=grid, forms=forms) if use_forms else None, drawings=drawings, figures=figures)


@dataclass
class FileOutput:
    """1 ファイル分の出力をためる。"""

    header: str
    pages_md: list[str] = field(default_factory=list)
    pages: list[dict] = field(default_factory=list)  # ページの統計
    labels: dict = field(default_factory=dict)  # 要素の種類ごとの数
    status: set = field(default_factory=set)
    strikes: list[dict] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    forms: list[dict] = field(default_factory=list)
    terms: list[dict] = field(default_factory=list)  # 用語集との照合 (補正したものと、候補)
    figures: FigureWriter | None = None  # 図や写真の切り出し先 (切り出さない場合は None)

    def add_terms(self, page_no: int, terms: dict):
        self.terms += [{"page": page_no, "applied": True, **t} for t in terms["fixes"]] + [{"page": page_no, "applied": False, **t} for t in terms["suggestions"]]

    def count(self, doc):
        for item, _ in doc.iterate_items():
            key = str(item.label.value)
            self.labels[key] = self.labels.get(key, 0) + 1

    def write(self, out: Path, name: str, meta: dict):
        (out / f"{name}.md").write_text(self.header + "\n\n" + "\n\n<!-- page -->\n\n".join(self.pages_md), encoding="utf-8")
        dump = lambda suffix, obj: (out / f"{name}.{suffix}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        if self.pages:
            dump("strike", self.strikes)
        if self.forms:
            dump("form_review", self.forms)
        if self.checks:
            dump("checkbox", self.checks)
        if self.terms:
            dump("glossary", self.terms)
        dump("meta", meta | {"status": sorted(self.status), "items": self.labels, "garbage_dropped": sum(p.get("garbage", 0) for p in self.pages),
                             "figures": self.figures.saved if self.figures else [], "pages": self.pages})  # fmt: skip


def parse_pages(spec: str | None):
    if not spec:
        return None
    a, _, b = spec.partition("-")
    return (int(a), int(b or a))


def text_form_pages(src: str, first: int, last: int, forms: form_defs.FormDefs) -> dict[int, dict]:
    """テキスト層のある PDF のうち、欄単位の帳票として読めたページ ({ページ番号: 帳票の読み取り結果})。"""
    found = {}
    if not forms.regions:
        return found
    with pdfplumber.open(src) as pdf, tempfile.TemporaryDirectory() as tmp:
        for pno in range(first, min(last, len(pdf.pages)) + 1):
            page = pdf.pages[pno - 1]
            if not textlayer.ruled(page):
                continue
            img = np.array(Image.open(render_page(src, pno, Path(tmp) / f"p{pno:04d}.png")).convert("RGB"))
            form = read_text_form(img, textlayer.lines_of(page), forms=forms)
            if form is not None:
                found[pno] = form
    return found


def pdf_cropper(src: str, figures: FigureWriter):
    """テキスト層のある PDF の図を切り出す関数を返す。範囲は PDF の座標 (ポイント、左上原点)。"""
    shown: dict[int, Image.Image] = {}  # 直前に描画したページだけを持つ

    def crop(page_no: int, b) -> str | None:
        if page_no not in shown:
            shown.clear()
            with tempfile.TemporaryDirectory() as tmp:
                shown[page_no] = Image.open(render_page(src, page_no, Path(tmp) / "page.png")).convert("RGB")
        k = DPI / 72
        return figures.crop(shown[page_no], page_no, (b.l * k, b.t * k, b.r * k, b.b * k))

    return crop


def read_text_pdf(engines: Engines, src: str, pages: tuple[int, int] | None, output: FileOutput, out: Path, name: str, page_count: int, ocr_pages: list[int] = ()):
    """テキスト層をそのまま使う。ocr_pages (テキスト層のないページ) だけは OCR する。

    帳票のページは docling の読み順だと隣り合う欄の行が混ざるので、欄単位で読む。
    """
    first, last = pages or (1, page_count)
    ocr_pages = [p for p in ocr_pages if first <= p <= last]
    forms = text_form_pages(src, first, last, engines.forms.forms) if engines.forms is not None else {}
    crop = pdf_cropper(src, output.figures) if output.figures else None
    if not forms and not ocr_pages:
        kw = {"page_range": pages} if pages else {}
        res = engines.text.convert(src, raises_on_error=False, **kw)
        output.pages_md.append(export.text_markdown(res.document, src, crop))
        output.count(res.document)
        output.status.add(str(res.status.value))
        return
    (out / "json").mkdir(exist_ok=True)
    for pno in range(first, last + 1):
        if pno in forms:
            record_form(output, pno, forms[pno], out / "json" / f"{name}.p{pno:04d}.form.json")
            continue
        if pno in ocr_pages:
            read_image_page(engines, src, pno, output, out, name)
            continue
        res = engines.text.convert(src, raises_on_error=False, page_range=(pno, pno))
        output.pages_md.append(f"<!-- p.{pno} -->\n\n{export.text_markdown(res.document, src, crop)}")
        output.count(res.document)
        output.status.add(str(res.status.value))


def record_form(output: FileOutput, page_no: int, form: dict, json_path: Path):
    """帳票として読んだページを、出力に加える。"""
    output.pages_md.append(export.form_page(page_no, form))
    json_path.write_text(json.dumps(form["data"], ensure_ascii=False, default=str), encoding="utf-8")
    terms = form.get("glossary") or {"fixes": [], "suggestions": []}
    output.pages.append({"page": page_no, "form": form["form"], "form_items": form["items"], "form_review": len(form["review"]), **EMPTY_STATS, "lines": form["items"],
                         "glossary_fixes": len(terms["fixes"]), "glossary_suggestions": len(terms["suggestions"])})  # fmt: skip
    output.add_terms(page_no, terms)
    output.forms += [{"page": page_no, "form": form["form"], "value": v} for v in form["review"]]
    output.labels[f"form:{form['form']}"] = output.labels.get(f"form:{form['form']}", 0) + 1
    output.status.add("success")


def read_form_page(engines: Engines, img_path: Path, page_no: int, output: FileOutput, json_path: Path) -> bool:
    """罫線の帳票なら帳票として読む (定義済みの帳票か、定義のない罫線の帳票)。表の構造を推定するより、項目と値の対応が確か。"""
    form = engines.forms.read(np.array(Image.open(img_path).convert("RGB"))) if engines.forms else None
    if form is None:
        return False
    record_form(output, page_no, form, json_path)
    return True


def read_ocr_page(engines: Engines, img_path: Path, page_no: int, output: FileOutput, json_path: Path):
    """ページ画像を docling と NDLOCR-Lite で読む。"""
    engines.collector.results.clear()
    res = engines.ocr.convert(img_path, raises_on_error=False)
    doc = res.document
    # 1 ページ 1 文書として処理しているので、文書内のページ番号は常に 1
    result = engines.collector.results.get(1) or PageResult(stats=dict(EMPTY_STATS))
    stats = {"page": page_no, **result.stats}
    whole = drawing.is_drawing(stats)  # ページのほとんどが図や写真
    page_img = Image.open(img_path).convert("RGB") if output.figures else None
    crop = None
    if output.figures and not whole and 1 in doc.pages:
        k = page_img.width / doc.pages[1].size.width  # docling の座標から、ページ画像の画素へ
        crop = lambda _, b: output.figures.crop(page_img, page_no, (b.l * k, b.t * k, b.r * k, b.b * k))
    md = f"{export.page_header(page_no, stats)}\n\n{export.ocr_markdown(doc, {1: result.lines}, crop)}{export.review_notes(page_no, result)}"
    if output.figures and whole:
        # 図の領域ごとに切ると図面がばらばらになるので、ページ全体を 1 枚の画像にする
        md += "\n\n" + output.figures.page(page_img, page_no)
    if engines.drawings and whole:
        # 図面は NDLOCR-Lite ではほとんど読めないので、Vision の読み取りを参考として足す
        drawn = drawing.read(np.array(Image.open(img_path).convert("RGB")))
        md += "\n\n" + drawing.to_markdown(page_no, drawn)
        stats |= {"drawing": True, "drawing_lines": len(drawn["lines"]) if drawn else None, "drawing_rotation": drawn["rotation"] if drawn else None}
        if drawn:
            json_path.with_suffix(".drawing.json").write_text(json.dumps(drawn, ensure_ascii=False), encoding="utf-8")
    output.pages_md.append(md)
    output.checks += [{"page": page_no, **it} for it in result.checks["items"]] + [{"page": page_no, "review": True, **it} for it in result.checks["review"]]
    output.strikes += [{"page": page_no, "certain": False, **it} for it in result.strike_review]
    output.add_terms(page_no, result.glossary)
    output.strikes += [{"page": page_no, "reason": "取り消し線 (行全体)", "text": l["text"], "certain": True} for l in result.lines if l["struck"] == "all"]
    # 行の一部の取り消しのうち、範囲が確定したもの (確定しなかったものは、要確認として上で足している)
    unsure = {tuple(it["box"]) for it in result.strike_review}
    output.strikes += [{"page": page_no, "reason": "取り消し線 (行の一部)", "text": l["text"], "struck": " / ".join(re.findall(r"(?<!\\)~~(.+?)(?<!\\)~~", l["md"])), "certain": True}
                       for l in result.lines if l["struck"] == "part" and tuple(l["box"]) not in unsure]  # fmt: skip
    json_path.write_text(json.dumps(doc.export_to_dict(), ensure_ascii=False), encoding="utf-8")
    output.count(doc)
    output.pages.append(stats | {"figures": sum(f["page"] == page_no for f in output.figures.saved) if output.figures else 0})
    output.status.add(str(res.status.value))


def read_image_page(engines: Engines, src: str, page_no: int, output: FileOutput, out: Path, name: str, quicklook: bool = False):
    """PDF の 1 ページを画像にして読む。帳票なら帳票として、それ以外は OCR で読む。"""
    with tempfile.TemporaryDirectory() as tmp:
        img = render_page(src, page_no, Path(tmp) / f"p{page_no:04d}.png", quicklook)
        if not read_form_page(engines, img, page_no, output, out / "json" / f"{name}.p{page_no:04d}.form.json"):
            read_ocr_page(engines, img, page_no, output, out / "json" / f"{name}.p{page_no:04d}.json")


def process_file(engines: Engines, src: str, out: Path, name: str, pages: tuple[int, int] | None = None, force_ocr: bool = False):
    """1 ファイルを読み、Markdown と JSON を out に書き出す。"""
    t0 = time.time()
    is_image = route.is_image_file(src)
    info = {"kind": route.IMAGE, "pages": 1, "page_kinds": {}, "ocr_pages": []} if is_image else route.classify(src)
    kind = route.IMAGE if force_ocr and info["kind"] == route.TEXT else info["kind"]
    meta = {"source": str(src), "route": kind, "route_label": route.KIND_LABEL[kind], "page_kinds": info["page_kinds"]}
    figures = FigureWriter(out, name) if engines.figures else None
    finish = lambda output: output.write(out, name, meta | {"seconds": round(time.time() - t0, 1)})

    if kind == route.TEXT:
        # テキスト層のないページが混ざっていれば、そのページだけ OCR する
        mixed = f" ({len(info['ocr_pages'])} ページはテキスト層を使えないため OCR: p." + ",".join(map(str, info["ocr_pages"])) + ")" if info["ocr_pages"] else ""
        output = FileOutput(header=f"<!-- 経路: {route.KIND_LABEL[kind]}{mixed} -->", figures=figures)
        meta["ocr_pages"] = info["ocr_pages"]
        read_text_pdf(engines, src, pages, output, out, name, info["pages"], info["ocr_pages"])
        finish(output)
        print(f"{name}: {kind} {sorted(output.status)} {round(time.time() - t0, 1)}s items={output.labels}", flush=True)
        return

    first, last = pages or (1, info["pages"])
    # 文字化け PDF は Quick Look で描画する (1 ページの PDF で、macOS の場合だけ使える)
    quicklook = kind == route.GARBLED and info["pages"] == 1 and platform.system() == "Darwin" and shutil.which("qlmanage") is not None
    output = FileOutput(header=f"<!-- 経路: {route.KIND_LABEL[kind]}" + (" (Quick Look で描画)" if quicklook else "") + " -->", figures=figures)
    (out / "json").mkdir(exist_ok=True)
    for pno in range(first, last + 1):
        if is_image:
            if not read_form_page(engines, Path(src), pno, output, out / "json" / f"{name}.p{pno:04d}.form.json"):
                read_ocr_page(engines, Path(src), pno, output, out / "json" / f"{name}.p{pno:04d}.json")
        else:
            read_image_page(engines, src, pno, output, out, name, quicklook)
        if pno % 10 == 0:
            print(f"  {name} p{pno}/{last} {round(time.time() - t0)}s", flush=True)
    finish(output)
    garbage = sum(p.get("garbage", 0) for p in output.pages)
    print(f"{name}: {kind} {sorted(output.status)} {round(time.time() - t0, 1)}s pages={len(output.pages)} items={output.labels} garbage={garbage}", flush=True)


def prepare_glossary(path: str | None, root: str | None, out: Path, disabled: bool = False) -> glossary.Glossary | None:
    """OCR を始める前に用語集を用意する。

    指定があればそれを読む。なければ、入力のルートにある OCR が要らないファイル (テキスト層を使える PDF、Word、Excel)
    とファイル名から作り、出力先に書き出す。すでに書き出してあれば、それを使う (人が直した内容を保つ)。
    """
    if disabled:
        return None
    if path is None:
        if root is None:
            return None
        path = out / "glossary.tsv"
        if not Path(path).exists():
            rows = glossary.build(root, log=lambda m: print(m, flush=True))
            glossary.save(rows, path)
            print(f"用語集: {len(rows)} 語を {path} に書き出しました", flush=True)
    terms = glossary.Glossary(glossary.load(path))
    print(f"用語集: {path} の {len(terms)} 語と照らし合わせます", flush=True)
    return terms


def run(engines: Engines, inputs: list[str], base: Path, root: str | None = None, name: str | None = None, pages: tuple[int, int] | None = None, force_ocr: bool = False) -> list[str]:
    """入力を順に読み、base に書き出す。読めなかった入力の一覧を返す。

    root を指定すると、base の下に root からの相対パスのフォルダ構成を再現する。
    出力済みのファイルは飛ばす (pages を指定した場合を除く)。
    """
    failed = []
    for src in inputs:
        out = base / Path(src).parent.relative_to(root) if root else base
        out.mkdir(parents=True, exist_ok=True)
        stem = name or Path(src).stem
        if (out / f"{stem}.md").exists() and not pages:
            print(f"{stem}: skip (done)", flush=True)
            continue
        try:
            process_file(engines, src, out, stem, pages, force_ocr)
        except Exception as e:  # 1 ファイルの失敗で全体を止めない
            print(f"FAILED {src}: {e!r}", flush=True)
            failed.append(src)
    return failed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ndlocr-src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pages")
    ap.add_argument("--name")
    ap.add_argument("--root", help="入力のルート。指定すると出力先に相対パスのフォルダ構成を再現する")
    ap.add_argument("--list", help="入力ファイルを 1 行 1 パスで列挙したファイル")
    ap.add_argument("--force-ocr", action="store_true", help="テキスト層が使える PDF も OCR する")
    ap.add_argument("--no-forms", action="store_true", help="帳票と判定したページも、帳票として読まない")
    ap.add_argument("--forms", help="帳票の定義 (JSON)。見出しの語と値の型が分かっている帳票を、定義に沿って読む")
    ap.add_argument("--no-grid", action="store_true", help="定義のない罫線の帳票 (測定記録など) を、セル単位で読まない (通常の経路で読む)")
    ap.add_argument("--no-drawings", action="store_true", help="図面のページを macOS の Vision で読まない")
    ap.add_argument("--no-figures", action="store_true", help="図や写真を画像に切り出さない")
    ap.add_argument("--glossary", help="用語集 (TSV)。省略すると、--root があればその中の OCR が要らないファイルから作り、出力先に glossary.tsv として書き出す")
    ap.add_argument("--no-glossary", action="store_true", help="用語集を作らず、照合もしない")
    ap.add_argument("inputs", nargs="*")
    a = ap.parse_args(argv)

    base = Path(a.out)
    base.mkdir(parents=True, exist_ok=True)
    engines = build_engines(a.ndlocr_src, use_forms=not a.no_forms, drawings=not a.no_drawings, terms=prepare_glossary(a.glossary, a.root, base, a.no_glossary), figures=not a.no_figures, grid=not a.no_grid, forms=form_defs.load(a.forms))
    inputs = a.inputs + ([l for l in Path(a.list).read_text(encoding="utf-8").splitlines() if l.strip()] if a.list else [])
    return 1 if run(engines, inputs, base, a.root, a.name, parse_pages(a.pages), a.force_ocr) else 0


if __name__ == "__main__":
    raise SystemExit(main())
