"""旧形式の Office 文書 (.doc / .xls / .ppt) を、処理できる形式 (.docx / .xlsx / .pptx) に変換する。

usage:
  dococr-convert 旧形式.doc 旧形式.xls --out-dir converted
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

TARGET = {".doc": "docx", ".xls": "xlsx", ".ppt": "pptx"}
MAC_SOFFICE = "/Applications/LibreOffice.app/Contents/MacOS/soffice"


def is_legacy(path: str | Path) -> bool:
    return Path(path).suffix.lower() in TARGET


def soffice_path() -> str | None:
    """LibreOffice の実行ファイルを探す。起動スクリプトだけ残って本体がない場合は使えないとみなす。"""
    for cand in (shutil.which("soffice"), shutil.which("libreoffice"), MAC_SOFFICE):
        if not cand:
            continue
        try:
            if subprocess.run([cand, "--version"], capture_output=True, timeout=60).returncode == 0:
                return cand
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def to_modern(path: str | Path, out_dir: str | Path, timeout: int = 300) -> Path:
    """旧形式のファイルを変換し、変換後のパスを返す。新形式のファイルはそのまま返す。

    LibreOffice で変換する (表・自動番号・結合セル・書式が保たれる)。LibreOffice がなく
    .doc の場合だけ、macOS の textutil で代用する。textutil は文字書式を残すが、表・自動番号・
    ヘッダーを落とすので警告を出す。
    """
    path, out_dir = Path(path), Path(out_dir)
    ext = path.suffix.lower()
    if ext not in TARGET:
        return path
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{path.stem}.{TARGET[ext]}"
    soffice = soffice_path()
    if soffice:
        # 実行ごとに別のプロファイルを使い、起動中の LibreOffice や並列実行とぶつからないようにする
        with tempfile.TemporaryDirectory() as profile:
            cmd = [soffice, f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", TARGET[ext], "--outdir", str(out_dir), str(path)]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if out.exists():
            return out
        raise RuntimeError(f"LibreOffice で変換できません: {path}\n{res.stdout}{res.stderr}")
    if ext == ".doc" and shutil.which("textutil"):
        warnings.warn(f"LibreOffice がないため textutil で変換します。表・自動番号・ヘッダーは失われます: {path}")
        subprocess.run(["textutil", "-convert", "docx", "-output", str(out), str(path)], check=True, capture_output=True)
        return out
    raise RuntimeError(f"{ext} の変換には LibreOffice が必要です: {path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    rc = 0
    for src in a.inputs:
        try:
            print(f"{src} -> {to_modern(src, a.out_dir)}")
        except Exception as e:  # 1 ファイルの失敗で全体を止めない
            print(f"FAILED {src}: {e}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
