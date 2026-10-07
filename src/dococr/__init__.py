"""文書の読み取り: 構造化 OCR、帳票の欄抽出、取り消し線・チェック欄の抽出。

    from dococr import extract_strikes, ocr_files, load_forms

個々の処理は、役割ごとのモジュールにある (README の「モジュールの構成」)。
"""
from .api import NeedsOcr, extract_strikes, ocr_files
from .form_defs import FormDefs, define as define_form, load as load_forms

__version__ = "0.1.0"
__all__ = ["FormDefs", "NeedsOcr", "define_form", "extract_strikes", "load_forms", "ocr_files"]
