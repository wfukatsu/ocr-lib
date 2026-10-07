import base64
import io
import json
from types import SimpleNamespace

import numpy as np
from PIL import Image

from dococr import vlm

V = lambda value, unsure=False: {"value": value, "unsure": unsure}
RESULT = {"tables": [{"title": "軸受の測定", "columns": ["項目", "基準値", "測定値"], "rows": [[V("すきま"), V("0.05"), V("0.04")], [V("振れ"), V("0.02"), V("0.03", True)], [V("温度"), V(""), V("41")]]}]}


class FakeClient:
    def __init__(self, result=RESULT):
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)
        self.result = result

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=json.loads(json.dumps(self.result)))], usage=SimpleNamespace(input_tokens=1200, output_tokens=300))


def test_encode_image_shrinks_large_pages():
    data, scale = vlm.encode_image(np.full((1000, 4000, 3), 255, np.uint8), max_side=2000)
    assert scale == 0.5 and Image.open(io.BytesIO(base64.b64decode(data))).size == (2000, 500)
    assert vlm.encode_image(np.full((100, 200, 3), 255, np.uint8))[1] == 1.0


def test_ask_sends_image_and_ocr_text_and_forces_the_schema():
    client = FakeClient()
    result, usage = vlm.ask(client, "m", "measurement", np.full((50, 80, 3), 255, np.uint8), "すきま | 0.05")
    kw = client.calls[0]
    assert kw["model"] == "m" and kw["tool_choice"] == {"type": "tool", "name": "record"} and kw["tools"][0]["input_schema"] == vlm.TASKS["measurement"]["schema"]
    image, text = kw["messages"][0]["content"]
    assert image["source"]["media_type"] == "image/png" and "すきま | 0.05" in text["text"] and "推測で埋めず" in kw["system"]
    assert result == RESULT and usage == {"input_tokens": 1200, "output_tokens": 300, "image_scale": 1.0}


def test_values_are_trusted_only_when_the_ocr_text_backs_them():
    result = json.loads(json.dumps(RESULT))
    ok, total = vlm.mark_support(result, vlm.ocr_cells("すきま 0.05 0.04 振れ 0.02 0.03 温度"))
    rows = result["tables"][0]["rows"]
    assert (ok, total) == (7, 8)  # 空の値は数えない。「41」は OCR にない
    assert rows[0][2] == {"value": "0.04", "unsure": False, "supported": True, "review": False}
    assert rows[1][2]["supported"] and rows[1][2]["review"]  # モデルが自信がないとした値は、裏付けがあっても要確認
    assert not rows[2][2]["supported"] and rows[2][2]["review"] and "supported" not in rows[2][1]
    md = vlm.to_markdown("measurement", result)
    assert "### 軸受の測定" in md and "| すきま | 0.05 | 0.04 |" in md and "| 振れ | 0.02 | 0.03 (?) |" in md and "| 温度 |  | 41 (?) |" in md


def test_short_values_need_a_whole_reading_and_long_values_need_boundaries():
    cells = vlm.ocr_cells("測定日 2025年10月5日 | 0.12 MPa\n型式 A-15 | 5.0\n材質:SUS316L。")
    assert "0.12" in cells and "測定日2025年10月5日" in cells
    # 別の数値や日付の一部に当たるだけでは、裏付けにしない
    assert not vlm.supported("5", cells) and not vlm.supported("12", cells) and not vlm.supported("0.1", cells) and not vlm.supported("316", cells)
    assert vlm.supported("0.12", cells) and vlm.supported("5.0", cells) and vlm.supported("A-15", cells) and vlm.supported("MPa", cells)
    assert vlm.supported("SUS316L", cells) and vlm.supported("2025年10月5日", cells)  # 読み取りの一部でも、語の切れ目で始まり終わる


