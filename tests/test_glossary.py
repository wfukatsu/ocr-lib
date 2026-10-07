import json

from dococr import glossary as gl, review
from dococr.crosscheck import settle_with_glossary

ROWS = [{"term": t, "kind": k, "count": 3, "sources": []} for t, k in [
    ("V-AB-016", gl.MODEL), ("XYP1A", gl.MODEL), ("XYP1B", gl.MODEL), ("SUS316L", gl.MODEL),
    ("自動梱包ロボット", gl.WORD), ("パレタイザー", gl.WORD), ("上部シャッター", gl.WORD), ("乾燥装置", gl.WORD), ("検品ステーション", gl.WORD), ("ラッピング", gl.WORD),
]]  # fmt: skip
G = gl.Glossary(ROWS)


def test_tokens_find_model_numbers_and_noun_compounds():
    found = [(t, k) for t, k, _ in gl.tokens("ＸＹＰ１Ａ(自動梱包ロボットA)は SUS316L 製で、型式は KX416-2 とする。X棟 PUMP 12")]
    assert found == [("XYP1A", gl.MODEL), ("自動梱包ロボット", gl.WORD), ("SUS316L", gl.MODEL), ("KX416-2", gl.MODEL)]


def test_terms_in_text_skips_words_cut_by_line_wraps_and_trailing_particles():
    text = "自動梱包ロボットの部品交\n換を行う。潤滑油等を補充する。\nラッピング\n\n以上。\nコンベアピット及び配管"
    assert [t for t, _ in gl.terms_in_text(text)] == ["自動梱包ロボット", "潤滑油", "ラッピング", "コンベアピット"]


def test_only_confusable_single_character_differences_are_fixed():
    assert G.check("自動梱包ロポット", gl.WORD) == ("fix", "自動梱包ロボット")  # ポ と ボ
    assert G.check("パレタイザ一", gl.WORD) == ("fix", "パレタイザー")  # 長音と漢数字の一
    assert G.check("V-AB-0l6", gl.MODEL) == ("fix", "V-AB-016")  # 小文字が混ざった読み取りは、型番として書けない
    # 型番として書ける読み取りは、紛らわしい文字 1 つの違いでも書き換えない (別の実在する番号かもしれない)
    assert G.check("V-AB-O16", gl.MODEL) == ("suggest", "V-AB-016")
    assert G.check("下部シャッター", gl.WORD) == ("suggest", "上部シャッター")  # 別の実在する語かもしれない
    assert G.check("V-AB-076", gl.MODEL) == ("suggest", "V-AB-016")  # 別の番号かもしれない
    assert G.check("XYP1C", gl.MODEL) == ("ok", None)  # 候補が 2 つあり、決まらない
    assert G.check("乾燥装直", gl.WORD) == ("suggest", "乾燥装置") and G.check("燥装置", gl.WORD) == ("ok", None)  # 短い語は補正しない
    assert G.check("上部シャッター", gl.WORD) == ("ok", None) and G.check("空調倉庫設備", gl.WORD) == ("ok", None)


def test_well_formed_model_numbers_are_never_rewritten_to_a_neighbour():
    g = gl.Glossary([{"term": t, "kind": gl.MODEL, "count": 1, "sources": []} for t in ("P-18", "TK-10", "Q-1A-207")])
    for read in ("P-1B", "TK-1D", "TK-1O", "Q-IA-207"):
        assert g.correct(f"{read} の点検") == (f"{read} の点検", [], [{"from": read, "to": g.check(read, gl.MODEL)[1]}])
    assert g.correct("P一18 と Tk-10") == ("P-18 と TK-10", [{"from": "P一18", "to": "P-18"}, {"from": "Tk-10", "to": "TK-10"}], [])  # ハイフンと大文字・小文字は直す


def test_correct_rewrites_in_place_and_reports():
    text, fixes, sugg = G.correct("1. 自動梱包ロポット(V一AB一0l6)の下部シャッターを開放する")
    assert text == "1. 自動梱包ロボット(V-AB-016)の下部シャッターを開放する"
    assert fixes == [{"from": "自動梱包ロポット", "to": "自動梱包ロボット"}, {"from": "V一AB一0l6", "to": "V-AB-016"}] and sugg == [{"from": "下部シャッター", "to": "上部シャッター"}]
    assert G.correct("V一AB一016 の点検") == ("V-AB-016 の点検", [{"from": "V一AB一016", "to": "V-AB-016"}], [])
    assert G.correct("XYP1A 自動梱包ロボット") == ("XYP1A 自動梱包ロボット", [], [])
    assert G.correct("材質 Sus316L") == ("材質 SUS316L", [{"from": "Sus316L", "to": "SUS316L"}], [])  # 大文字と小文字
    assert G.correct("ＸＹＰ１Ａ") == ("ＸＹＰ１Ａ", [], [])  # 全角は書き換えない


