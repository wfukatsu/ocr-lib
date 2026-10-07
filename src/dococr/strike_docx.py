"""Word (.docx) から取り消し線付きの文字列を抽出し、Markdown にする。

取り消し線は run の書式 (w:strike / w:dstrike) として、変更履歴による削除は w:del として
保存されている。両者を区別して扱う。文書に埋め込まれた画像は、取り出して Markdown から参照する。
"""
from __future__ import annotations

import posixpath
import re
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .convert import to_modern
from .figures import FigureWriter
from .mdutil import DSTRIKE, STRIKE, TRACKED, Seg, render

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
# 画像への参照: DrawingML の a:blip (r:embed) と、旧来の VML の v:imagedata (r:id)
IMAGE_REFS = {"{http://schemas.openxmlformats.org/drawingml/2006/main}blip": R + "embed", "{urn:schemas-microsoft-com:vml}imagedata": R + "id"}
OFF = {"0", "false", "off"}


def _rels(z: zipfile.ZipFile, part: str) -> dict[str, str]:
    """part (word/document.xml など) の関係 ID から、パッケージ内のパスへの対応。"""
    name = f"{posixpath.dirname(part)}/_rels/{posixpath.basename(part)}.rels"
    if name not in z.namelist():
        return {}
    rels = {}
    for el in ET.fromstring(z.read(name)):
        if el.get("TargetMode") != "External":
            rels[el.get("Id")] = posixpath.normpath(posixpath.join(posixpath.dirname(part), el.get("Target", ""))).lstrip("/")
    return rels


def _toggle(rpr: ET.Element | None, tag: str) -> bool | None:
    """rPr 内の on/off 書式を読む。指定がなければ None。"""
    if rpr is None:
        return None
    el = rpr.find(W + tag)
    if el is None:
        return None
    return el.get(W + "val", "true").lower() not in OFF


class _Styles:
    """styles.xml から、スタイルに設定された取り消し線を basedOn をたどって解決する。"""

    def __init__(self, xml: bytes | None):
        self.rpr: dict[str, ET.Element | None] = {}
        self.based: dict[str, str | None] = {}
        self.heading: dict[str, int] = {}
        self.default_rpr: ET.Element | None = None
        if not xml:
            return
        root = ET.fromstring(xml)
        self.default_rpr = root.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr")
        for st in root.findall(W + "style"):
            sid = st.get(W + "styleId")
            self.rpr[sid] = st.find(W + "rPr")
            b = st.find(W + "basedOn")
            self.based[sid] = b.get(W + "val") if b is not None else None
            name = st.find(W + "name")
            m = re.fullmatch(r"heading (\d)", (name.get(W + "val") if name is not None else "").lower())
            if m:
                self.heading[sid] = int(m.group(1))

    def toggle(self, sid: str | None, tag: str) -> bool | None:
        seen = set()
        while sid and sid not in seen:
            seen.add(sid)
            v = _toggle(self.rpr.get(sid), tag)
            if v is not None:
                return v
            sid = self.based.get(sid)
        return None


