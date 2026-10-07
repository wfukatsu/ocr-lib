from dococr import mapping as mp

SPECS = ["PA1A(昇降リフトA).pdf", "PA1B(昇降リフトB).pdf", "TD-3A(X棟-A).pdf", "TK1(保管棚).pdf", "TK9(保管棚).pdf", "BL2(ファン).pdf", "00321(倉庫設備).pdf", "PB7B(回転台B).pdf"]
DRAWINGS = ["PA1A・B昇降リフト_外形図.PDF", "TD3A(Y棟-A)_Y棟構造図.PDF", "保管棚(600L)2024年度版_構造図.PDF", "BL2(換気用ファン)取扱説明書.PDF", "PB7B(仮)回転台_断面図.PDF", "ZZ9(予備品)_外形寸法図.PDF"]


def test_parse_name():
    assert mp.parse_name("V-AB-016(表示盤)_構造図") == {"nos": ["V-AB-016"], "name": "表示盤", "kind": "構造図", "tentative": False}
    assert mp.parse_name("PA1A・B昇降リフト_外形図") == {"nos": ["PA1A", "PA1B"], "name": "昇降リフト", "kind": "外形図", "tentative": False}
    assert mp.parse_name("TD3A(Y棟-A)_Y棟構造図")["kind"] == "構造図" and mp.parse_name("DR1B(リフトB)_外形寸法図")["kind"] == "外形寸法図"
    assert mp.parse_name("保管棚(600L)2024年度版_構造図") == {"nos": [], "name": "保管棚(600L)2024年度版", "kind": "構造図", "tentative": False}
    assert mp.parse_name("PB7B(仮)回転台_断面図") == {"nos": ["PB7B"], "name": "回転台", "kind": "断面図", "tentative": True}
    assert mp.parse_name("00321(倉庫設備)")["nos"] == ["00321"] and mp.parse_name("ＡＧＴ４－ＭＩＸ－１(混合機)")["nos"] == ["AGT4-MIX-1"]


def test_build_matches_by_number_and_records_the_basis():
    rows = {r["no"]: r for r in mp.build(SPECS, DRAWINGS) if r["no"]}
    assert rows["PA1A"]["status"] == rows["PA1B"]["status"] == mp.MATCH and "複数の番号で 1 つのファイル" in rows["PA1B"]["related"][0]["note"]
    td = rows["TD-3A"]
    assert td["status"] == mp.VARIANT and "「TD3A」" in td["related"][0]["note"] and "名称が異なる (関連ファイル: Y棟-A)" in td["related"][0]["note"]
    assert rows["BL2"]["status"] == mp.MATCH and "名称が異なる" in rows["BL2"]["related"][0]["note"]
    assert rows["PB7B"]["status"] == mp.MATCH and "(仮)" in rows["PB7B"]["related"][0]["note"] and "名称が異なる" not in rows["PB7B"]["related"][0]["note"]
    assert rows["00321"]["status"] == mp.NONE and rows["00321"]["related"] == []


def test_related_files_without_a_number_are_only_candidates():
    rows = mp.build(SPECS, DRAWINGS)
    by_no = {r["no"]: r for r in rows if r["no"]}
    # 同じ名称の台帳が 2 つあるので、どちらにも候補として挙げ、確定しない
    assert by_no["TK1"]["status"] == by_no["TK9"]["status"] == mp.CANDIDATE
    loose = [r for r in rows if not r["no"]]
    assert [(r["related"][0]["file"], r["related"][0]["status"]) for r in loose] == [("保管棚(600L)2024年度版_構造図.PDF", mp.CANDIDATE), ("ZZ9(予備品)_外形寸法図.PDF", mp.NONE)]


def test_outputs(tmp_path):
    for d, names in (("s", SPECS), ("d", DRAWINGS)):
        (tmp_path / d).mkdir()
        for n in names:
            (tmp_path / d / n).write_bytes(b"")
    (tmp_path / "s" / ".DS_Store").write_text("x")
    assert mp.main(["--items", str(tmp_path / "s"), "--related", str(tmp_path / "d"), "-o", str(tmp_path / "m.md"), "--csv", str(tmp_path / "m.csv")]) == 0
    md = (tmp_path / "m.md").read_text(encoding="utf-8")
    assert "台帳 8 件のうち、関連ファイルが一致 4 件、表記ゆれで一致 1 件、名称からの候補 2 件、関連ファイルなし 1 件。" in md
    assert "| TD-3A | X棟-A | 番号の表記ゆれ | TD3A(Y棟-A)_Y棟構造図.PDF (構造図) |" in md
    assert len((tmp_path / "m.csv").read_text(encoding="utf-8-sig").splitlines()) == 1 + 8 + 2  # 見出し、台帳 8 件、番号が未確定の関連ファイル 2 件


def test_kinds_can_be_replaced():
    assert mp.parse_name("PA1A(昇降リフトA)_点検記録", kinds=("点検記録",))["kind"] == "点検記録"
    assert mp.parse_name("PA1A(昇降リフトA)_外形図", kinds=())["kind"] == ""
