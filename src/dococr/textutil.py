"""文字列と行の並びの共通処理。"""
from __future__ import annotations

import unicodedata
from typing import Callable


def norm(s: str | None) -> str:
    """照合用に、全角・半角をそろえて空白を除く。"""
    return unicodedata.normalize("NFKC", s or "").replace(" ", "").replace("　", "")


def group_rows(items: list[dict]) -> list[list[dict]]:
    """同じ高さの項目 ("box" を持つ辞書) を 1 行にまとめ、行は上から、行の中は左から並べる。"""
    rows: list[list[dict]] = []
    first: list[tuple[float, float]] = []  # 各行の最初の項目の (中心の高さ, 高さ)
    for it in sorted(items, key=lambda i: (i["box"][1] + i["box"][3]) / 2):
        cy, h = (it["box"][1] + it["box"][3]) / 2, it["box"][3] - it["box"][1]
        if rows and abs(cy - first[-1][0]) < 0.6 * min(h, first[-1][1]):
            rows[-1].append(it)
        else:
            rows.append([it])
            first.append((cy, h))
    return [sorted(r, key=lambda i: i["box"][0]) for r in rows]


def join_rows(items: list[dict], show: Callable[[dict], str], sep: str = "\n") -> str:
    """同じ高さの項目を ` | ` でつないだ行を、sep で並べた文字列にする。"""
    return sep.join(" | ".join(show(i) for i in row) for row in group_rows(items))
