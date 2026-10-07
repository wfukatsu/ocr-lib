"""人が確認すべきページと値を、1 つの一覧にまとめる。

構造化 OCR の出力フォルダから、未読領域のあるページ、行検出が崩壊したページ、範囲が推定の
取り消し線、判定が不確かなチェック欄、確定できなかった帳票の値を集める。

usage:
  dococr-review <出力フォルダ> [-o review.md] [--csv review.csv]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from .config import MIN_INK_COVERED

KINDS = {
    "unread": "未読領域",
    "collapsed": "行検出の崩壊",
    "strike": "取り消し線",
    "checkbox": "チェック欄",
    "form": "帳票の値",
    "drawing": "図・写真",
    "glossary": "用語集との照合",
    "failed": "処理の失敗",
}


def _load(path: Path) -> list:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def collect(out_dir: str | Path) -> list[dict]:
    """確認が必要な箇所を {"file", "page", "kind", "detail"} の一覧で返す。"""
    out_dir = Path(out_dir)
    rows: list[dict] = []
    for meta_path in sorted(out_dir.rglob("*.meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        stem = meta_path.name[: -len(".meta.json")]
        name = str(meta_path.parent.relative_to(out_dir) / stem)
        add = lambda page, kind, detail: rows.append({"file": name, "page": page, "kind": kind, "detail": detail})
        if any(s != "success" for s in meta.get("status", [])):
            add(0, "failed", "変換の状態: " + ", ".join(meta["status"]))
        for p in meta.get("pages", []):
            if p.get("page_collapsed"):
                add(p["page"], "collapsed", "行検出が崩壊したため分割して読み直した")
            cov = p.get("ink_covered")
            if cov is not None and cov < MIN_INK_COVERED:
                add(p["page"], "unread", f"文字領域のインクのうち行として読めたのは {round(cov * 100)}%")
            if p.get("drawing"):
                n = p.get("drawing_lines")
                add(p["page"], "drawing", "図・写真が主のページ。図の中の文字は読んでいない (画像のまま扱う)" if n is None else f"図・写真が主のページ。図の中の文字は参考の読み取り ({n} 行)。寸法などの数字は原本で確かめる")
        base = meta_path.parent / stem
        for r in _load(Path(f"{base}.strike.json")):
            # 行に対応しない線は罫線や印影のことが多いので、候補の文字列があるものだけを挙げる
            if not r.get("certain") and r.get("candidate"):
                add(r["page"], "strike", f"{r['reason']}: {r['candidate']}")
        for r in _load(Path(f"{base}.checkbox.json")):
            if r.get("review"):
                add(r["page"], "checkbox", f"{r['reason']}: {r.get('text') or '(行を読めていない)'}")
        for r in _load(Path(f"{base}.glossary.json")):
            if not r.get("applied"):  # 書き換えずに候補として挙げたもの
                add(r["page"], "glossary", f"用語集に 1 文字違いの語がある: {r['from']} → {r['to']}")
        for r in _load(Path(f"{base}.form_review.json")):
            add(r["page"], "form", f"{r['form']}: {r['value']}")
    return sorted(rows, key=lambda r: (r["file"], r["page"], r["kind"]))


def summarize(rows: list[dict]) -> dict:
    return {"total": len(rows), "by_kind": dict(Counter(r["kind"] for r in rows)), "files": len({r["file"] for r in rows}), "pages": len({(r["file"], r["page"]) for r in rows})}


def to_markdown(rows: list[dict]) -> str:
    s = summarize(rows)
    out = ["# 確認が必要な箇所", "", f"{s['files']} ファイル・{s['pages']} ページに、{s['total']} 件あります。", "", "| 種類 | 件数 |", "| --- | --- |"]
    out += [f"| {KINDS[k]} | {s['by_kind'][k]} |" for k in KINDS if k in s["by_kind"]]
    cur = None
    for r in rows:
        if r["file"] != cur:
            cur = r["file"]
            out += ["", f"## {cur}", "", "| ページ | 種類 | 内容 |", "| --- | --- | --- |"]
        detail = r["detail"].replace("|", r"\|").replace("\n", " ")
        out.append(f"| {r['page'] or '-'} | {KINDS[r['kind']]} | {detail} |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_dir")
    ap.add_argument("-o", "--output", help="Markdown の出力先 (省略時は標準出力)")
    ap.add_argument("--csv", help="CSV の出力先")
    a = ap.parse_args(argv)
    rows = collect(a.out_dir)
    md = to_markdown(rows)
    if a.output:
        Path(a.output).write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md)
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["file", "page", "kind", "detail"])
            w.writeheader()
            w.writerows({**r, "kind": KINDS[r["kind"]]} for r in rows)
    s = summarize(rows)
    print(f"確認が必要な箇所: {s['total']} 件 ({s['files']} ファイル・{s['pages']} ページ)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