class _Doc:
    def __init__(self, styles: _Styles, tracked: str):
        self.styles = styles
        self.tracked = tracked  # "mark": 変更履歴の削除も出力して区別する / "skip": 出力しない
        self.found: list[dict] = []
        self.image = lambda rid: None  # 関係 ID から Markdown の画像参照を返す (取り出さない場合は None)

    def _kind(self, run: ET.Element, pstyle: str | None) -> str | None:
        rpr = run.find(W + "rPr")
        rstyle = rpr.find(W + "rStyle") if rpr is not None else None
        rsid = rstyle.get(W + "val") if rstyle is not None else None
        for tag, kind in (("dstrike", DSTRIKE), ("strike", STRIKE)):
            # run の直接指定 > 文字スタイル > 段落スタイル > 文書の既定値
            for v in (_toggle(rpr, tag), self.styles.toggle(rsid, tag), self.styles.toggle(pstyle, tag), _toggle(self.styles.default_rpr, tag)):
                if v is not None:
                    if v:
                        return kind
                    break
        return None

    @staticmethod
    def _text(run: ET.Element) -> str:
        out = []
        for el in run:
            if el.tag in (W + "t", W + "delText"):
                out.append(el.text or "")
            elif el.tag == W + "tab":
                out.append("\t")
            elif el.tag in (W + "br", W + "cr"):
                out.append("\n")
        return "".join(out)

    def _segs(self, node: ET.Element, pstyle: str | None, deleted: bool, segs: list[Seg]):
        for el in node:
            if el.tag == W + "r":
                for ref in el.iter():
                    link = self.image(ref.get(IMAGE_REFS[ref.tag])) if ref.tag in IMAGE_REFS else None
                    if link:
                        segs.append(Seg(link))
                text = self._text(el)
                if not text:
                    continue
                if deleted:
                    if self.tracked == "mark":
                        segs.append(Seg(text, TRACKED))
                else:
                    segs.append(Seg(text, self._kind(el, pstyle)))
            elif el.tag in (W + "del", W + "moveFrom"):
                self._segs(el, pstyle, True, segs)
            elif el.tag not in (W + "pPr", W + "rPr"):  # w:ins, w:hyperlink, w:smartTag, w:sdt など
                self._segs(el, pstyle, deleted, segs)

    def paragraph(self, p: ET.Element, where: str) -> str:
        ps = p.find(f"{W}pPr/{W}pStyle")
        pstyle = ps.get(W + "val") if ps is not None else None
        segs: list[Seg] = []
        self._segs(p, pstyle, False, segs)
        # 隣接する取り消し線付きの run をつないで、抽出結果として記録する
        group, kind, buf = None, None, ""
        for seg in [*segs, Seg("", "__end__")]:
            g = "strike" if seg.kind in (STRIKE, DSTRIKE) else seg.kind
            if g != group:
                if buf.strip() and group:
                    self.found.append({"where": where, "kind": kind, "text": buf})
                group, kind, buf = g, seg.kind, ""
            buf += seg.text
        text = render(segs).replace("\n", "  \n")
        level = self.styles.heading.get(pstyle or "")
        return f"{'#' * level} {text}" if level and text.strip() else text

    def table(self, tbl: ET.Element, where: str) -> str:
        rows = []
        for r, tr in enumerate(tbl.findall(W + "tr"), 1):
            cells = []
            for c, tc in enumerate(tr.findall(W + "tc"), 1):
                parts = [self.paragraph(p, f"{where} 行{r} 列{c}") for p in tc.iter(W + "p")]
                cells.append("<br>".join(t for t in parts if t.strip()).replace("|", r"\|").replace("  \n", "<br>"))
            rows.append(cells)
        if not rows:
            return ""
        n = max(len(r) for r in rows)
        rows = [r + [""] * (n - len(r)) for r in rows]
        lines = ["| " + " | ".join(r) + " |" for r in rows]
        lines.insert(1, "|" + " --- |" * n)
        return "\n".join(lines)

    def blocks(self, container: ET.Element, label: str) -> list[str]:
        out, np_, nt = [], 0, 0
        for el in container:
            if el.tag == W + "p":
                np_ += 1
                out.append(self.paragraph(el, f"{label} 段落{np_}"))
            elif el.tag == W + "tbl":
                nt += 1
                out.append(self.table(el, f"{label} 表{nt}"))
            elif el.tag == W + "sdt":
                content = el.find(W + "sdtContent")
                if content is not None:
                    out += self.blocks(content, label)
        return [b for b in out if b.strip()]


def extract(path: str | Path, tracked: str = "mark", figures: FigureWriter | None = None) -> tuple[str, list[dict]]:
    """.docx / .doc を Markdown にし、(Markdown, 取り消し線の一覧) を返す。

    figures を渡すと、文書に埋め込まれた画像を取り出して、元の位置に画像参照を書く。
    """
    path = Path(path)
    with tempfile.TemporaryDirectory() as tmp:
        path = to_modern(path, tmp)  # 旧形式 .doc は .docx に変換してから読む
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            doc = _Doc(_Styles(z.read("word/styles.xml") if "word/styles.xml" in names else None), tracked)
            parts = [("本文", "word/document.xml")]
            parts += [("ヘッダー", n) for n in sorted(names) if re.fullmatch(r"word/header\d*\.xml", n)]
            parts += [("フッター", n) for n in sorted(names) if re.fullmatch(r"word/footer\d*\.xml", n)]
            out: list[str] = []
            links: dict[str, str] = {}  # 同じ画像を何度使っていても、書き出すのは 1 度

            def image(rels: dict[str, str], rid: str | None) -> str | None:
                target = rels.get(rid)
                if figures is None or target not in names:
                    return None
                if target not in links:
                    links[target] = figures.raw(z.read(target), posixpath.basename(target))
                return links[target]

            for label, name in parts:
                rels = _rels(z, name)
                doc.image = lambda rid, rels=rels: image(rels, rid)
                root = ET.fromstring(z.read(name))
                body = root.find(W + "body") if label == "本文" else root
                blocks = doc.blocks(body, label)
                if blocks and label != "本文":
                    out.append(f"<!-- {label} -->")
                out += blocks
    return "\n\n".join(out) + "\n", doc.found
