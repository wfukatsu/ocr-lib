from dococr import crosscheck as cc


def test_reconcile():
    assert cc.reconcile("40", "40") == ("40", True)
    assert cc.reconcile("60", "6") == ("6", False)  # 数字だけの値は照合先を採り、要確認にする
    assert cc.reconcile("10", "No") == ("No", False)
    assert cc.reconcile("B", "=") == ("B", False)  # 照合先が値らしくなければ元を採る
    assert cc.reconcile("式形", "形式") == ("式形", False)  # どちらも日本語で食い違えば要確認
    assert cc.reconcile("数", "段数") == ("段数", False)  # 1 文字欠けは長い方で補う
    assert cc.reconcile("95", None) == ("95", True)  # 照合していない


def test_reconcile_keeps_unverified_japanese_for_review():
    # 照合先が日本語を読めていなくても確定にはしない (「無」を「無異」と読む誤りがある)
    assert cc.reconcile("横型", "fe") == ("横型", False)
    assert cc.reconcile("無異", "") == ("無異", False)
    assert cc.reconcile("登録No", "HlSRNo") == ("登録No", False)


def test_reconcile_units():
    assert cc.reconcile("40", "40°C") == ("40°C", True)  # 単位の有無だけの違い
    assert cc.reconcile("60C", "60°C") == ("60°C", True)  # 度の記号を読めた方を採る
    assert cc.reconcile("50", "90°C") == ("90°C", False)  # 数値が違えば要確認


def cell(text, ndl=None, alt=None, certain=True, x=0, y=0):
    return {"text": text, "ndl": ndl or text, "alt": alt, "certain": certain, "cell": [x, y, x + 100, y + 40], "box": [x, y, x + 50, y + 30]}


def test_vote_with_a_third_engine():
    rows = [[cell("流量"), cell("6", "60", "6", False, x=100)], [cell("口径", y=40), cell("40", "10", "40", False, x=100, y=40)], [cell("段数", y=80), cell("1", "1-", "1", False, x=100, y=80)]]
    lines = [("6", (110, 5, 130, 30)), ("10", (110, 45, 140, 70)), ("流量 6 1", (0, 80, 300, 110))]
    assert cc.vote(rows, lines) == 2
    assert rows[0][1]["text"] == "6" and rows[0][1]["by"] == "vote"
    assert rows[1][1]["text"] == "10" and rows[1][1]["certain"]  # 3 つ目が NDL 側と一致すれば NDL を採る
    assert not rows[2][1]["certain"]  # セルをはみ出す読み取りは票に数えない


def test_vote_keeps_a_differing_third_reading_as_a_candidate():
    rows = [[cell("有無"), cell("無異", "無異", "", False, x=100)]]
    assert cc.vote(rows, [("無", (110, 5, 135, 30))]) == 0
    assert not rows[0][1]["certain"] and rows[0][1]["third"] == "無"
