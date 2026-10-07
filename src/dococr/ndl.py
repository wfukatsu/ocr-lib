"""NDLOCR-Lite のモデルを読み込む。"""
from __future__ import annotations

import argparse
import sys
from functools import lru_cache
from pathlib import Path

MODELS = {
    "det": "model/deim-s-1024x1024.onnx",
    "rec30": "model/parseq-ndl-24x256-30-tiny-189epoch-tegaki3-r8data-202604.onnx",
    "rec50": "model/parseq-ndl-24x384-50-tiny-300epoch-tegaki3-r8data-202604.onnx",
    "rec100": "model/parseq-ndl-24x768-100-tiny-153epoch-tegaki3-r8data-202604.onnx",
}


@lru_cache(maxsize=2)
def load(ndlocr_src: str, detector: bool = True):
    """(ocr モジュール, 行検出器, 30 字用・50 字用・100 字用の認識器) を返す。同じモデルは 1 度だけ読み込む。"""
    src = Path(ndlocr_src)
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    import ocr as ndl

    args = argparse.Namespace(
        det_weights=str(src / MODELS["det"]),
        det_classes=str(src / "config/ndl.yaml"),
        det_score_threshold=0.2,
        det_conf_threshold=0.25,
        det_iou_threshold=0.2,
        rec_weights=str(src / MODELS["rec100"]),
        rec_classes=str(src / "config/NDLmoji.yaml"),
        device="cpu",
    )
    det = ndl.get_detector(args) if detector else None
    return ndl, det, ndl.get_recognizer(args, str(src / MODELS["rec30"])), ndl.get_recognizer(args, str(src / MODELS["rec50"])), ndl.get_recognizer(args)
