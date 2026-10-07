"""docling の OCR 段を NDLOCR-Lite に差し替える。

docling の標準パイプラインは layout -> ocr -> layout_postprocess -> table -> assemble の順に動く。
OCR 段では、layout が出した領域を手がかりに行を見直し、チェック欄と取り消し線を判定する。
ページごとの結果は、呼び出し側が用意した PageCollector に入れる。
"""
from __future__ import annotations

import re
import uuid
from typing import ClassVar, Iterable, Literal

import numpy as np
from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell

from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import Page
from docling.datamodel.document import ConversionResult
from docling.datamodel.pipeline_options import OcrMode, OcrOptions
from docling.models.base_ocr_model import BaseOcrModel
from docling.models.factories import get_ocr_factory

from . import checkbox, strike_image
from .config import DPI
from .line_ocr import PageLineOcr, ink_covered, overlap
from .types import Line, PageResult

FIGURE_LABELS = {"picture", "chart"}  # 欠落の指標で、インクを数えない領域
REDO_LABELS = {"table", "picture", "form", "key_value_region", "document_index", "chart"}  # 領域単位で読み直す領域
MAX_PX = 12000  # ページ画像の長辺の上限


class PageCollector:
    """OCR 段がページごとの結果を入れる入れ物。変換 1 回ごとに呼び出し側が作る。"""

    def __init__(self, dpi: float = DPI, glossary=None):
        self.dpi = dpi
        self.glossary = glossary  # 用語集 (glossary.Glossary)。None なら照合しない
        self.results: dict[int, PageResult] = {}  # docling の文書内のページ番号 -> 結果


# docling はパイプラインの設定を値として持ち回るので、入れ物そのものは設定に入れられない。
# 設定には ID だけを入れ、OCR 段がここから引く。
_COLLECTORS: dict[str, PageCollector] = {}


def register_collector(collector: PageCollector) -> str:
    cid = uuid.uuid4().hex
    _COLLECTORS[cid] = collector
    return cid


class NdlOcrLiteOptions(OcrOptions):
    kind: ClassVar[Literal["ndlocr_lite"]] = "ndlocr_lite"
    canonicalize_lang: ClassVar[bool] = False
    lang: list[str] = []
    ndlocr_src: str = ""
    collector_id: str = ""
    mode: OcrMode = OcrMode.FULL_PAGE  # PDF 由来のテキスト層は使わず OCR 結果だけを採用する


def register_engine():
    """docling に OCR エンジンとして登録する。"""
    factory = get_ocr_factory(allow_external_plugins=False)
    if NdlOcrLiteOptions not in factory.classes:
        factory.register(NdlOcrLiteModel, "ndlocr_lite", __name__)


def _px(bbox, scale: float) -> tuple[int, int, int, int]:
    return tuple(int(v * scale) for v in (bbox.l, bbox.t, bbox.r, bbox.b))


def refine_with_layout(ocr: PageLineOcr, page_img: np.ndarray, lines: list[Line], regions: list[tuple[str, tuple]]) -> tuple[list[Line], int]:
    """layout の領域ごとに行を見直す。表・図・帳票と、行が取れていない領域は領域単位で読み直す。

    regions は (領域の種類, 画素の範囲)。読み直した結果が良ければ置き換え、(行, 置き換えた領域の数) を返す。
    """
    H, W = page_img.shape[:2]
    score = lambda ls: sum(len(l["text"]) * l["conf"] for l in ls)
    redo = 0
    for label, box in sorted(regions, key=lambda r: (r[1][2] - r[1][0]) * (r[1][3] - r[1][1])):
        if (box[2] - box[0]) * (box[3] - box[1]) > 0.9 * W * H:
            continue
        inside = [ln for ln in lines if box[0] <= (ln["box"][0] + ln["box"][2]) / 2 <= box[2] and box[1] <= (ln["box"][1] + ln["box"][3]) / 2 <= box[3]]
        # 既にある行と重なっている領域は読めているとみなす (行の断片だけを読み直して重複させない)
        covered = any(overlap(ln["box"], box) >= 0.3 for ln in lines)
        if not (label in REDO_LABELS or not (inside or covered)):
            continue
        region = ocr.ocr_region(page_img, box)
        if label not in REDO_LABELS:  # 読み残しの補完では、数字だけの断片を採用しない
            region = [r for r in region if len(r["text"]) > 2 and not re.fullmatch(r"[\d.\s]+", r["text"])]
        if score(region) > score(inside) * 1.05:
            ids = {id(l) for l in inside}
            lines = [l for l in lines if id(l) not in ids and not any(overlap(l["box"], r["box"]) > 0.5 and overlap(r["box"], l["box"]) > 0.5 for r in region)] + region
            redo += 1
    return lines, redo