def test_apply_marks_lines_and_lists_suggestions_only_for_unsure_lines():
    lines = [{"text": "自動梱包ロポット", "conf": 0.9}, {"text": "下部シャッター", "conf": 0.9}, {"text": "下部シャッター", "conf": 0.4}, {"text": "検品ステーション", "conf": 0.9}]
    report = G.apply(lines)
    assert lines[0]["text"] == "自動梱包ロボット" and lines[0]["glossary"] == [{"from": "自動梱包ロポット", "to": "自動梱包ロボット"}] and "glossary" not in lines[1]
    assert report == {"fixes": [{"from": "自動梱包ロポット", "to": "自動梱包ロボット"}], "suggestions": [{"from": "下部シャッター", "to": "上部シャッター"}]}


def test_disagreeing_readings_settle_on_the_one_in_the_glossary():
    assert G.pick("SUS316L", "SUS3I6L") == "SUS316L" and G.pick("5US316L", "SUS316L") == "SUS316L"
    assert G.pick("XYP1A", "XYP1B") is None and G.pick("ABC", "ABD") is None and G.pick("XYP1A", None) is None
    res = settle_with_glossary({"text": "5US316L", "certain": False, "ndl": "5US316L", "alt": "SUS316L"}, G)
    assert (res["text"], res["certain"], res["by"]) == ("SUS316L", True, "glossary")
    keep = {"text": "x", "certain": False, "ndl": "x", "alt": "y"}
    assert settle_with_glossary(dict(keep), G) == keep and settle_with_glossary(dict(keep), None) == keep


def _docx(tmp_path, name, text):
    from helpers import make, p, r

    path = make(tmp_path, p(r(text)))
    return path.rename(tmp_path / name)


def test_build_reads_text_files_and_file_names_and_round_trips(tmp_path):
    src = tmp_path / "in"
    (src / "図面").mkdir(parents=True)
    _docx(tmp_path, "a.docx", "自動梱包ロボット(XYP1A)と自動梱包ロボット(XYP1B)を点検する。検品ステーションは対象外。").rename(src / "a.docx")
    (src / "図面" / "TK-9(回転式保管棚)_構造図.PDF").write_bytes(b"")  # 読めないファイルでも、ファイル名は使う
    (src / "1. 概要.txt").write_text("対象外")
    logs = []
    rows = gl.build(src, log=logs.append)
    by = {r["term"]: r for r in rows}
    assert by["自動梱包ロボット"]["count"] == 2 and by["TK-9"]["kind"] == gl.MODEL and by["回転式保管棚"]["kind"] == gl.NAME
    assert "検品ステーション" not in by and "XYP1A" not in by and "1" not in by  # 1 回しか出ない語と、ファイルの連番は載せない
    assert any("読めなかった" in m for m in logs) and any("a.docx から候補" in m for m in logs)
    gl.save(rows, tmp_path / "g.tsv")
    assert gl.load(tmp_path / "g.tsv") == rows and len(gl.Glossary(gl.load(tmp_path / "g.tsv"))) == len(rows)


def test_suggestions_are_listed_for_review(tmp_path):
    (tmp_path / "d.meta.json").write_text(json.dumps({"status": ["success"], "pages": []}), encoding="utf-8")
    (tmp_path / "d.glossary.json").write_text(json.dumps([{"page": 4, "applied": True, "from": "a", "to": "b"}, {"page": 4, "applied": False, "from": "下部シャッター", "to": "上部シャッター"}]), encoding="utf-8")
    rows = review.collect(tmp_path)
    assert [(r["page"], r["kind"]) for r in rows] == [(4, "glossary")] and "下部シャッター → 上部シャッター" in rows[0]["detail"]


def test_near_misses_of_frequent_terms_are_listed_even_on_confident_lines():
    g = gl.Glossary([{"term": "監督職員", "kind": gl.WORD, "count": 148, "sources": []}, {"term": "出庫検査", "kind": gl.WORD, "count": 2, "sources": []}])
    lines = [{"text": "監督報員に提出する", "conf": 0.95}, {"text": "入庫検査を測る", "conf": 0.95}]
    assert g.apply(lines) == {"fixes": [], "suggestions": [{"from": "監督報員", "to": "監督職員"}]}  # まれな語の 1 文字違いは、別の語かもしれない
    assert lines[0]["text"] == "監督報員に提出する"  # 書き換えはしない


def test_katakana_that_look_alike_are_fixed():
    g = gl.Glossary([{"term": t, "kind": gl.WORD, "count": 2, "sources": []} for t in ("冷温水機ユニット", "ディフューザー")])
    assert g.correct("冷温水機コニットとディフェーザー")[0] == "冷温水機ユニットとディフューザー"
