"""Lossless identifiers shared by DART source and calculation layers."""
import re
from typing import Any


def normalize_stock_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1].strip()
    if re.fullmatch(r"[0-9]{1,6}", text):
        return text.zfill(6)
    return text if re.fullmatch(r"[0-9A-Z]{6}", text) else ""
