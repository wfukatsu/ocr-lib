import numpy as np

from dococr import form_regions as fr

# ---- 欄の中に文章や表が入る帳票

FORM = {"name": "t", "labels": {"題名": "right", "作業概要": "right", "変更理由": "right", "分類": "below"}}


def L(text, x, y, w=200, h=30):
    return {"box": [x, y, x + w, y + h], "text": text, "conf": 0.9}


def test_label_score_tolerates_misread_vertical_labels():
    assert fr._label_score("14名", "題名") == 0.5
    assert fr._label_score("11当性評価", "妥当性評価") == 0.8
    assert fr._label_score("実予算額の内訳61", "予算額の内訳") == 1.0


def test_find_labels_vertical_exact_and_inline():
    cells = [(0, 0, 60, 150), (0, 200, 60, 400), (700, 0, 200, 60), (1000, 0, 300, 140)]
    lines = [L("14", 10, 20, 40), L("名", 10, 90, 40), L("作1511要", 10, 300, 40), L("分類", 720, 15, 80), L("変更理由", 1010, 10), L("本文", 1010, 80)]
    found = fr.find_labels(cells, lines, list(FORM["labels"]))
    assert found["題名"] == (0, 0, 60, 150) and found["作業概要"] == (0, 200, 60, 400) and found["分類"] == (700, 0, 200, 60)
    assert found["変更理由"][:3] == (1000, 0, 300) and found["変更理由"][3] < 60  # 見出しと値が同じ欄にある場合は、見出しの行だけを欄とする


def test_read_regions_gives_up_early_on_pages_without_the_labels():
    """帳票ではないページでは、時間のかかる照合と読み直しを行わない。"""
    called = []
    lines = [L("測定値", 100, 100), L("12.5", 400, 100, 80)]
    img = np.full((500, 1800, 3), 255, dtype=np.uint8)
    assert fr.read_regions(img, lambda im: lines, FORM, checker=lambda im, ls: called.append("check"), min_labels=6) is None and called == []
    assert fr.read_regions(img, lambda im: lines, FORM, checker=lambda im, ls: called.append("check")) is not None and called == ["check"]


def test_longer_label_wins_on_a_tie():
    cells = [(0, 0, 60, 300)]
    assert list(fr.find_labels(cells, [L("予算額の内訳", 10, 100, 40)], ["予算額", "予算額の内訳"])) == ["予算額の内訳"]


def test_read_regions_assigns_lines_to_the_label_on_their_left_or_above(monkeypatch):
    cells = [(0, 0, 60, 150), (700, 0, 60, 150), (1400, 0, 200, 60)]
    lines = [L("14", 10, 20, 40), L("名", 10, 90, 40), L("空調機更新工事", 100, 50), L("変-理1由", 710, 60, 40), L("風量の低下が顕著", 800, 40), L("部品交換を実施する", 800, 90),
             L("分類", 1420, 15, 80), L("更新", 1420, 80, 80), L("欄の外の文字", 100, 400)]
    monkeypatch.setattr(fr, "find_cells", lambda img, dpi, min_fill: (cells, None))
    res = fr.read_regions(np.zeros((500, 1800, 3), dtype=np.uint8), lambda img: lines, FORM)
    assert res["fields"] == {"題名": "空調機更新工事", "変更理由": "風量の低下が顕著\n部品交換を実施する", "分類": "更新"}
    assert res["rest"] == "欄の外の文字" and res["labels_found"] == 3
    md = fr.regions_markdown(res, FORM)
    assert md.startswith("## 題名\n\n空調機更新工事") and "見出しの欄が見つからなかった項目: 作業概要" in md


# ---- 行検出の取りこぼしと誤読の補正


def test_infer_labels_uses_the_only_narrow_empty_cell_in_the_same_band():
    found = {"題名": (0, 0, 60, 150), "予算額": (700, 0, 60, 150)}
    cells = [*found.values(), (60, 0, 640, 150), (760, 0, 200, 150), (960, 0, 60, 150), (1020, 0, 500, 150), (960, 300, 60, 150)]
    assert fr.infer_labels(cells, found, [["題名", "予算額", "期間"]]) == ["期間"]
    assert found["期間"] == (960, 0, 60, 150)


