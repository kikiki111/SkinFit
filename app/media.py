"""商品写真の解決。人が公式ページで確かめた登録画像を優先し、なければ公式API（Yahoo!・楽天）で照合した画像を使う。

モデルが書いたURLや、Google検索連携のリンク先から取った画像は使わない（検索連携の規約でリンク先の自動取得を禁じているため）。
"""
import json
import re
import unicodedata
from functools import lru_cache
from .config import settings


def _key(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or "")).casefold()


def strip_brand(brand: str, name: str) -> str:
    """製品名の先頭にブランド名が重なっていれば外す（「ちふれ ちふれ 濃厚 美容液」を防ぐ）。"""
    n = name.strip()
    while brand and n.startswith(brand):
        n = n[len(brand):].strip()
    return n or name


def product_key(brand: str | None, name: str) -> str:
    """ブランドと製品名の照合キー。表記の幅・空白・大文字小文字と、製品名に重なったブランド名をそろえる。"""
    return f"{_key(brand or '')}|{_key(strip_brand(brand or '', name))}"


@lru_cache(maxsize=1)
def _manifest():
    return json.loads((settings.web_dir / "assets/products/manifest.json").read_text())


def media_for(brand: str, name: str):
    for entry in _manifest():
        if _key(brand) == _key(entry["brand"]) and _key(name) == _key(entry["name"]):
            return {k: entry[k] for k in ("src", "source_url", "credit")}
    return None


def media_of(product):
    """manifest.json の登録画像を優先し、なければ製品が持つ写真（登録データの公式画像URL・公式APIの画像）を返す。"""
    registered = media_for(product.brand, product.name)
    if registered:
        return registered
    return product.media.model_dump() if product.media else None