def test_failed_page_is_logged_as_sent_and_keeps_earlier_results(tmp_path):
    def ask_page(task, img, text):
        if len(calls) == 1:
            calls.append(None)
            raise RuntimeError("timeout")
        calls.append(None)
        return json.loads(json.dumps(RESULT)), {"input_tokens": 1, "output_tokens": 1}

    calls = []
    report = vlm.run("doc.pdf", (1, 3), "measurement", tmp_path, ask_page, "m", "claude-code", lambda img: (img, []), lambda src, pno: np.full((50, 80, 3), 255, np.uint8))
    assert [("error" in r) for r in report] == [False, True, False] and "timeout" in report[1]["error"]
    log = (tmp_path / "sent_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(l)["page"] for l in log] == [1, 2, 3]  # 応答を受け取れなかったページも、送ったことは残る
    saved = json.loads((tmp_path / "doc.vlm.json").read_text(encoding="utf-8"))
    assert [r["page"] for r in saved] == [1, 2, 3] and "p.2 視覚モデルによる読み取りに失敗した" in (tmp_path / "doc.vlm.md").read_text(encoding="utf-8")


def test_drawing_markdown():
    result = {"title_block": {"name": V("保管棚 構造図"), "drawing_no": V("L-1234")}, "parts": [{"no": V("1"), "name": V("胴板"), "material": V("SS400")}]}
    vlm.mark_support(result, vlm.ocr_cells("保管棚 構造図 1 胴板"))
    md = vlm.to_markdown("drawing", result)
    assert "- 名称: 保管棚 構造図" in md and "- 図番: L-1234 (?)" in md and "| 1 | 胴板 | SS400 (?) |  |" in md


def test_run_writes_results_and_logs_what_was_sent(tmp_path):
    client = FakeClient()
    lines = [{"box": [0, 0, 50, 20], "text": "すきま"}, {"box": [60, 0, 100, 20], "text": "0.05"}]
    ask_page = lambda task, img, text: vlm.ask(client, "m", task, img, text)
    report = vlm.run("doc.pdf", (3, 4), "measurement", tmp_path, ask_page, "m", "anthropic", lambda img: (img, lines), lambda src, pno: np.full((50, 80, 3), 255, np.uint8))
    assert [r["page"] for r in report] == [3, 4] and report[0]["values"] == 8 and report[0]["supported"] == 2 and len(client.calls) == 2
    log = [json.loads(l) for l in (tmp_path / "sent_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(l["file"], l["page"], l["provider"], l["model"]) for l in log] == [("doc.pdf", 3, "anthropic", "m"), ("doc.pdf", 4, "anthropic", "m")]
    md = (tmp_path / "doc.vlm.md").read_text(encoding="utf-8")
    assert md.count("視覚モデルによる読み取り (測定記録)") == 2 and "OCR の裏付けあり 2 件" in md and (tmp_path / "doc.vlm.json").exists()


def test_nothing_is_sent_without_explicit_permission(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(vlm, "make_client", lambda provider: (_ for _ in ()).throw(AssertionError("送信してはいけない")))
    rc = vlm.main(["doc.pdf", "--task", "measurement", "--pages", "3-4", "--ndlocr-src", "x", "--out", str(tmp_path / "o"), "--provider", "anthropic"])
    assert rc == 2 and "送信しませんでした" in capsys.readouterr().err and not (tmp_path / "o").exists()


def test_tiles_cover_the_page_in_reading_order_with_overlap():
    img = np.arange(100 * 200, dtype=np.uint32).reshape(100, 200)
    parts = vlm.tiles(img, 2, overlap=0.1)
    assert [p.shape for p in parts] == [(55, 110)] * 4 and parts[0][0, 0] == img[0, 0] and parts[1][0, -1] == img[0, -1] and parts[3][-1, -1] == img[-1, -1]


def _cli(structured, is_error=False):
    seen = {}

    def runner(cmd, **kw):
        seen.update(cmd=cmd, kw=kw, files=sorted(p.name for p in __import__("pathlib").Path(kw["cwd"]).iterdir()))
        events = [{"type": "system"}, {"type": "result", "is_error": is_error, "result": "x", "structured_output": structured, "total_cost_usd": 0.12,
                                       "usage": {"input_tokens": 4, "cache_creation_input_tokens": 5000, "cache_read_input_tokens": 1000, "output_tokens": 300}}]  # fmt: skip
        return SimpleNamespace(stdout="Warning: no stdin\n" + json.dumps(events), stderr="")

    return runner, seen


def test_claude_code_is_given_only_the_page_images_and_the_read_tool():
    runner, seen = _cli(RESULT)
    result, usage = vlm.ask_claude_code("m", "measurement", np.full((3000, 2200, 3), 255, np.uint8), "すきま | 0.05", runner=runner)
    cmd = seen["cmd"]
    assert result == RESULT and usage == {"input_tokens": 6004, "output_tokens": 300, "cost_usd": 0.12, "images": 5}
    assert seen["files"] == ["page.png", "part1.png", "part2.png", "part3.png", "part4.png"]
    opt = lambda name: cmd[cmd.index(name) + 1]
    assert cmd[:2] == ["claude", "-p"] and opt("--tools") == "Read" and opt("--model") == "m" and opt("--add-dir") == seen["kw"]["cwd"]
    assert "--strict-mcp-config" in cmd and json.loads(opt("--mcp-config")) == {"mcpServers": {}}  # 連携先は使わせない
    assert json.loads(opt("--json-schema")) == vlm.TASKS["measurement"]["schema"] and "すきま | 0.05" in cmd[2] and "part4.png" in cmd[2]


def test_claude_code_small_page_is_sent_whole_and_errors_are_raised():
    runner, seen = _cli(RESULT)
    vlm.ask_claude_code("m", "measurement", np.full((800, 600, 3), 255, np.uint8), "", runner=runner)
    assert seen["files"] == ["page.png"]
    for bad in (_cli(RESULT, is_error=True)[0], _cli(None)[0]):
        try:
            vlm.ask_claude_code("m", "measurement", np.full((80, 60, 3), 255, np.uint8), "", runner=bad)
        except RuntimeError as e:
            assert "構造化した結果を返さなかった" in str(e)
        else:
            raise AssertionError("エラーにならなかった")
