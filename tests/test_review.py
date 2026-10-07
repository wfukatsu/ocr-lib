import json

from dococr import review


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def make(tmp_path):
    base = tmp_path / "仕様書" / "spec"
    write(tmp_path / "仕様書" / "spec.meta.json", {"status": ["success"], "pages": [
        {"page": 1, "page_collapsed": False, "ink_covered": 0.95},
        {"page": 2, "page_collapsed": True, "ink_covered": 0.4},
        {"page": 3, "page_collapsed": False, "ink_covered": None},
    ]})
    write(tmp_path / "仕様書" / "spec.strike.json", [
        {"page": 2, "certain": True, "reason": "取り消し線 (行全体)", "text": "確定した行"},
        {"page": 2, "certain": False, "reason": "行の一部に取り消し線。範囲は位置からの推定", "candidate": "一部"},
        {"page": 3, "certain": False, "reason": "取り消し線らしい線があるが、対応する行がない", "candidate": ""},
    ])
    write(tmp_path / "仕様書" / "spec.checkbox.json", [
        {"page": 1, "text": "■a.項目", "checked": True, "verified": True},
        {"page": 1, "review": True, "reason": "OCR が読んだ記号と、画像の四角の塗りが食い違う", "text": "■b.項目"},
    ])
    write(tmp_path / "台帳" / "p.meta.json", {"status": ["success"], "pages": [{"page": 1, "form": "備品台帳", "page_collapsed": False, "ink_covered": None}]})
    write(tmp_path / "台帳" / "p.form_review.json", [{"page": 1, "form": "備品台帳", "value": "良奸 (別の読み: 良好)"}])
    write(tmp_path / "bad.meta.json", {"status": ["failure"], "pages": []})


def test_collect_gathers_only_what_needs_review(tmp_path):
    make(tmp_path)
    rows = review.collect(tmp_path)
    assert [(r["file"], r["page"], r["kind"]) for r in rows] == [
        ("bad", 0, "failed"),
        ("仕様書/spec", 1, "checkbox"),
        ("仕様書/spec", 2, "collapsed"),
        ("仕様書/spec", 2, "strike"),
        ("仕様書/spec", 2, "unread"),
        ("台帳/p", 1, "form"),
    ]
    assert review.summarize(rows) == {"total": 6, "by_kind": {"failed": 1, "checkbox": 1, "collapsed": 1, "strike": 1, "unread": 1, "form": 1}, "files": 3, "pages": 4}


def test_markdown_and_csv(tmp_path):
    make(tmp_path)
    assert review.main([str(tmp_path), "-o", str(tmp_path / "r.md"), "--csv", str(tmp_path / "r.csv")]) == 0
    md = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert "3 ファイル・4 ページに、6 件あります。" in md and "## 仕様書/spec" in md
    assert "| 2 | 未読領域 | 文字領域のインクのうち行として読めたのは 40% |" in md
    assert "良奸 (別の読み: 良好)" in (tmp_path / "r.csv").read_text(encoding="utf-8-sig")


def test_drawing_pages_are_listed_with_how_they_were_read(tmp_path):
    meta = {"status": ["success"], "pages": [{"page": 1, "ink_covered": None, "drawing": True, "drawing_lines": 120}, {"page": 2, "ink_covered": None, "drawing": True, "drawing_lines": None}]}
    (tmp_path / "zu.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    rows = review.collect(tmp_path)
    assert [(r["page"], r["kind"]) for r in rows] == [(1, "drawing"), (2, "drawing")]
    assert "参考の読み取り (120 行)" in rows[0]["detail"] and "画像のまま扱う" in rows[1]["detail"]
