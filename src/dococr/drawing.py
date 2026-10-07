"""図面のページの文字を、macOS の Vision で読む。

図面は手書きの文字や横向きの文字が多く、NDLOCR-Lite の行検出ではほとんど読めない。Vision は
向きによらず読めるが、寸法の数字には誤りが混ざる。結果は参考として出し、確定扱いにしない。
図番と名称は、図面の中の表題欄ではなくファイル名や対応表から取る。
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from .crosscheck import vision_read
from .mdutil import escape
from .textutil import join_rows

Reader = Callable[[np.ndarray], "list[tuple[str, float, tuple]] | None"]


def is_drawing(stats: dict) -> bool:
    """ページのほとんどが図や写真 (文字の領域として読めた割合を出せない) なら、図面として扱う。"""
    return stats.get("ink_covered") is None


def read(img: np.ndarray, reader: Reader = vision_read) -> dict | None:
    """{"rotation": 読んだ向き (反時計回りの度数), "lines": [{"text", "box", "conf"}]} を返す。Vision が使えなければ None。

    4 方向で読み、文字が横に並ぶ向きのうち、読めた文字数が最も多いものを採る。上下が逆でも Vision は
    同じように読めるので、逆さまの向きを選ぶことがある (その場合は行の並びが下からになる)。
    """
    best = None
    for k in range(4):
        res = reader(np.ascontiguousarray(np.rot90(img, k)))
        if res is None:
            return None
        lines = [{"text": t, "conf": c, "box": [round(v) for v in box]} for t, c, box in res if t.strip()]
        wide = sum((l["box"][2] - l["box"][0]) >= (l["box"][3] - l["box"][1]) for l in lines)
        key = (wide * 2 >= len(lines), sum(len(l["text"]) for l in lines))
        if best is None or key > best[0]:
            best = (key, {"rotation": k * 90, "lines": lines})
    return best[1]


def to_markdown(page_no: int, res: dict | None) -> str:
    if res is None:
        return f"<!-- 図・写真が主のページ (p.{page_no})。Vision が使えないため図の中の文字は読んでいない。画像のまま扱う -->"
    if not res["lines"]:
        return f"<!-- 図・写真が主のページ (p.{page_no})。図の中の文字は読めなかった -->"
    turned = f"。{res['rotation']} 度回して読んだ" if res["rotation"] else ""
    body = join_rows(res["lines"], lambda l: escape(l["text"]))
    return f"<!-- 要確認 p.{page_no}: 図・写真の中の文字。macOS の Vision による参考の読み取りで、寸法などの数字には誤りが混ざる{turned} -->\n\n```text\n{body}\n```"
