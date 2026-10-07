"""帳票の欄抽出の結果を検証し、要確認を減らす。

OCR エンジン間の食い違いをそのまま要確認にすると、固定の見出しや連番でも付いてしまい、
人が確認できる量にならない。帳票について分かっていること (連番、見出しの語、値の型) と、
3 つ目のエンジンによる多数決で確定できるものを確定させ、本当に不確かな値だけを残す。

確定させたセルには "by" に理由を入れ、元の読み取り結果 ("ndl"、"alt") は残す。
"""
from __future__ import annotations

import difflib
import re
from collections import Counter

import numpy as np

from . import crosscheck
from .crosscheck import settle
from .textutil import norm


def fix_sequences(rows: list[list[dict]], min_run: int = 5) -> int:
    """行の先頭に連番 (01, 02, …) が並ぶ列を見つけ、位置から番号を確定させる。確定させた数を返す。

    位置から決めた番号を採るのは、どれかのエンジンがその番号を読んでいる行と、読みが確定しておらず
    前後の行が連番に合っている行だけ。どのエンジンも別の番号を読んで確定している行は、欠番で番号が
    飛んでいるかもしれないので書き換えない。
    """
    num = lambda c: [int(v) for v in (norm(c.get("text")), norm(c.get("ndl")), norm(c.get("alt"))) if re.fullmatch(r"\d{1,3}", v)]
    fixed, i = 0, 0
    while i < len(rows):
        j = i
        x0 = rows[i][0]["cell"][0] if rows[i] else None
        # 同じセル列で、数字らしい読み取りが続く範囲
        while j < len(rows) and rows[j] and rows[j][0]["cell"][0] == x0 and num(rows[j][0]):
            j += 1
        if j - i >= min_run:
            # 各行の読み取りから「先頭の番号」の候補を出し、多数決で決める
            votes = Counter(v - k for k, r in enumerate(rows[i:j]) for v in set(num(r[0])))
            start, support = votes.most_common(1)[0]
            if support >= 0.5 * (j - i):
                width = Counter(len(norm(r[0].get(key))) for r in rows[i:j] for key in ("ndl", "alt") if re.fullmatch(r"\d+", norm(r[0].get(key)))).most_common(1)[0][0]
                fits = [start + k in num(r[0]) for k, r in enumerate(rows[i:j])]  # どれかのエンジンが、位置どおりの番号を読んでいる
                for k, r in enumerate(rows[i:j]):
                    around = fits[max(k - 1, 0) : k] + fits[k + 1 : k + 2]
                    if not (fits[k] or (not r[0]["certain"] and around and all(around))):
                        continue
                    want = str(start + k).zfill(width)
                    if not r[0]["certain"] or norm(r[0]["text"]) != want:
                        fixed += 1
                    settle(r[0], want, "sequence")
        i = max(j, i + 1)
    return fixed


def match_label(cell: dict, labels: list[str]) -> str | None:
    """セルの読み取りが見出しの語に当たるなら、その語を返す。"""
    reads = [norm(cell.get(k)) for k in ("text", "ndl", "alt") if cell.get(k)]
    best, score = None, 0.0
    for lab in labels:
        n = norm(lab)
        for r in reads:
            # 2 文字以下の見出しは、あいまいな一致を認めない
            s = 1.0 if r == n else (difflib.SequenceMatcher(None, r, n).ratio() if len(n) > 2 and abs(len(r) - len(n)) <= 2 else 0.0)
            if s > score:
                best, score = lab, s
    return best if score >= 0.8 else None


def detect_form(rows: list[list[dict]], forms=()) -> dict | None:
    """forms (セルごとに値が入る帳票の定義) のうち、見出しの語が十分に見つかったものを返す。"""
    cells = [c for r in rows for c in r]
    for form in forms:
        if sum(match_label(c, form["labels"]) is not None for c in cells) >= form["min_labels"]:
            return form
    return None


def apply_form(rows: list[list[dict]], form: dict) -> tuple[int, int]:
    """見出しの語を辞書で確定させ、型の決まっている値を検証する。(確定させた見出し, 確定させた値) を返す。"""
    n_label = n_type = 0
    for r in rows:
        for i, c in enumerate(r):
            lab = match_label(c, form["labels"])
            if lab is None or c.get("by") == "sequence":
                continue
            if not c["certain"] or norm(c["text"]) != norm(lab):
                n_label += 1
            settle(c, lab, "label")
            pattern = form["types"].get(lab)
            if pattern and i + 1 < len(r):
                v = r[i + 1]
                valid = {norm(v.get(k)) for k in ("text", "ndl", "alt") if v.get(k) and re.fullmatch(pattern, norm(v.get(k)))}
                if len(valid) == 1:
                    if not v["certain"]:
                        n_type += 1
                    settle(v, valid.pop(), "type")
                else:
                    v.update(certain=False, by="type_mismatch")  # 取りうる値のどれにも読めていない
    return n_label, n_type


def verify(rows: list[list[dict]], img: np.ndarray | None = None, use_vision: bool = True, forms=()) -> dict:
    """検証を順に適用し、理由ごとの件数を返す。"""
    stats = {"sequence": fix_sequences(rows)}
    form = detect_form(rows, forms)
    stats["form"] = form["name"] if form else None
    if form:
        stats["label"], stats["type"] = apply_form(rows, form)
    lines = crosscheck.vision_lines(img) if use_vision and img is not None else None
    stats["vote"] = crosscheck.vote(rows, lines) if lines else 0
    stats["items"] = sum(len(r) for r in rows)
    stats["review"] = sum(not c["certain"] for r in rows for c in r)
    return stats
