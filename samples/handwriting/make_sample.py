"""手書きのサンプル文書を作る (架空の点検記録と連絡メモ)。

活字の帳票に手書きで値を書き込んだページと、手書きだけのメモのページを、画像だけの PDF にする。
手書きは人が書いたものではなく、手書き風のフォントの文字を 1 文字ずつ傾き・大きさ・位置をばらつかせて描いたもの。
書き込んだ内容は expected.json に書き出す。

usage:
  python samples/handwriting/make_sample.py samples/handwriting/source --hand-font <手書き風のフォント> [--font <活字のフォント>]

pillow が要る。手書き風のフォントは同梱していない。置いてあるサンプルは Yomogi (SIL Open Font License 1.1) で作った。
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

DPI = 300
K = DPI / 72  # ポイント → 画素
W, H = 595, 842  # A4 (ポイント)
INK = 40  # 手書きの濃さ (0 が黒)

TITLE = "空調設備 定期点検 記録"
PAGE_NO = "No. 27"  # 罫線の外の書き込み
HEADER = [[("点検日", "2026年9月14日"), ("点検者", "山田 太郎")], [("設備名", "第2棟 送風機 AHU-3"), ("天候", "晴れ")]]
COLUMNS = ["項目", "基準値", "測定値", "判定"]
ROWS = [
    ("風量", "1,500 m3/h 以上", "1,620", "良"),
    ("運転電流", "12.5 A 以下", "11.8", "良"),
    ("軸受温度", "70 ℃ 以下", "73.5", "否"),
    ("振動", "4.5 mm/s 以下", "2.3", "良"),
    ("絶縁抵抗", "1 MΩ 以上", "50", "良"),
]
CHECKS = [("フィルター清掃", True), ("ベルト交換", False), ("給油", True)]
NOTE = ["軸受温度が基準を超えている。", "次回の点検までにベアリングを交換する。"]
MEMO_TITLE = "連絡メモ"
MEMO = ["9月14日の午後、第2棟の送風機から異音がありました。", "ベルトのゆるみが原因と思われます。", "部品が届きしだい交換します。", "連絡先 内線 4521 山田"]


class Sheet:
    """1 ページ分の画像。座標はポイント、原点は左上。"""

    def __init__(self, font_path: str, hand_path: str, rng: random.Random):
        self.img = Image.new("L", (round(W * K), round(H * K)), 255)
        self.d = ImageDraw.Draw(self.img)
        self.font_path, self.hand_path, self.rng = font_path, hand_path, rng
        self.fonts: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

    def font(self, path: str, px: int) -> ImageFont.FreeTypeFont:
        return self.fonts.setdefault((path, px), ImageFont.truetype(path, px))

    def text(self, x: float, y: float, s: str, size: float = 11):
        self.d.text((x * K, y * K), s, font=self.font(self.font_path, round(size * K)), fill=0)

    def line(self, x0: float, y0: float, x1: float, y1: float):
        self.d.line((x0 * K, y0 * K, x1 * K, y1 * K), fill=0, width=3)

    def grid(self, xs: list[float], ys: list[float]):
        for y in ys:
            self.line(xs[0], y, xs[-1], y)
        for x in xs:
            self.line(x, ys[0], x, ys[-1])

    def hand(self, x: float, y: float, s: str, size: float = 14):
        """手書き風に書く。1 文字ずつ、傾き・大きさ・上下の位置をばらつかせる。"""
        rng, px = self.rng, x * K
        slope = rng.uniform(-0.012, 0.012)  # 行全体の右上がり・右下がり
        for ch in s:
            f = self.font(self.hand_path, round(size * K * rng.uniform(0.92, 1.08)))
            adv = f.getlength(ch)
            if not ch.isspace():
                side = round(f.size * 1.6)
                tile = Image.new("L", (side, side), 0)
                ImageDraw.Draw(tile).text((side * 0.2, side * 0.2), ch, font=f, fill=255)
                tile = tile.rotate(rng.uniform(-4, 4), resample=Image.BICUBIC)
                top = y * K + (px - x * K) * slope + rng.uniform(-0.04, 0.04) * f.size
                self.img.paste(INK, (round(px - side * 0.2), round(top - side * 0.2)), tile)
            px += adv * rng.uniform(0.9, 1.05)

    def tick(self, x: float, y: float, s: float):
        """四角 (左上が x, y、一辺 s) に手書きのチェックを入れる。四角から少しはみ出す。"""
        j = lambda: self.rng.uniform(-0.06, 0.06) * s
        pts = [(x + s * 0.15 + j(), y + s * 0.5 + j()), (x + s * 0.42 + j(), y + s * 0.85 + j()), (x + s * 1.15 + j(), y - s * 0.1 + j())]
        self.d.line([(px * K, py * K) for px, py in pts], fill=INK, width=5, joint="curve")


def record_page(sh: Sheet):
    sh.text(70, 60, TITLE, 16)
    sh.hand(455, 58, PAGE_NO, 13)
    xs, y = [70, 130, 310, 370, 525], 100
    sh.grid(xs, [y, y + 30, y + 60])
    for r, row in enumerate(HEADER):
        for c, (label, value) in enumerate(row):
            sh.text(xs[c * 2] + 8, y + r * 30 + 9, label)
            sh.hand(xs[c * 2 + 1] + 10, y + r * 30 + 7, value)
    xs, y = [70, 170, 320, 430, 525], 190
    sh.grid(xs, [y + i * 30 for i in range(len(ROWS) + 2)])
    for c, label in enumerate(COLUMNS):
        sh.text(xs[c] + 8, y + 9, label)
    for r, (item, limit, value, verdict) in enumerate(ROWS, start=1):
        sh.text(xs[0] + 8, y + r * 30 + 9, item)
        sh.text(xs[1] + 8, y + r * 30 + 9, limit)
        sh.hand(xs[2] + 22, y + r * 30 + 7, value)
        sh.hand(xs[3] + 34, y + r * 30 + 7, verdict)
    y = 400
    sh.text(70, y, "実施した作業")
    for i, (label, done) in enumerate(CHECKS):
        x, s = 82 + i * 150, 11
        sh.d.rectangle((x * K, (y + 26) * K, (x + s) * K, (y + 26 + s) * K), outline=0, width=3)
        sh.text(x + s + 6, y + 26, label)
        if done:
            sh.tick(x, y + 26, s)
    y = 470
    sh.grid([70, 525], [y, y + 100])
    sh.text(78, y + 8, "所見")
    for i, s in enumerate(NOTE):
        sh.hand(90, y + 30 + i * 28, s)


def memo_page(sh: Sheet):
    sh.text(70, 60, MEMO_TITLE, 16)
    for i, s in enumerate(MEMO):
        sh.hand(80, 120 + i * 40, s, 16)


def expected() -> dict:
    return {
        "page_no": PAGE_NO,
        "header": {label: value for row in HEADER for label, value in row},
        "measurements": [{"項目": item, "測定値": value, "判定": verdict} for item, _, value, verdict in ROWS],
        "checks": {label: done for label, done in CHECKS},
        "note": NOTE,
        "memo": MEMO,
    }


def find_font() -> str | None:
    # macOS のファイル名は濁点が分かれた形 (NFD) なので、正規化してから比べる
    for pattern, word in (("/System/Library/Fonts/*W3.ttc", "角ゴシック"), ("/usr/share/fonts/**/NotoSansCJK-Regular.ttc", ""), ("/usr/share/fonts/**/ipaexg.ttf", ""), ("C:/Windows/Fonts/meiryo.ttc", "")):
        hit = sorted(f for f in glob.glob(pattern, recursive=True) if word in unicodedata.normalize("NFC", f))
        if hit:
            return hit[0]
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_dir")
    ap.add_argument("--hand-font", required=True, help="手書き風の日本語のフォント")
    ap.add_argument("--font", help="活字に使う日本語のフォント (省略すると、よくある場所から探す)")
    ap.add_argument("--seed", type=int, default=1, help="ばらつきの乱数の種")
    a = ap.parse_args(argv)
    font = a.font or find_font()
    if font is None:
        ap.error("日本語のフォントが見つかりません。--font で指定してください")
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)
    pages = []
    for draw in (record_page, memo_page):
        sh = Sheet(font, a.hand_font, rng)
        draw(sh)
        pages.append(sh.img.filter(ImageFilter.GaussianBlur(0.8)))
    pages[0].save(out / "tenken_tegaki.pdf", "PDF", resolution=DPI, save_all=True, append_images=pages[1:])
    (out / "expected.json").write_text(json.dumps(expected(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{out} に tenken_tegaki.pdf と expected.json を作りました (手書き: {a.hand_font}、活字: {font})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
