"""ページ画像と OCR 結果を視覚モデルに渡し、表や欄の構造を読み取らせる (試行用)。

OCR だけでは取れないもの (測定記録の手書きの数値、図面の表題欄や寸法) が対象。
役割を分ける: 文字の根拠は OCR、配置と意味の解釈は視覚モデル。視覚モデルが返した値は、
OCR が同じ値を読んでいるものだけを「裏付けあり」とし、それ以外は要確認にする。

**ページ画像と OCR 結果を社外のサービスに送信する。** 契約済みのサービスに限って使うこと。
`--allow-external` を付けない限り送信しない。送信するページは、送る前に sent_log.jsonl に記録する。

usage:
  dococr-vlm --task measurement --pages 118-122 --ndlocr-src <ndlocr-lite/src> --out <dir> \\
      --provider claude-code --allow-external <pdf>

--provider claude-code は、Claude Code の CLI (`claude -p`) を呼ぶ。API キーは要らず、Claude Code の認証を使う。
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

from .textutil import join_rows, norm

DEFAULT_MODEL = "claude-opus-5-5"
MAX_SIDE = 2576  # 送る画像の長辺の上限 (画素)。これより大きいページは縮小する
CLI_SIDE = 2000  # Claude Code が画像を読むときの長辺の上限。これより大きい画像は縮小されるので、分割した拡大図も渡す

VALUE = {
    "type": "object",
    "properties": {"value": {"type": "string", "description": "読み取った値。読めなければ空文字"}, "unsure": {"type": "boolean", "description": "読み取りに自信がなければ true"}},
    "required": ["value", "unsure"],
}
TASKS = {
    "measurement": {
        "label": "測定記録",
        "instruction": "このページは点検・測定の記録です。表ごとに、表題と、行ごとの項目と値を取り出してください。値には手書きの数値を含みます。",
        "schema": {
            "type": "object",
            "properties": {
                "tables": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "columns": {"type": "array", "items": {"type": "string"}},
                            "rows": {"type": "array", "items": {"type": "array", "items": VALUE}},
                        },
                        "required": ["title", "columns", "rows"],
                    },
                }
            },
            "required": ["tables"],
        },
    },
    "drawing": {
        "label": "図面",
        "instruction": "このページは機器の図面です。表題欄 (図面の名称、図番、作成者の会社名、尺度、日付) と、部品表 (番号、名称、材質、数量) を取り出してください。寸法は取り出さなくて構いません。",
        "schema": {
            "type": "object",
            "properties": {
                "title_block": {"type": "object", "properties": {k: VALUE for k in ("name", "drawing_no", "company", "scale", "date")}, "required": ["name", "drawing_no"]},
                "parts": {"type": "array", "items": {"type": "object", "properties": {k: VALUE for k in ("no", "name", "material", "quantity")}, "required": ["no", "name"]}},
            },
            "required": ["title_block", "parts"],
        },
    },
}
SYSTEM = (
    "あなたは、スキャンした日本語の技術文書から、表や欄の構造を取り出す作業をします。"
    "ページ画像と、同じページの OCR 結果を渡します。OCR 結果は文字の根拠として使い、配置と対応関係は画像から判断してください。"
    "画像から読み取れない値は、推測で埋めずに空文字にしてください。読み取りに自信がない値は unsure を true にしてください。"
    "個人名や印影の文字は取り出さないでください。"
)


def encode_image(img: np.ndarray, max_side: int = MAX_SIDE) -> tuple[str, float]:
    """PNG にして base64 にする。(データ, 縮小率) を返す。"""
    im = Image.fromarray(img)
    scale = min(1.0, max_side / max(im.size))
    if scale < 1.0:
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii"), scale


def ask(client, model: str, task: str, img: np.ndarray, ocr_text: str, max_tokens: int = 8000) -> tuple[dict, dict]:
    """視覚モデルに 1 ページを渡し、(構造化した結果, 使用量) を返す。client は Anthropic の SDK と同じ形のもの。"""
    spec = TASKS[task]
    data, scale = encode_image(img)
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
        {"type": "text", "text": f"{spec['instruction']}\n\n同じページの OCR 結果 (行ごと。同じ高さの行は | で区切る):\n\n{ocr_text}"},
    ]
    tool = {"name": "record", "description": "読み取った構造を記録する", "input_schema": spec["schema"]}
    res = client.messages.create(model=model, max_tokens=max_tokens, system=SYSTEM, messages=[{"role": "user", "content": content}], tools=[tool], tool_choice={"type": "tool", "name": "record"})
    block = next((b for b in res.content if getattr(b, "type", None) == "tool_use"), None)
    if block is None:
        raise RuntimeError("視覚モデルが構造化した結果を返さなかった")
    usage = {"input_tokens": getattr(res.usage, "input_tokens", None), "output_tokens": getattr(res.usage, "output_tokens", None), "image_scale": round(scale, 3)}
    return dict(block.input), usage


def tiles(img: np.ndarray, n: int, overlap: float = 0.06) -> list[np.ndarray]:
    """ページを n×n に分けた画像 (左上から右へ、上から下へ)。境目の文字が切れないよう少し重ねる。"""
    H, W = img.shape[:2]
    oy, ox = round(H * overlap / 2), round(W * overlap / 2)
    return [img[max(r * H // n - oy, 0) : min((r + 1) * H // n + oy, H), max(c * W // n - ox, 0) : min((c + 1) * W // n + ox, W)] for r in range(n) for c in range(n)]


def ask_claude_code(model: str, task: str, img: np.ndarray, ocr_text: str, split: int = 2, runner=subprocess.run, timeout: int = 900) -> tuple[dict, dict]:
    """Claude Code の CLI に 1 ページを渡し、(構造化した結果, 使用量) を返す。

    画像は一時フォルダに置き、CLI にはそのフォルダの読み取りだけを許す (ほかのツールや連携先は使わせない)。
    CLI は大きい画像を縮小して読むので、ページ全体のほかに split×split に分けた拡大図も渡す。
    """
    spec = TASKS[task]
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for name, part in [("page.png", img)] + ([(f"part{i + 1}.png", t) for i, t in enumerate(tiles(img, split))] if split > 1 and max(img.shape[:2]) > CLI_SIDE else []):
            im = Image.fromarray(part)
            k = min(1.0, CLI_SIDE / max(im.size))
            if k < 1.0:
                im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
            im.save(Path(tmp) / name)
            paths.append(str(Path(tmp) / name))
        parts = f"残りの {len(paths) - 1} 枚は、同じページを {split}×{split} に分けた拡大図です (左上から右へ、上から下への順)。細かい文字は拡大図で確かめてください。" if len(paths) > 1 else ""
        prompt = (
            "次の画像ファイルを Read ツールで読んでください。\n" + "\n".join(paths) + f"\n\n1 枚目はページ全体です。{parts}\n\n{spec['instruction']}\n\n"
            f"同じページの OCR 結果 (行ごと。同じ高さの行は | で区切る):\n\n{ocr_text}"
        )
        cmd = ["claude", "-p", prompt, "--output-format", "json", "--json-schema", json.dumps(spec["schema"], ensure_ascii=False), "--append-system-prompt", SYSTEM,
               "--tools", "Read", "--allowedTools", "Read", "--add-dir", tmp, "--model", model, "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']  # fmt: skip
        res = runner(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, cwd=tmp, timeout=timeout)
    try:
        events = json.loads(res.stdout[res.stdout.index("[") :] if res.stdout.lstrip()[:1] not in "[{" else res.stdout)
    except ValueError as e:
        raise RuntimeError(f"Claude Code の出力を読めなかった: {res.stdout[:200]!r} {res.stderr[:200]!r}") from e
    last = events[-1] if isinstance(events, list) else events
    if last.get("is_error") or not isinstance(last.get("structured_output"), dict):
        raise RuntimeError(f"Claude Code が構造化した結果を返さなかった: {str(last.get('result'))[:200]}")
    u = last.get("usage") or {}
    usage = {"input_tokens": sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")), "output_tokens": u.get("output_tokens"),
             "cost_usd": last.get("total_cost_usd"), "images": len(paths)}  # fmt: skip
    return last["structured_output"], usage


SHORT_VALUE = 2  # この文字数以下の値は、OCR の 1 つの読み取りと丸ごと一致したときだけ裏付けありとする


def ocr_cells(ocr_text: str) -> list[str]:
    """OCR 結果 (行ごと。同じ高さの行は | で区切る) を、読み取りの単位ごとに分ける。

    1 つの読み取りと、その中の空白で区切られた語の両方を返す (「すきま 0.05」の「0.05」も 1 つの単位)。
    """
    parts = [c for line in ocr_text.splitlines() for c in line.split(" | ")]
    return list(dict.fromkeys(n for c in parts for n in (norm(c), *map(norm, c.split())) if n))


def supported(value: str, cells: list[str]) -> bool:
    """OCR が同じ値を読んでいるか。

    ページの文字列のどこかに含まれるかで見ると、「5」は日付や別の数値の一部に当たるだけで裏付けありになる。
    短い値は読み取りと丸ごと一致すること、長い値は英数字や小数点の途中から始まったり終わったりしないことを求める。
    """
    v = norm(value)
    if v in cells:
        return True
    if len(v) <= SHORT_VALUE:
        return False
    head = r"(?<![0-9A-Za-z])(?<![0-9][.,])" if v[0].isascii() and v[0].isalnum() else ""
    tail = r"(?![0-9A-Za-z]|[.,][0-9])" if v[-1].isascii() and v[-1].isalnum() else ""
    pattern = re.compile(head + re.escape(v) + tail)
    return any(pattern.search(c) for c in cells)


def mark_support(node, cells: list[str]) -> tuple[int, int]:
    """値ごとに、OCR が同じ値を読んでいるかを "supported" として書き込む。(裏付けのある数, 値の数) を返す。

    cells は ocr_cells の結果。裏付けがない値と、モデルが自信がないとした値は "review" を true にする。空の値は数えない。
    """
    ok = total = 0
    if isinstance(node, dict):
        if "value" in node and isinstance(node["value"], str):
            v = norm(node["value"])
            if v:
                node["supported"] = supported(v, cells)
                node["review"] = bool(node.get("unsure")) or not node["supported"]
                return int(node["supported"]), 1
            return 0, 0
        children = node.values()
    elif isinstance(node, list):
        children = node
    else:
        return 0, 0
    for child in children:
        a, b = mark_support(child, cells)
        ok, total = ok + a, total + b
    return ok, total


def to_markdown(task: str, result: dict) -> str:
    show = lambda v: (v.get("value", "") + (" (?)" if v.get("review") else "")).replace("|", r"\|") if isinstance(v, dict) else str(v)
    out = []
    if task == "measurement":
        for t in result.get("tables", []):
            cols = t.get("columns") or [""] * max((len(r) for r in t.get("rows", [])), default=1)
            out += [f"### {t.get('title') or '(表題なし)'}", "", "| " + " | ".join(cols) + " |", "|" + " --- |" * len(cols)]
            out += ["| " + " | ".join(show(v) for v in row) + " |" for row in t.get("rows", [])]
            out.append("")
    else:
        names = {"name": "名称", "drawing_no": "図番", "company": "会社名", "scale": "尺度", "date": "日付", "no": "番号", "material": "材質", "quantity": "数量"}
        out += ["### 表題欄", ""] + [f"- {names[k]}: {show(v)}" for k, v in result.get("title_block", {}).items()] + [""]
        if result.get("parts"):
            keys = ["no", "name", "material", "quantity"]
            out += ["### 部品表", "", "| " + " | ".join(names[k] for k in keys) + " |", "|" + " --- |" * len(keys)]
            out += ["| " + " | ".join(show(p.get(k, {})) for k in keys) + " |" for p in result["parts"]]
    return "\n".join(out).rstrip() + "\n"


def make_client(provider: str):
    """契約しているサービスに合わせて SDK のクライアントを作る。認証情報は各 SDK の標準の環境変数から読む。"""
    import anthropic

    if provider == "anthropic":
        return anthropic.Anthropic()
    if provider == "bedrock":
        return anthropic.AnthropicBedrock()
    if provider == "vertex":
        return anthropic.AnthropicVertex()
    raise ValueError(f"未対応のサービス: {provider}")


def run(src: str, pages: tuple[int, int], task: str, out_dir: Path, ask_page, model: str, provider: str, prepare, render) -> list[dict]:
    """ページごとに OCR し、視覚モデルに渡して結果を書き出す。

    ask_page(task, img, ocr_text) は (構造化した結果, 使用量) を返す。render(src, page_no) はページ画像を返し、
    prepare(img) は (向きを直した画像, OCR の行) を返す。

    送信の記録は送る前に書く (応答を受け取れなくても、送ったことは残る)。結果は 1 ページごとに書き出し、
    あるページで失敗しても、それまでの結果を残して次のページに進む。失敗したページは "error" を持つ。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(src).stem
    report, mds = [], []
    for pno in range(pages[0], pages[1] + 1):
        img, lines = prepare(render(src, pno))
        ocr_text = join_rows(lines, lambda l: l["text"])
        with open(out_dir / "sent_log.jsonl", "a", encoding="utf-8") as f:  # 何を社外に送ったかの記録
            f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "file": str(src), "page": pno, "provider": provider, "model": model, "task": task}, ensure_ascii=False) + "\n")
        t0 = time.time()
        try:
            result, usage = ask_page(task, img, ocr_text)
        except Exception as e:  # 1 ページの失敗で、それまでの結果を失わない
            report.append({"page": pno, "error": repr(e), "seconds": round(time.time() - t0, 1)})
            mds.append(f"<!-- p.{pno} 視覚モデルによる読み取りに失敗した (送信は済んでいる): {e} -->\n")
            print(f"{stem} p.{pno}: 失敗 {e!r}", flush=True)
        else:
            seconds = round(time.time() - t0, 1)
            ok, total = mark_support(result, ocr_cells(ocr_text))
            report.append({"page": pno, "values": total, "supported": ok, "review": total - ok, "seconds": seconds, **usage, "result": result})
            mds.append(f"<!-- p.{pno} 視覚モデルによる読み取り ({TASKS[task]['label']})。値 {total} 件のうち OCR の裏付けあり {ok} 件。(?) は要確認 -->\n\n{to_markdown(task, result)}")
            cost = f" 費用 {usage['cost_usd']:.3f} USD" if usage.get("cost_usd") is not None else ""
            print(f"{stem} p.{pno}: 値 {total} 裏付けあり {ok} {seconds}s 入力 {usage['input_tokens']} 出力 {usage['output_tokens']} トークン{cost}", flush=True)
        (out_dir / f"{stem}.vlm.md").write_text("\n".join(mds), encoding="utf-8")
        (out_dir / f"{stem}.vlm.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--task", required=True, choices=sorted(TASKS))
    ap.add_argument("--pages", required=True, help="対象のページ (例: 118-122)。試行なので範囲を必ず指定する")
    ap.add_argument("--ndlocr-src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--provider", required=True, choices=["claude-code", "anthropic", "bedrock", "vertex"], help="契約しているサービス。claude-code は Claude Code の CLI を呼ぶ")
    ap.add_argument("--split", type=int, default=2, help="claude-code で、ページ全体のほかに渡す拡大図の分割数 (既定は 2×2。1 で渡さない)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--allow-external", action="store_true", help="ページ画像と OCR 結果を社外のサービスに送信することを認める")
    a = ap.parse_args(argv)
    first, _, last = a.pages.partition("-")
    pages = (int(first), int(last or first))
    n = pages[1] - pages[0] + 1
    if not a.allow_external:
        print(f"送信しませんでした。{n} ページの画像と OCR 結果を {a.provider} ({a.model}) に送信します。契約済みのサービスであることを確かめ、--allow-external を付けて実行してください。", file=sys.stderr)
        return 2

    from . import drawing
    from .line_ocr import PageLineOcr
    from .render import render_page

    ocr = PageLineOcr(a.ndlocr_src)

    def render(src, pno):
        with tempfile.TemporaryDirectory() as tmp:
            return np.array(Image.open(render_page(src, pno, Path(tmp) / "p.png")).convert("RGB"))

    if a.provider == "claude-code":
        if shutil.which("claude") is None:
            print("claude コマンドが見つかりません。", file=sys.stderr)
            return 2
        ask_page = lambda task, img, text: ask_claude_code(a.model, task, img, text, split=a.split)
    else:
        client = make_client(a.provider)
        ask_page = lambda task, img, text: ask(client, a.model, task, img, text)

    def prepare(img):
        # 図面は NDLOCR-Lite ではほとんど読めないので、Vision が使えればその読み取りと向きを使う
        drawn = drawing.read(img) if a.task == "drawing" else None
        if drawn:
            return np.ascontiguousarray(np.rot90(img, drawn["rotation"] // 90)), drawn["lines"]
        return img, ocr.read_page(img)[0]

    report = run(a.input, pages, a.task, Path(a.out), ask_page, a.model, a.provider, prepare, render)
    return 1 if any("error" in p for p in report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
