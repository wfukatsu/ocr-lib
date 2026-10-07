"""取り消し線のある文字列を抽出し、Markdown の ``~~…~~`` で出力する。

usage:
  dococr-strike 文書.docx -o out.md --report strike.json
  dococr-strike 表.xlsx -o out.md --report strike.json
  dococr-strike 文書.pdf -o out.md                         # テキスト層のある PDF
  dococr-strike スキャン.pdf --out-dir out --ndlocr-src <ndlocr-lite/src>   # 画像だけの PDF
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .api import NeedsOcr, extract_strikes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="Markdown の出力先 (省略時は標準出力)")
    ap.add_argument("--report", help="取り消し線と要確認箇所の一覧 (JSON) の出力先")
    ap.add_argument("--tracked", choices=["mark", "skip"], default="mark", help="Word の変更履歴による削除: mark = 区別して出力 / skip = 出力しない")
    ap.add_argument("--no-figures", action="store_true", help="図や画像を取り出さない (取り出すのは -o か --out-dir を指定したとき)")
    ap.add_argument("--out-dir", help="スキャン PDF の出力先フォルダ")
    ap.add_argument("--ndlocr-src", help="スキャン PDF の OCR に使う ndlocr-lite/src のパス")
    ap.add_argument("--pages", help="スキャン PDF の対象ページ (例: 19-21)")
    a = ap.parse_args(argv)

    src = Path(a.input)
    figures = None
    if src.suffix.lower() in (".docx", ".doc") and a.output and not a.no_figures:
        from .figures import FigureWriter

        # 画像は Markdown の隣に置く。標準出力に出すときは置き場所がないので取り出さない
        figures = FigureWriter(Path(a.output).parent, Path(a.output).stem)
    try:
        md, found = extract_strikes(src, tracked=a.tracked, figures=figures)
    except NeedsOcr as e:
        # テキスト層がない・文字化け・OCR 済みスキャンの PDF は、OCR と画像からの線検出で処理する
        if not a.ndlocr_src or not a.out_dir:
            ap.error(f"{e}。--ndlocr-src と --out-dir を指定してください")
        cmd = [sys.executable, "-m", "dococr.pipeline", "--ndlocr-src", a.ndlocr_src, "--out", a.out_dir, str(src)]
        return subprocess.call(cmd + (["--pages", a.pages] if a.pages else []) + (["--no-figures"] if a.no_figures else []))
    except ValueError as e:
        ap.error(str(e))

    if a.output:
        Path(a.output).write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md)
    if a.report:
        Path(a.report).write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