def read_page(ocr: PageLineOcr, page_img: np.ndarray, regions: list[tuple[str, tuple]], dpi: float, glossary=None) -> PageResult:
    """ページ画像を読み、行・チェック欄・取り消し線の結果を返す。行の box は画素。"""
    # 取り消し線は OCR の前に検出して消す (線が残ると行検出が崩壊し、文字も誤読する)
    strikes = strike_image.detect(page_img, dpi=round(dpi))
    page_img = strike_image.erase(page_img, strikes)
    figures = [box for label, box in regions if label in FIGURE_LABELS]
    g0 = ocr.garbage
    # 1) ページ全体を OCR して基準の行を得る (読めた割合が低ければ分割して読み直す)
    lines, collapsed = ocr.read_page(page_img, dpi, figures)
    # 2) layout の領域ごとに見直す
    lines, redo = refine_with_layout(ocr, page_img, lines, regions)
    # 3) チェック欄 (□ / ■) を画像から判定し、読み落とした行を補う
    checks = checkbox.process(page_img, lines, reread=ocr.ocr_region, dpi=round(dpi))
    # 4) 用語集と照らし合わせ、紛らわしい文字の取り違えを補正する
    terms = glossary.apply(lines) if glossary is not None else {"fixes": [], "suggestions": []}
    # 5) 取り消し線を行に対応づける。表・図・帳票の中のものは確定にしない
    review = strike_image.mark_lines(lines, strikes, reread=lambda box: ocr.read_strip(page_img, box))
    strike_image.demote_in_regions(lines, [box for label, box in regions if label in REDO_LABELS], review, tables=[box for label, box in regions if label == "table"])
    cov = ink_covered(page_img, lines, figures, dpi)
    stats = {
        "regions": len(regions), "lines": len(lines), "regions_reocr": redo, "page_collapsed": collapsed, "garbage": ocr.garbage - g0,
        "ink_covered": None if cov is None else round(cov, 2),
        "checkboxes": len(checks["items"]), "checkbox_review": len(checks["review"]), "checkbox_recovered": checks["recovered"],
        "strike_lines": len(strikes), "struck": sum(l["struck"] is not None for l in lines), "strike_review": len(review),
        "low_conf": sum(l["conf"] < 0.5 for l in lines), "glossary_fixes": len(terms["fixes"]), "glossary_suggestions": len(terms["suggestions"]),
    }  # fmt: skip
    return PageResult(stats=stats, lines=lines, strike_review=review, checks=checks, glossary=terms)


class NdlOcrLiteModel(BaseOcrModel):
    def __init__(self, enabled, artifacts_path, options: NdlOcrLiteOptions, accelerator_options: AcceleratorOptions):
        super().__init__(enabled=enabled, artifacts_path=artifacts_path, options=options, accelerator_options=accelerator_options)
        if not self.enabled:
            return
        self.ocr = PageLineOcr(options.ndlocr_src)
        self.collector = _COLLECTORS.get(options.collector_id) or PageCollector()

    @classmethod
    def get_options_type(cls):
        return NdlOcrLiteOptions

    def __call__(self, conv_res: ConversionResult, page_batch: Iterable[Page]) -> Iterable[Page]:
        if not self.enabled:
            yield from page_batch
            return
        for page in page_batch:
            if page._backend is None or not page._backend.is_valid():
                yield page
                continue
            # 入力は 1 ページ 1 画像。docling は画像の 1 画素を 1 単位として扱うので、等倍で取り出す
            scale = min(1.0, MAX_PX / max(page.size.width, page.size.height))
            page_img = np.array(page._backend.get_page_image(scale=scale).convert("RGB"))
            clusters = page.predictions.layout.clusters if page.predictions.layout else []
            regions = [(str(c.label.value), _px(c.bbox, scale)) for c in clusters]
            result = read_page(self.ocr, page_img, regions, self.collector.dpi * scale, self.collector.glossary)
            cells = []
            for i, ln in enumerate(result.lines):
                l, t, r, b = (v / scale for v in ln["box"])
                rect = BoundingRectangle.from_bounding_box(BoundingBox.from_tuple(coord=(l, t, r, b), origin=CoordOrigin.TOPLEFT))
                cells.append(TextCell(index=i, text=ln["md"], orig=ln["md"], from_ocr=True, confidence=ln["conf"], rect=rect))
            # 呼び出し側には、docling のページ座標にそろえた行を渡す
            result.lines = [{**ln, "box": tuple(v / scale for v in ln["box"])} for ln in result.lines]
            self.collector.results[page.page_no] = result
            self.post_process_cells(cells, page, conv_res)
            yield page