def test_infer_labels_does_not_guess_between_several_candidates():
    found = {"題名": (0, 0, 60, 150)}
    cells = [(0, 0, 60, 150), (700, 0, 60, 150), (960, 0, 60, 150)]
    assert fr.infer_labels(cells, found, [["題名", "予算額"]]) == [] and "予算額" not in found


def _ring(size=40, r=13, t=2):
    yy, xx = np.mgrid[:size, :size]
    d = np.hypot(xx - size / 2, yy - size / 2)
    return (d <= r) & (d >= r - t)


def test_circle_mark_is_told_apart_from_letters():
    assert fr.is_circle_mark(_ring())
    tall = np.zeros((40, 40), bool)
    tall[5:35, 14:16] = tall[5:35, 24:26] = tall[5:7, 14:26] = tall[33:35, 14:26] = True  # 縦長の 0
    assert not fr.is_circle_mark(tall)
    filled = np.zeros((40, 40), bool)
    filled[8:32, 8:32] = True  # 塗りつぶし
    assert not fr.is_circle_mark(filled)
    assert not fr.is_circle_mark(np.zeros((40, 40), bool))


def test_clean_lines_drops_dotted_rule_fragments_and_normalizes_circles():
    img = np.full((200, 400), 255, np.uint8)
    img[100:140, 100:140][_ring()] = 0
    lines = [L("--", 10, 10, 22, 20), L("fe)", 100, 100, 40, 40), L("金額", 200, 100, 100, 40)]
    out = fr.clean_lines(img, lines)
    assert [l["text"] for l in out] == ["○", "金額"] and out[0]["certain"] is True


class _Reader:
    def __init__(self, certain=True):
        self.certain = certain

    def read(self, crop):
        return {"text": "自2023年6月1日", "certain": self.certain, "ndl": "", "alt": None}


def _low_cell_page():
    img = np.full((300, 1000, 3), 255, np.uint8)
    img[40:80, 100:600] = 0  # 欄の中の 1 行
    return img, np.zeros((300, 1000), np.uint8), [(50, 20, 800, 100)]


def test_reread_low_cells_replaces_uncertain_fragments_with_the_cell_reading():
    img, grid, cells = _low_cell_page()
    lines = [L("2023", 300, 40, 80, 40), {**L("1-", 500, 40, 40, 40), "certain": False}, L("欄の外", 100, 200)]
    out = fr.reread_low_cells(img, grid, cells, lines, _Reader())
    assert sorted(l["text"] for l in out) == ["欄の外", "自2023年6月1日"]


def test_reread_low_cells_keeps_lines_when_nothing_is_uncertain_or_reread_is_unsure():
    img, grid, cells = _low_cell_page()
    sure = [L("2023", 300, 40, 80, 40)]
    assert fr.reread_low_cells(img, grid, cells, sure, _Reader()) == sure
    unsure = [{**L("1-", 500, 40, 40, 40), "certain": False}]
    assert fr.reread_low_cells(img, grid, cells, unsure, _Reader(certain=False)) == unsure


def test_reread_low_cells_reads_cells_the_line_detector_missed_entirely():
    img, grid, cells = _low_cell_page()
    outside = [L("欄の外", 100, 200)]
    out = fr.reread_low_cells(img, grid, cells, outside, _Reader(certain=False))
    # ほかに読み取りがないので、確定できなかった値も採る (要確認として残る)
    assert sorted(l["text"] for l in out) == ["欄の外", "自2023年6月1日"] and [l["certain"] for l in out if l.get("by") == "cell"] == [False]
    blank = np.full((300, 1000, 3), 255, np.uint8)
    assert fr.reread_low_cells(blank, grid, cells, outside, _Reader()) == outside  # 文字のない欄は読まない
    assert fr.reread_low_cells(img, grid, [(50, 20, 60, 100)], outside, _Reader()) == outside  # 縦書きの見出しの細い欄は対象外
