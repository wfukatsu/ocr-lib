"""用語集: テキストとして読めるファイルから固有名詞や型番を集め、OCR の読み取りと照らし合わせる。

処理の順序は次のとおり。

1. OCR が要らないファイル (テキスト層を使える PDF、Word、Excel) とファイル名から、用語を集めて用語集に書き出す。
2. OCR の読み取りを用語集と照らし合わせる。用語集にない語が、用語集の語と紛らわしい文字 1 つだけ違う場合に補正する。

補正は、見た目が紛らわしい文字の取り違え (ポ と ボ、ー と 一 など) に限る。それ以外の 1 文字違いは、
別の実在する語のことがある (「上部シャッター」と「下部シャッター」) ので、書き換えずに候補として挙げる。

型番は、紛らわしい文字 1 つの違いでも書き換えない。「P-1B」と「P-18」、「TK-1D」と「TK-10」のように、
どちらも実在する番号のことがあり、用語集に載るのは OCR が要らないファイルに出てくる番号だけなので、
正しく読めた番号を別の番号に変えてしまう。型番として書けない読み取り (小文字や縦棒が混ざったもの、
ハイフンが長音になったもの) だけを補正する。

usage:
  dococr-glossary --root <入力フォルダ> -o glossary.tsv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

MODEL, WORD, NAME = "型番", "用語", "名称"
KANJI = r"一-鿿々〆"
KATA = r"ァ-ヺー"
# 英大文字で始まり数字を含む、英数字とハイフンの並び (KX416-2、V-AB-016、SUS316L)
MODEL_RE = re.compile(r"(?<![A-Za-z0-9-])[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*(?![A-Za-z0-9-])")
# 漢字とカタカナの並び (自動梱包ロボット、パレタイザー)。ひらがなで区切れるので、名詞の複合語が取れる
WORD_RE = re.compile(f"[{KANJI}{KATA}]+")
# OCR の読み取りから型番の候補を探すときは、小文字や縦棒が混ざったもの (V-AB-0l6) も拾う
LOOSE_MODEL_RE = re.compile(r"(?<![A-Za-z0-9|-])[A-Z0-9][A-Za-z0-9|]*(?:-[A-Za-z0-9|]+)*(?![A-Za-z0-9|-])")
# 英数字に挟まれた長音や漢数字の一は、ハイフンの取り違え (V一AB一016)
DASH_RE = re.compile(r"(?<=[A-Za-z0-9])[ー一−‐―](?=[A-Za-z0-9])")
MIN_LEN, MAX_LEN = 3, 20
MIN_COUNT = 2  # 本文から集める語は、この回数以上出たものだけを載せる
MIN_FIX_LEN = 4  # これより短い語は、1 文字違いの別の語が多いので補正しない
LOW_CONF = 0.7  # 行の信頼度がこれ未満なら、1 文字違いの語を候補として挙げる
MIN_SUGGEST_COUNT = 5  # 用語集の語がこの回数以上出ていれば、行の信頼度が高くても候補として挙げる

# 見た目が紛らわしい文字の組。OCR の取り違えとして補正してよいもの
_CONFUSABLE_GROUPS = [
    "O0DQ", "I1l|", "S5", "B8", "Z2", "G6",
    "ー一-−‐―", "ロ口", "カ力", "エ工", "タ夕", "ニ二", "ハ八", "ト卜", "ヘへ", "ソン", "シツ", "ク夕", "チ千", "ミ三", "オ才", "ヌ又", "ム厶",
    "ポボホ", "パバハ", "ピビヒ", "プブフ", "ペベヘ", "ガカ", "ギキ", "グク", "ゲケ", "ゴコ", "ザサ", "ジシ", "ズス", "ゼセ", "ゾソ", "ダタ", "ヂチ", "ヅツ", "デテ", "ドト",
    "ァア", "ィイ", "ゥウ", "ェエ", "ォオ", "ッツ", "ャヤ", "ュユ", "ョヨ", "コユ", "ェュ",
]  # fmt: skip
CONFUSABLE = {frozenset((a, b)) for g in _CONFUSABLE_GROUPS for a in g for b in g if a != b}


def norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def tokens(text: str, loose: bool = False) -> list[tuple[str, str, int]]:
    """文字列から、用語の候補を (語, 種類, 位置) で取り出す。loose は OCR の読み取り向けで、型番を緩く拾う。"""
    text = norm(text)
    model = LOOSE_MODEL_RE if loose else MODEL_RE
    out = [(m.group(0), MODEL, m.start()) for m in model.finditer(text) if re.search(r"\d", m.group(0)) and re.search(r"[A-Za-z|]", m.group(0)) and MIN_LEN <= len(m.group(0)) <= MAX_LEN]
    out += [(m.group(0), WORD, m.start()) for m in WORD_RE.finditer(text) if MIN_LEN <= len(m.group(0)) <= MAX_LEN]
    return sorted(out, key=lambda t: t[2])


_JP = re.compile(f"[{KANJI}{KATA}]")


def terms_in_text(text: str) -> list[tuple[str, str]]:
    """本文から用語の候補を (語, 種類) で取り出す。

    行の折り返しで切れた語を載せないよう、行の端にあって隣の行にも漢字・カタカナが続く語は除く。
    語の末尾の「等」「及」などは落とす。
    """
    lines = norm(text).splitlines()
    out = []
    for i, line in enumerate(lines):
        prev_jp = i > 0 and bool(_JP.match(lines[i - 1][-1:]))
        next_jp = i + 1 < len(lines) and bool(_JP.match(lines[i + 1][:1]))
        for term, kind, pos in tokens(line):
            if kind == WORD:
                if (pos == 0 and prev_jp) or (pos + len(term) == len(line) and next_jp):
                    continue
                term = re.sub("[等及又並]+$", "", term)
                if len(term) < MIN_LEN:
                    continue
            out.append((term, kind))
    return out


# ---- 用語を集める


def _pdf_text(path: Path) -> str:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def _xlsx_text(path: Path) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return "\n".join(str(v) for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for v in row if isinstance(v, str))
    finally:
        wb.close()


def _office_text(path: Path) -> str:
    from . import convert, strike_docx

    with tempfile.TemporaryDirectory() as tmp:
        if convert.is_legacy(path):
            if convert.soffice_path() is None:
                return ""
            path = convert.to_modern(path, tmp)
        if path.suffix.lower() == ".xlsx":
            return _xlsx_text(path)
        md, _ = strike_docx.extract(path)
    return md.replace("~~", "")


def readable_text(path: Path) -> str | None:
    """OCR なしで読めるファイルなら本文を返す。OCR が要るファイルと対象外のファイルは None。"""
    from . import route

    ext = path.suffix.lower()
    if ext == ".pdf":
        return _pdf_text(path) if route.classify(path)["kind"] == route.TEXT else None
    if ext in (".docx", ".xlsx", ".doc", ".xls"):
        return _office_text(path)
    return None


def build(root: str | Path, log=print) -> list[dict]:
    """root 以下のファイルから用語を集め、[{"term", "kind", "count", "sources"}] を返す。

    ファイル名の先頭の番号と名称は、1 回しか出なくても載せる (資料の提供元が付けた名前なので信用できる)。
    """
    from .mapping import parse_name

    root = Path(root)
    count: Counter = Counter()
    kind: dict[str, str] = {}
    sources: dict[str, list[str]] = defaultdict(list)
    trusted: set[str] = set()

    def add(term: str, k: str, src: str, strong: bool = False):
        count[term] += 1
        kind.setdefault(term, k)
        if strong:
            trusted.add(term)
            kind[term] = k
        if src not in sources[term] and len(sources[term]) < 3:
            sources[term].append(src)

    for path in sorted(p for p in root.rglob("*") if p.is_file() and not p.name.startswith((".", "~$"))):
        rel = str(path.relative_to(root))
        parsed = parse_name(path.stem)
        nos = [n for n in parsed["nos"] if (re.search(r"[A-Z]", n) and re.search(r"\d", n)) or len(n) >= 5]  # 「1. 概要」のような連番は、型番ではない
        for no in nos:
            add(norm(no), MODEL, rel, strong=True)
        if nos and MIN_LEN <= len(parsed["name"]) <= MAX_LEN and WORD_RE.fullmatch(norm(parsed["name"])):
            add(norm(parsed["name"]), NAME, rel, strong=True)
        try:
            text = readable_text(path)
        except Exception as e:  # 1 ファイルの失敗で全体を止めない
            log(f"用語集: 読めなかった {rel}: {e!r}")
            continue
        if text is None:
            continue
        found = terms_in_text(text)
        log(f"用語集: {rel} から候補 {len(found)} 件")
        for term, k in found:
            add(term, k, rel)
    rows = [{"term": t, "kind": kind[t], "count": n, "sources": sources[t]} for t, n in count.items() if n >= MIN_COUNT or t in trusted]
    return sorted(rows, key=lambda r: (r["kind"], -r["count"], r["term"]))


def save(rows: list[dict], path: str | Path):
    """用語集を TSV で書き出す。人が開いて、行の追加や削除ができる。"""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["用語", "種類", "出現回数", "出典"])
        for r in rows:
            w.writerow([r["term"], r["kind"], r["count"], " / ".join(r["sources"])])


def load(path: str | Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    return [{"term": norm(r[0]), "kind": r[1] if len(r) > 1 else WORD, "count": int(r[2]) if len(r) > 2 and r[2].isdigit() else 1, "sources": r[3].split(" / ") if len(r) > 3 and r[3] else []}
            for r in rows[1:] if r and r[0].strip()]  # fmt: skip


# ---- 読み取りと照らし合わせる


class Glossary:
    """用語集と照らし合わせて、OCR の読み取りを補正する。"""

    def __init__(self, rows: list[dict]):
        self.terms = {r["term"]: r for r in rows}
        # 同じ長さで 1 文字だけ違う語を速く探すため、各位置の文字を伏せた形で引けるようにする
        self._masked: dict[tuple[int, str], list[str]] = defaultdict(list)
        for t in self.terms:
            for i in range(len(t)):
                self._masked[(i, t[:i] + t[i + 1 :])].append(t)

    def __len__(self) -> int:
        return len(self.terms)

    def __contains__(self, term: str) -> bool:
        return norm(term) in self.terms

    def near(self, token: str) -> list[tuple[str, str, str]]:
        """token と同じ長さで 1 文字だけ違う用語を、(用語, 読み取りの文字, 用語の文字) で返す。"""
        out = []
        for i in range(len(token)):
            for t in self._masked.get((i, token[:i] + token[i + 1 :]), ()):
                if t != token and len(t) == len(token):
                    out.append((t, token[i], t[i]))
        return out

    def check(self, token: str, kind: str) -> tuple[str, str | None]:
        """("fix", 用語) = 補正する / ("suggest", 用語) = 候補として挙げる / ("ok", None) = そのまま。"""
        if token in self.terms or len(token) < MIN_FIX_LEN:
            return "ok", None
        cands = [c for c in self.near(token) if (self.terms[c[0]]["kind"] == MODEL) == (kind == MODEL)]
        if len({c[0] for c in cands}) != 1:  # 候補がない、または 1 つに決まらない
            return "ok", None
        term, got, want = cands[0]
        if frozenset((got, want)) not in CONFUSABLE:
            return "suggest", term
        # 型番として書ける読み取りは、それ自体が別の実在する番号かもしれないので書き換えない
        return ("suggest" if kind == MODEL and MODEL_RE.fullmatch(token) else "fix"), term

    def correct(self, text: str) -> tuple[str, list[dict], list[dict]]:
        """文字列を補正し、(補正後の文字列, 補正の一覧, 候補の一覧) を返す。一覧は {"from", "to"}。

        全角・半角の違いで位置がずれないよう、長さが変わらない場合だけ書き換える。
        """
        fixes, suggestions = [], []
        if norm(text) != text and len(norm(text)) != len(text):
            return text, fixes, suggestions
        base = DASH_RE.sub("-", norm(text))
        out = list(text)
        spans = []
        for token, kind, pos in tokens(base, loose=True):
            if any(pos < e and s < pos + len(token) for s, e in spans):  # 型番の中の語を二重に扱わない
                continue
            orig = text[pos : pos + len(token)]
            if kind == MODEL and token in self.terms and norm(orig) != token:
                action, term = "fix", token  # ハイフンの取り違えを直すと用語集の語になる
            elif kind == MODEL and token not in self.terms and token.upper() in self.terms:
                action, term = "fix", token.upper()  # 大文字と小文字の取り違え (Ts2-18)
            else:
                action, term = self.check(token, kind)
            if action == "fix":
                out[pos : pos + len(token)] = list(term)
                fixes.append({"from": orig, "to": term})
                spans.append((pos, pos + len(token)))
            elif action == "suggest":
                suggestions.append({"from": orig, "to": term})
        return "".join(out), fixes, suggestions

    def pick(self, a: str, b: str | None) -> str | None:
        """2 つの読みのうち、片方だけが用語集にあればそれを返す (どちらもある、どちらもない場合は None)。"""
        if not b:
            return None
        in_a, in_b = norm(a) in self.terms, norm(b) in self.terms
        return a if in_a and not in_b else b if in_b and not in_a else None

    def apply(self, lines: list[dict]) -> dict:
        """OCR の行 ("text" を持つ辞書) を補正する。{"fixes": […], "suggestions": […]} を返す。

        補正した行には "glossary" (補正の一覧) を付ける。候補は、信頼度の低い行のものと、用語集の語が
        資料によく出るもの (MIN_SUGGEST_COUNT 回以上) を挙げる。よく出る語の 1 文字違いは、誤読のことが多い。
        """
        report = {"fixes": [], "suggestions": []}
        for ln in lines:
            text, fixes, suggestions = self.correct(ln.get("text") or "")
            if fixes:
                ln["text"], ln["glossary"] = text, fixes
                if "md" in ln:  # 取り消し線の Markdown を作った後なら、そちらも合わせる
                    for f in fixes:
                        ln["md"] = ln["md"].replace(f["from"], f["to"])
                report["fixes"] += fixes
            low = ln.get("conf", 1.0) < LOW_CONF
            report["suggestions"] += [s for s in suggestions if low or self.terms[s["to"]]["count"] >= MIN_SUGGEST_COUNT]
        return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="入力ファイルのフォルダ")
    ap.add_argument("-o", "--output", required=True, help="用語集の出力先 (TSV)")
    a = ap.parse_args(argv)
    rows = build(a.root, log=lambda m: print(m, file=sys.stderr))
    save(rows, a.output)
    kinds = Counter(r["kind"] for r in rows)
    print(f"用語集: {len(rows)} 語 (" + "、".join(f"{k} {n}" for k, n in kinds.items()) + f") を {a.output} に書き出しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
