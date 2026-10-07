import json

import pytest

from dococr import form_defs as fd


def test_load_splits_definitions_by_layout_and_fills_defaults(tmp_path):
    path = tmp_path / "forms.json"
    path.write_text(json.dumps({"forms": [
        {"name": "台帳", "labels": ["番号", "名称", "区分"], "types": {"区分": "[AB]"}},
        {"name": "概要", "layout": "regions", "labels": {"題名": "right", "部署": "below"}, "order": [["題名"]], "min_labels": 1},
    ]}, ensure_ascii=False), encoding="utf-8")  # fmt: skip
    defs = fd.load(path)
    assert [f["name"] for f in defs.cells] == ["台帳"] and [f["name"] for f in defs.regions] == ["概要"]
    assert defs.cells[0]["min_labels"] == 3 and defs.cells[0]["types"] == {"区分": "[AB]"}  # 見出しが少ない帳票は、その数まで
    assert defs.regions[0]["min_labels"] == 1 and defs.regions[0]["order"] == [["題名"]]


def test_no_definitions_by_default():
    assert not fd.load(None) and fd.load(None).cells == () and fd.parse([]).regions == ()


@pytest.mark.parametrize("kw", [
    {"name": "", "labels": ["a"]},
    {"name": "x", "labels": []},
    {"name": "x", "labels": ["a"], "layout": "table"},
    {"name": "x", "labels": ["a"], "layout": "regions"},
    {"name": "x", "labels": {"a": "left"}, "layout": "regions"},
    {"name": "x", "labels": ["a"], "types": {"a": "["}},
    {"name": "x", "labels": ["a"], "types": {"b": "."}},
    {"name": "x", "labels": {"a": "right"}, "layout": "regions", "order": [["a", "b"]]},
])  # fmt: skip
def test_mistakes_in_a_definition_are_reported_before_reading(kw):
    with pytest.raises(ValueError):
        fd.define(**kw)
