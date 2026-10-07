"""構造化 OCR の出力を、正解データと照らして採点する。

改善のたびに同じ正解データで測り、前回の結果より下がった指標があれば知らせる。
正解データには資料の内容が入るので、リポジトリには置かない (形式は README を参照)。

usage:
  dococr-eval --gt gt.json --out <出力フォルダ> [--save result.json] [--baseline 前回の result.json]
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path

KINDS = {
    "contains": "ページに含まれる文字列",
    "fields": "見出しごとの値",
    "pairs": "項目と値の対応",
    "checkboxes": "チェック欄の状態",
    "struck": "取り消し線のある文字列",
    "not_struck": "取り消し線のない文字列",
    "struck_count": "取り消し線のある行の数",
}


def norm(s: str) -> str:
    """表記の揺れを除く。全角・半角、空白、区切りの記号、要確認の印は比べない。

    数字に挟まれたピリオドは小数点なので残す (除くと「1.5」を「15」と読んでも正解になる)。
    """
    s = unicodedata.normalize("NFKC", s).replace("°C", "℃").replace("~~", "")
    s = re.sub(r"\s", "", s)  # 「1 . 5」のように空白で離れた小数点も、数字に挟まれたものとして扱う
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", "", s)
    return re.sub(r"[|()（）:：,，、。・･/?]", "", s).lower()


def split_pages(md: str) -> dict[int, str]:
    """出力の Markdown を、ページ番号ごとに分ける。ページ番号のない出力 (テキスト層から読んだもの) は全体を 0 とする。"""
    marks = list(re.finditer(r"^<!-- p\.(\d+)[ >-]", md, flags=re.M))
    if not marks:
        return {0: md}
    return {int(m.group(1)): md[m.start() : (marks[i + 1].start() if i + 1 < len(marks) else len(md))] for i, m in enumerate(marks)}


def section(page: str, label: str) -> str:
    """`## 見出し` から次の見出しまでの本文。"""
    m = re.search(rf"^## {re.escape(label)}\s*$(.*?)(?=^## |\Z)", page, flags=re.M | re.S)
    return m.group(1) if m else ""


def pair_value(page: str, key: str) -> str | None:
    """`項目 | 値` と並ぶ行から、項目の右隣の (空でない) 値を返す。項目の前の連番は無視する。"""
    for line in page.splitlines():
        cells = [c.strip() for c in line.split("|")]
        for i, c in enumerate(cells):
            if norm(re.sub(r"^\d+\s+", "", c)).startswith(norm(key)):
                rest = [v for v in cells[i + 1 :] if v]
                if rest:
                    return rest[0]
    return None


def checkbox_states(page: str) -> list[int]:
    return [int(m.group(1) == "x") for m in re.finditer(r"^- \[([x ])\] ", page, flags=re.M)]


def struck_text(page: str) -> str:
    return "".join(re.findall(r"(?<!\\)~~(.+?)(?<!\\)~~", page, flags=re.S))


def score_case(case: dict, page: str) -> tuple[dict[str, list[int]], list[str]]:
    """({指標: [正解した数, 全体の数]}, 外したものの一覧) を返す。"""
    res: dict[str, list[int]] = {}
    misses: list[str] = []

    def add(kind: str, hit: bool, what: str):
        r = res.setdefault(kind, [0, 0])
        r[0] += hit
        r[1] += 1
        if not hit:
            misses.append(f"{KINDS[kind]}: {what}")

    whole = norm(page)
    for s in case.get("contains", []):
        add("contains", norm(s) in whole, s)
    for label, parts in case.get("fields", {}).items():
        got = norm(section(page, label))
        for s in parts:
            add("fields", norm(s) in got, f"{label} = {s}")
    for key, val in case.get("pairs", []):
        got = pair_value(page, key)
        add("pairs", got is not None and norm(got) == norm(val), f"{key} = {val} (読み取り: {got})")
    if "checkboxes" in case:
        want, got = case["checkboxes"], checkbox_states(page)
        same = sum(b.size for b in difflib.SequenceMatcher(None, want, got, autojunk=False).get_matching_blocks())
        res["checkboxes"] = [same, len(want)]
        if same < len(want) or len(got) != len(want):
            misses.append(f"{KINDS['checkboxes']}: 正解 {len(want)} 件、読み取り {len(got)} 件、並びの一致 {same} 件")
    struck = norm(struck_text(page))
    for s in case.get("struck", []):
        add("struck", norm(s) in struck, s)
    for s in case.get("not_struck", []):
        add("not_struck", norm(s) in whole and norm(s) not in struck, s)
    if "struck_count" in case:
        n = sum("~~" in line for line in page.splitlines())
        add("struck_count", n == case["struck_count"], f"正解 {case['struck_count']} 行、読み取り {n} 行")
    return res, misses


def evaluate(gt: dict, out_dir: str | Path) -> dict:
    """{"cases": [{"name", "scores", "misses"}], "total": {指標: [正解した数, 全体の数]}}"""
    out_dir = Path(out_dir)
    cases, total = [], {}
    for case in gt["cases"]:
        path = out_dir / (case["output"] + ".md")
        md = path.read_text(encoding="utf-8") if path.exists() else None
        if md is None:
            page = None
        elif "page" not in case:
            page = md  # ページの指定がなければ、ファイル全体で採点する
        else:
            pages = split_pages(md)
            page = pages.get(case["page"], pages.get(0))
        if page is None:
            # 出力がないものは、すべて不正解として数える (空の文字列を採点する)
            scores, _ = score_case(case, "")
            misses = ["出力がない: " + case["output"] + (f" p.{case['page']}" if case.get("page") else "")]
        else:
            scores, misses = score_case(case, page)
        for k, (ok, n) in scores.items():
            t = total.setdefault(k, [0, 0])
            t[0] += ok
            t[1] += n
        cases.append({"name": case["name"], "scores": scores, "misses": misses})
    return {"cases": cases, "total": total}


def regressions(result: dict, baseline: dict) -> list[str]:
    """前回より正解数が減った指標を返す (ケースごと)。"""
    before = {c["name"]: c["scores"] for c in baseline["cases"]}
    out = []
    for c in result["cases"]:
        for k, (ok, n) in c["scores"].items():
            prev = before.get(c["name"], {}).get(k)
            if prev and ok < prev[0]:
                out.append(f"{c['name']} / {KINDS[k]}: {prev[0]}/{prev[1]} → {ok}/{n}")
    return out


def report(result: dict) -> str:
    out = ["| 指標 | 正解 | 全体 | 割合 |", "|---|---|---|---|"]
    out += [f"| {KINDS[k]} | {ok} | {n} | {100 * ok / n:.1f}% |" for k, (ok, n) in result["total"].items() if n]
    for c in result["cases"]:
        score = "、".join(f"{KINDS[k]} {ok}/{n}" for k, (ok, n) in c["scores"].items())
        out.append(f"\n**{c['name']}**: {score}")
        out += [f"- {m}" for m in c["misses"]]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gt", required=True, help="正解データ (JSON)")
    ap.add_argument("--out", required=True, help="構造化 OCR の出力フォルダ")
    ap.add_argument("--save", help="結果を JSON で保存する")
    ap.add_argument("--baseline", help="前回の結果 (JSON)。正解数が減った指標があれば終了コード 1 を返す")
    a = ap.parse_args(argv)
    result = evaluate(json.loads(Path(a.gt).read_text(encoding="utf-8")), a.out)
    print(report(result))
    if a.save:
        Path(a.save).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.baseline:
        worse = regressions(result, json.loads(Path(a.baseline).read_text(encoding="utf-8")))
        if worse:
            print("\n前回より下がった指標:\n" + "\n".join(f"- {w}" for w in worse), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
