"""商品写真の解決。登録データの公式画像URLを優先し、なければ公式API（Yahoo!・楽天）で照合した画像を使う。

メーカーの画像ファイルはリポジトリに置かない（公式サイトの規約で複製・転載を禁じているため）。

モデルが書いたURLや、Google検索連携のリンク先から取った画像は使わない（検索連携の規約でリンク先の自動取得を禁じているため）。
"""


def media_of(product):
    """製品が持つ写真（登録データの公式画像URL・公式APIの画像）を返す。"""
    return product.media.model_dump() if product.media else None
