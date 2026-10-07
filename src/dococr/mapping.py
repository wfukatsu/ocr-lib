"""2 つのフォルダのファイルを、ファイル名の先頭にある番号で突き合わせて対応表を作る。

台帳のファイル (1 つの番号に 1 ファイル。機器の仕様書など) と、関連ファイル (図面、取扱説明書など) が対象。
図面の中の表題欄は読めないことが多いので、番号や名称はファイル名から取る。ファイル名には
表記のゆれ (「TD-3A」と「TD3A」)、2 つの番号で 1 ファイル (「XYP1A・B」)、番号のないファイルがあるので、
突き合わせの根拠を状態として残し、推定は確定扱いにしない。

usage:
  dococr-map --items <台帳のフォルダ> --related <関連ファイルのフォルダ> [-o map.md] [--csv map.csv] [--kinds 外形図,構造図]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from pathlib import Path

KINDS = ("外形寸法図", "外形図", "構造図", "断面図", "計器仕様書", "取扱説明書")  # ファイル名の末尾にある、関連ファイルの種類。長い語を先に書く
MATCH, VARIANT, CANDIDATE, NONE, LOOSE = "一致", "番号の表記ゆれ", "名称からの候補 (要確認)", "関連ファイルなし", "番号が未確定の関連ファイル"


def parse_name(stem: str, kinds=KINDS) -> dict:
    """ファイル名 (拡張子なし) を {"nos": 番号の一覧, "name": 名称, "kind": 関連ファイルの種類, "tentative": 「(仮)」とあるか} に分ける。"""
    s = unicodedata.normalize("NFKC", stem).strip()
    nos: list[str] = []
    m = re.match(r"[A-Z0-9]+(?:-[A-Z0-9]+)*(?=[^A-Za-z0-9]|$)", s)
    if m and re.search(r"[A-Z]", m.group(0)) or m and m.group(0).isdigit():
        nos.append(m.group(0))
        s = s[m.end() :]
        # 「XYP1A・B」は、末尾の 1 文字だけが違う 2 つの番号
        for extra in re.match(r"((?:・[A-Z0-9])*)", s).group(1).split("・")[1:]:
            nos.append(nos[0][:-1] + extra)
        s = re.sub(r"^(?:・[A-Z0-9])+", "", s)
    kind = ""
    km = re.search(r"_?(?:[^_()]*?)(" + "|".join(map(re.escape, kinds)) + r")$", s) if kinds else None
    if km:
        kind, s = km.group(1), s[: km.start()]
    tentative = "(仮)" in s
    s = s.replace("(仮)", "").strip("_ ")
    inner = re.fullmatch(r"\((.*)\)", s)  # 「(名称)」の括弧を外す。「保管棚(600L)」の括弧は残す
    return {"nos": nos, "name": inner.group(1) if inner and "(" not in inner.group(1) else s, "kind": kind, "tentative": tentative}


def key(no: str) -> str:
    """表記のゆれを除いた番号 (ハイフンの有無を無視する)。"""
    return unicodedata.normalize("NFKC", no).upper().replace("-", "")


def _base(name: str) -> str:
    """名称の比較用。括弧書きと、号機を表す末尾の英字を除く。"""
    return re.sub(r"[A-Z]$", "", re.sub(r"\(.*?\)|\d+年度版", "", unicodedata.normalize("NFKC", name))).replace("用", "").strip()


def build(items: list[str], related: list[str], kinds=KINDS) -> list[dict]:
    """対応表の行 ({"no", "name", "item", "related": [{"file", "kind", "status", "note"}], "status"}) を返す。

    items は台帳のファイル名、related は関連ファイルのファイル名。
    最後に、どの番号にも対応づけられなかった関連ファイルを no = "" の行として足す。
    """
    spec_rows = [{**parse_name(Path(f).stem, kinds), "file": f} for f in items]
    draw_rows = [{**parse_name(Path(f).stem, kinds), "file": f} for f in related]
    used: set[str] = set()
    out = []
    for sp in spec_rows:
        no = sp["nos"][0] if sp["nos"] else ""
        found = []
        for d in draw_rows:
            hit = next((n for n in d["nos"] if key(n) == key(no)), None) if no else None
            if hit is None:
                continue
            notes = []
            if hit != no:
                notes.append(f"関連ファイルの番号は「{hit}」")
            if len(d["nos"]) > 1:
                notes.append("複数の番号で 1 つのファイル (" + "、".join(d["nos"]) + ")")
            if d["tentative"]:
                notes.append("関連ファイルの名前に「(仮)」とある")
            if d["name"] and _base(d["name"]) != _base(sp["name"]):
                notes.append(f"名称が異なる (関連ファイル: {d['name']})")
            found.append({"file": d["file"], "kind": d["kind"], "status": VARIANT if hit != no else MATCH, "note": "。".join(notes)})
            used.add(d["file"])
        if not found:  # 番号のない関連ファイルを、名称で探す。同じ名称のものがほかにもあるので確定しない
            for d in draw_rows:
                if not d["nos"] and _base(d["name"]) and _base(d["name"]) == _base(sp["name"]):
                    found.append({"file": d["file"], "kind": d["kind"], "status": CANDIDATE, "note": "関連ファイルの名前に番号がない"})
        status = NONE if not found else max((f["status"] for f in found), key=[MATCH, VARIANT, CANDIDATE].index)
        out.append({"no": no, "name": sp["name"], "item": sp["file"], "related": found, "status": status})
    candidates = {f["file"] for r in out for f in r["related"] if f["status"] == CANDIDATE}
    for d in draw_rows:
        if d["file"] not in used:
            note = "名称から候補を挙げた" if d["file"] in candidates else "対応する台帳のファイルがない"
            out.append({"no": "", "name": d["name"], "item": "", "related": [{"file": d["file"], "kind": d["kind"], "status": CANDIDATE if d["file"] in candidates else NONE, "note": note}], "status": LOOSE})
    return out


def to_markdown(rows: list[dict]) -> str:
    listed = [r for r in rows if r["no"] or r["item"]]
    count = lambda st: sum(r["status"] == st for r in listed)
    out = ["# ファイルの対応表", "", f"台帳 {len(listed)} 件のうち、関連ファイルが一致 {count(MATCH)} 件、表記ゆれで一致 {count(VARIANT)} 件、名称からの候補 {count(CANDIDATE)} 件、関連ファイルなし {count(NONE)} 件。",
           "", "| 番号 | 名称 | 状態 | 関連ファイル (種類) | 備考 |", "| --- | --- | --- | --- | --- |"]  # fmt: skip
    for r in rows:
        files = "<br>".join(f"{d['file']} ({d['kind'] or '種類不明'})" for d in r["related"]) or "-"
        notes = "<br>".join(dict.fromkeys(d["note"] for d in r["related"] if d["note"]))
        out.append(f"| {r['no'] or '-'} | {r['name']} | {r['status']} | {files} | {notes} |")
    return "\n".join(out) + "\n"


def write_csv(rows: list[dict], path: str | Path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["番号", "名称", "台帳のファイル", "状態", "関連ファイル", "関連ファイルの種類", "関連ファイルごとの状態", "備考"])
        for r in rows:
            for d in r["related"] or [{"file": "", "kind": "", "status": "", "note": ""}]:
                w.writerow([r["no"], r["name"], r["item"], r["status"], d["file"], d["kind"], d["status"], d["note"]])


def _files(folder: str) -> list[str]:
    return sorted(p.name for p in Path(folder).iterdir() if p.is_file() and not p.name.startswith((".", "~$")))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--items", required=True, help="台帳のファイル (1 つの番号に 1 ファイル) があるフォルダ")
    ap.add_argument("--related", required=True, help="関連ファイル (図面など) があるフォルダ")
    ap.add_argument("--kinds", help="ファイル名の末尾にある関連ファイルの種類 (カンマ区切り)。省略すると " + "、".join(KINDS))
    ap.add_argument("-o", "--output", help="Markdown の出力先 (省略時は標準出力)")
    ap.add_argument("--csv", help="CSV の出力先")
    a = ap.parse_args(argv)
    rows = build(_files(a.items), _files(a.related), tuple(sorted(a.kinds.split(","), key=len, reverse=True)) if a.kinds else KINDS)
    md = to_markdown(rows)
    if a.output:
        Path(a.output).write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md)
    if a.csv:
        write_csv(rows, a.csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
