"""取り消し線を Markdown の ``~~…~~`` で表すための共通処理。"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 取り消しの種類
STRIKE = "strike"  # 取り消し線 (Word の w:strike、PDF の線・注釈)
DSTRIKE = "dstrike"  # 二重取り消し線 (Word の w:dstrike)
TRACKED = "tracked"  # 変更履歴による削除 (Word の w:del)
UNCERTAIN = "uncertain"  # 線と文字列の対応が曖昧 (確定扱いにしない)

TRACKED_NOTE = "<!-- 変更履歴による削除 -->"


@dataclass
class Seg:
    """書式が同じひと続きの文字列。kind が None なら通常の文字列。"""

    text: str
    kind: str | None = None


def escape(text: str) -> str:
    """原文に含まれる ``~~`` を、取り消し線の記号と区別できるようにエスケープする。"""
    return text.replace("~~", r"\~\~")


def _wrap(text: str) -> str:
    # Markdown の ~~ は内側の端に空白があると効かないので、端の空白は外に出す
    m = re.match(r"^(\s*)(.*?)(\s*)$", text, flags=re.S)
    lead, core, trail = m.groups()
    return f"{lead}~~{escape(core)}~~{trail}" if core else text


def render(segs: list[Seg]) -> str:
    """Seg の並びを Markdown にする。

    隣り合う取り消し線付き文字列 (一重・二重) は 1 つの ``~~…~~`` につなぐ。
    通常の文字列をまたいでは結合しない。変更履歴による削除は書式の取り消し線と分け、注記を付ける。
    """
    out: list[str] = []
    buf, group = "", None
    for seg in [*segs, Seg("", "__end__")]:
        g = "strike" if seg.kind in (STRIKE, DSTRIKE) else seg.kind
        if g != group:
            if buf:
                if group == "strike":
                    out.append(_wrap(buf))
                elif group == TRACKED:
                    out.append(_wrap(buf) + TRACKED_NOTE)
                else:  # 通常の文字列と、曖昧な箇所 (確定扱いにしない)
                    out.append(escape(buf))
            buf, group = "", g
        buf += seg.text
    return "".join(out)


def merge_adjacent(md: str) -> str:
    """行ごとに付けた ``~~A~~ ~~B~~`` を ``~~A B~~`` につなぐ (OCR の行を段落にまとめた後に使う)。"""
    return re.sub(r"(?<!\\)~~( ?)~~(?!~)", r"\1", md)
