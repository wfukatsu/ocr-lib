import json

from dococr import evaluate as ev

MD = """<!-- 経路: テキスト層がないため OCR -->

<!-- p.1 帳票: 計画概要書 -->

## 題名

1 号機
空調機更新工事

## 期間

自2025年8月1日

<!-- page -->

<!-- p.2 -->

型式 | ABC-12 (?) | 段数 | 1
- [x] 部品交換
- [ ] 外観確認
- [x] 試運転

~~旧い手順~~ 新しい手順
元の文は \\~\\~記号\\~\\~ を含む
"""


def test_split_pages_and_sections():
    pages = ev.split_pages(MD)
    assert sorted(pages) == [1, 2] and "## 題名" in pages[1] and "型式" in pages[2]
    assert ev.split_pages("本文だけ") == {0: "本文だけ"}
    assert ev.section(pages[1], "題名").split() == ["1", "号機", "空調機更新工事"] and ev.section(pages[1], "分類") == ""


def test_norm_ignores_width_spaces_and_separators():
    assert ev.norm("ＡＢＣ－12 (?)") == ev.norm("abc-12") and ev.norm("95°C") == ev.norm("95℃")
    assert ev.norm("1,000 円。") == ev.norm("1000円") and ev.norm("No.3") == ev.norm("No3")


def test_decimal_point_is_compared():
    assert ev.norm("1.5") != ev.norm("15") and ev.norm("１．５ MPa") == ev.norm("1.5MPa") and ev.norm("0 . 98") == ev.norm("0.98")
    scores, misses = ev.score_case({"pairs": [["定格消費電流", "1.5"]], "contains": ["0.98MPa"]}, "定格消費電流 | 15\n098MPa")
    assert scores == {"contains": [0, 1], "pairs": [0, 1]} and len(misses) == 2
    assert ev.score_case({"pairs": [["定格消費電流", "1.5"]]}, "01 定格消費電流 | 1.5")[0] == {"pairs": [1, 1]}


def test_score_case_counts_hits_and_lists_misses():
    pages = ev.split_pages(MD)
    scores, misses = ev.score_case({"fields": {"題名": ["1号機", "空調機更新工事"], "期間": ["2025年8月1日", "2026年3月31日"]}}, pages[1])
    assert scores == {"fields": [3, 4]} and misses == ["見出しごとの値: 期間 = 2026年3月31日"]
    case = {"pairs": [["型式", "ABC-12"], ["段数", "2"]], "checkboxes": [1, 0, 1], "struck": ["旧い手順"], "not_struck": ["新しい手順", "記号"], "struck_count": 1, "contains": ["試運転", "溶接"]}
    scores, misses = ev.score_case(case, pages[2])
    assert scores == {"contains": [1, 2], "pairs": [1, 2], "checkboxes": [3, 3], "struck": [1, 1], "not_struck": [2, 2], "struck_count": [1, 1]}
    assert len(misses) == 2


def test_checkboxes_are_aligned_when_one_is_missing():
    scores, misses = ev.score_case({"checkboxes": [1, 1, 0, 1]}, "- [x] a\n- [ ] b\n- [x] c\n")
    assert scores["checkboxes"] == [3, 4] and "読み取り 3 件" in misses[0]


def _gt():
    return {"cases": [{"name": "a", "output": "d/doc", "page": 2, "checkboxes": [1, 0, 1]}, {"name": "b", "output": "d/doc", "contains": ["空調機更新工事", "試運転"]},
                      {"name": "c", "output": "d/none", "page": 1, "contains": ["x", "y"]}]}  # fmt: skip


def test_evaluate_totals_and_missing_output(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "doc.md").write_text(MD, encoding="utf-8")
    res = ev.evaluate(_gt(), tmp_path)
    assert res["total"] == {"checkboxes": [3, 3], "contains": [2, 4]}
    assert res["cases"][2]["misses"] == ["出力がない: d/none p.1"]
    assert "| チェック欄の状態 | 3 | 3 | 100.0% |" in ev.report(res)


def test_main_fails_when_a_score_drops(tmp_path, capsys):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "doc.md").write_text(MD, encoding="utf-8")
    gt = tmp_path / "gt.json"
    gt.write_text(json.dumps(_gt()), encoding="utf-8")
    base = tmp_path / "base.json"
    assert ev.main(["--gt", str(gt), "--out", str(tmp_path), "--save", str(base)]) == 0
    assert ev.main(["--gt", str(gt), "--out", str(tmp_path), "--baseline", str(base)]) == 0
    (tmp_path / "d" / "doc.md").write_text(MD.replace("- [x] 試運転", "- [ ] 試運転"), encoding="utf-8")
    assert ev.main(["--gt", str(gt), "--out", str(tmp_path), "--baseline", str(base)]) == 1
    assert "a / チェック欄の状態: 3/3 → 2/3" in capsys.readouterr().err


def test_pair_value_reads_markdown_tables_and_skips_numbering_and_empty_cells():
    assert ev.pair_value("| 01  種別 |   | うず巻 | 備考 |", "種別") == "うず巻"
    assert ev.pair_value("型式 | ABC-12 (?) | 段数 | 1", "段数") == "1" and ev.pair_value("型式 |", "型式") is None
