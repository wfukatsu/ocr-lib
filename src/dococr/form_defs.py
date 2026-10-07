"""帳票の定義。

読み取りの処理は持たない。定義はライブラリの中に置かず、JSON のファイルに書いて `load` で読む
(コマンドでは `--forms`)。定義がなければ、罫線のあるページは定義のない罫線の帳票として読む。

```json
{"forms": [
  {"name": "備品台帳", "layout": "cells",
   "labels": ["資産番号", "品名", "型番", "区分"], "types": {"区分": "[ABC]"}, "min_labels": 3},
  {"name": "計画概要書", "layout": "regions",
   "labels": {"題名": "right", "担当部署": "below", "概要": "right"}, "order": [["題名", "概要"]]}
]}
```

- `layout`: `cells` はセルごとに値が入る帳票、`regions` は欄の中に文章や表が入る帳票。
- `labels`: `cells` では見出しの語の一覧。`regions` では、見出しごとに値の欄が右隣 (`right`) か真下 (`below`) か。
- `types`: 見出しの右隣のセルが取りうる値の正規表現。
- `order` (`regions` のみ): 同じ段に左から並ぶ見出しの組。行検出が見落とした見出しの欄を、並び順から推定するのに使う。
- `min_labels`: この帳票とみなすのに要る見出しの数。省略すると `cells` は 8、`regions` は 6 (見出しがそれより少なければ、その数)。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

CELLS, REGIONS = "cells", "regions"
DEFAULT_MIN_LABELS = {CELLS: 8, REGIONS: 6}


@dataclass(frozen=True)
class FormDefs:
    """読み取りに使う帳票の定義の組。"""

    cells: tuple[dict, ...] = ()  # セルごとに値が入る帳票
    regions: tuple[dict, ...] = ()  # 欄の中に文章や表が入る帳票

    def __bool__(self) -> bool:
        return bool(self.cells or self.regions)


def define(name: str, labels, layout: str = CELLS, types: dict[str, str] | None = None, order: list[list[str]] | None = None, min_labels: int | None = None) -> dict:
    """帳票の定義を 1 つ作る。書き方の誤りは、読み取りを始める前にここで知らせる。"""
    if not name:
        raise ValueError("帳票の定義に name がない")
    if layout not in (CELLS, REGIONS):
        raise ValueError(f"{name}: layout は {CELLS} か {REGIONS}")
    if not labels:
        raise ValueError(f"{name}: labels がない")
    if layout == REGIONS:
        if not isinstance(labels, dict) or any(v not in ("right", "below") for v in labels.values()):
            raise ValueError(f"{name}: {REGIONS} の labels は、見出しごとに right か below を持つ")
        labels = dict(labels)
    else:
        labels = list(labels)
    types = dict(types or {})
    for lab, pattern in types.items():
        try:
            re.compile(pattern)
        except re.error as e:
            raise ValueError(f"{name}: types の {lab} が正規表現として読めない: {e}") from None
    unknown = [lab for row in order or [] for lab in row if lab not in labels] + [lab for lab in types if lab not in labels]
    if unknown:
        raise ValueError(f"{name}: labels にない見出し: " + " / ".join(unknown))
    form = {"name": name, "layout": layout, "labels": labels, "types": types, "min_labels": min(min_labels or DEFAULT_MIN_LABELS[layout], len(labels))}
    if layout == REGIONS:
        form["order"] = [list(row) for row in order or []]
    return form


def parse(data: dict | list) -> FormDefs:
    """JSON を読んだ結果 ({"forms": [...]} か、定義の一覧) を FormDefs にする。"""
    items = data.get("forms", []) if isinstance(data, dict) else data
    forms = [define(d.get("name", ""), d.get("labels"), d.get("layout", CELLS), d.get("types"), d.get("order"), d.get("min_labels")) for d in items]
    return FormDefs(cells=tuple(f for f in forms if f["layout"] == CELLS), regions=tuple(f for f in forms if f["layout"] == REGIONS))


def load(path: str | Path | None) -> FormDefs:
    """帳票の定義のファイル (JSON) を読む。path が None なら、定義なし。"""
    if path is None:
        return FormDefs()
    return parse(json.loads(Path(path).read_text(encoding="utf-8")))
