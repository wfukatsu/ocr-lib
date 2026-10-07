"""テストで共有する補助関数。"""
import subprocess
import zipfile

import pytest

from dococr import convert, form_defs

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{type}" Target="{target}"/>
</Relationships>"""


def r(text, rpr="", tag="t"):
    return f'<w:r><w:rPr>{rpr}</w:rPr><w:{tag} xml:space="preserve">{text}</w:{tag}></w:r>'


def p(*runs, style=""):
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}{''.join(runs)}</w:p>"


def make(tmp_path, body, header=""):
    styles = f"""<w:styles {NS}>
      <w:style w:type="paragraph" w:styleId="H1"><w:name w:val="heading 1"/></w:style>
      <w:style w:type="character" w:styleId="Del"><w:name w:val="Deleted"/><w:rPr><w:strike/></w:rPr></w:style>
      <w:style w:type="character" w:styleId="DelChild"><w:name w:val="Deleted child"/><w:basedOn w:val="Del"/></w:style>
    </w:styles>"""
    path = tmp_path / "t.docx"
    with zipfile.ZipFile(path, "w") as z:
        # Word や LibreOffice でも開ける最小構成のパッケージにする
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS.format(type="officeDocument", target="word/document.xml"))
        z.writestr("word/_rels/document.xml.rels", RELS.format(type="styles", target="styles.xml"))
        z.writestr("word/document.xml", f"<w:document {NS}><w:body>{body}</w:body></w:document>")
        z.writestr("word/styles.xml", styles)
        if header:
            z.writestr("word/header1.xml", f"<w:hdr {NS}>{header}</w:hdr>")
    return path


soffice = convert.soffice_path()
needs_soffice = pytest.mark.skipif(soffice is None, reason="LibreOffice がない")


def legacy(path, fmt, tmp_path):
    """テスト用に、新形式のファイルから旧形式のファイルを作る。"""
    out = tmp_path / "legacy"
    subprocess.run([soffice, f"-env:UserInstallation=file://{tmp_path}/profile", "--headless", "--convert-to", fmt, "--outdir", str(out), str(path)], check=True, capture_output=True)
    return out / f"{path.stem}.{fmt}"


# テスト用の架空の帳票の定義
CELL_FORM = form_defs.define(
    "備品台帳",
    ["資産番号(品名)", "親の資産番号(品名)", "分類", "型番", "登録No", "購入日", "購入先", "設置日", "設置者", "設置場所", "定格消費電力", "定格消費電流",
     "保証書No", "重要度", "管理部署", "管理者", "耐用年数", "No", "点検項目", "点検結果", "備考"],
    types={"重要度": r"[SABC]"},
)  # fmt: skip
REGION_FORM = form_defs.define(
    "計画概要書",
    {"題名": "right", "予算額": "right", "期間": "right", "拠点名": "below", "分類": "below", "稼働区分": "below", "設備区分": "below",
     "作業概要": "right", "変更理由": "right", "妥当性評価": "right", "補足": "right", "予算額の内訳": "right", "年度計画": "right"},
    layout="regions",
    order=[["題名", "予算額", "期間"], ["作業概要", "変更理由", "妥当性評価"]],
)  # fmt: skip
FORMS = form_defs.FormDefs(cells=(CELL_FORM,), regions=(REGION_FORM,))
