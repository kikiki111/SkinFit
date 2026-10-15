"""照合用のキー。商品名・成分名・検索本文の照合は、表記のそろえ方をここにまとめる。

場所ごとに別のそろえ方をすると、全角と半角・空白・大文字小文字の違いで、同じ製品を別物と判定してしまうため。
"""
import re
import unicodedata


def text_key(text: str | None) -> str:
    """表記の幅（全角・半角）・空白・大文字小文字をそろえる。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or "")).casefold()


def strip_brand(brand: str, name: str) -> str:
    """製品名の先頭にブランド名が重なっていれば外す（「ちふれ ちふれ 濃厚 美容液」を防ぐ）。表示用。"""
    n = name.strip()
    while brand and n.startswith(brand):
        n = n[len(brand):].strip()
    return n or name


def product_key(brand: str | None, name: str) -> str:
    """同じ製品かを判定するキー。表記の幅・空白・大文字小文字と、製品名に重なったブランド名をそろえる。

    ブランドと製品名はつなげて比べる。片方にブランドの欄が無くても、製品名にブランドが入っていれば一致する。
    （例：ブランド「ＤＨＣ」・製品名「薬用Ｑローション」と、ブランド無し・製品名「DHC 薬用Qローション」）
    """
    b, n = text_key(brand), text_key(name)
    while b and n.startswith(b) and n != b:
        n = n[len(b):]
    return b + n
