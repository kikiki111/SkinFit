"""確認済みの実物写真だけを使う。検索結果から画像URLを推測しない。"""
import json
import re
import unicodedata
from functools import lru_cache
from .config import settings


def _key(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


@lru_cache(maxsize=1)
def _manifest():
    return json.loads((settings.web_dir / "assets/products/manifest.json").read_text())


def media_for(brand: str, name: str):
    for entry in _manifest():
        if _key(brand) == _key(entry["brand"]) and _key(name) == _key(entry["name"]):
            return {k: entry[k] for k in ("src", "source_url", "credit")}
    return None
