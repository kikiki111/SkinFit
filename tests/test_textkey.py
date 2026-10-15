"""照合用のキー（app/textkey.py）と、それを使う「同じ製品か」の判定の試験。"""

from app.schemas import Conditions, Product
from app.textkey import product_key, text_key
from app.workflows.recommendation import _choose


def test_text_key_ignores_width_spaces_and_case():
    assert text_key("ＤＨＣ　薬用 Ｑ\nLotion") == text_key("dhc薬用qlotion")


def test_product_key_matches_the_same_product_written_differently():
    base = product_key("DHC", "薬用Qローション")
    assert product_key("ＤＨＣ", "薬用Ｑローション") == base  # 全角
    assert product_key("DHC", "DHC 薬用Qローション") == base  # 製品名にブランドが重なる
    assert product_key(None, "DHC 薬用Qローション") == base  # ブランドの欄が無い
    assert product_key("DHC", "薬用Qローション 詰替") != base
    assert product_key("別ブランド", "薬用Qローション") != base


def test_choose_drops_an_owned_product_written_in_full_width():
    owned = [Product(product_id="own_1", role="owned", brand="ＤＨＣ", name="薬用Ｑローション", category="lotion",
                     checked_at="2026-10-16", data_version="live")]
    stubs = [{"brand": "DHC", "name": "薬用Qローション"}, {"brand": "テスト", "name": "美容液"}]
    picked, notes = _choose(stubs, Conditions(), owned, 3)
    assert [s["name"] for s in picked] == ["美容液"]
    assert "外した：DHC 薬用Qローション（手持ちと同じ製品）" in notes
