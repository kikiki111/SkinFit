"""商品写真の解決。登録データの公式画像URLを優先し、なければ公式API（Yahoo!・楽天）で照合した画像を使う。

メーカーの画像ファイルはリポジトリに置かない（公式サイトの規約で複製・転載を禁じているため）。

モデルが書いたURLや、Google検索連携のリンク先から取った画像は使わない（検索連携の規約でリンク先の自動取得を禁じているため）。
"""
import re
import unicodedata


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


def media_of(product):
    """製品が持つ写真（登録データの公式画像URL・公式APIの画像）を返す。"""
    return product.media.model_dump() if product.media else None
