"""商品写真の探索（Yahoo!ショッピング → 楽天市場）の試験。通信は httpx.MockTransport で差し替える。"""

import asyncio

import httpx
import pytest
from pydantic import ValidationError

from app import product_image
from app.config import settings
from app.schemas import ProductMedia

BRAND, NAME = "アクアレーベル", "トリートメントローション（オイルイン） しっとり"
YAHOO_IMG = "https://item-shopping.c.yimg.jp/i/l/shop_lotion-600"
RAKUTEN_IMG = "https://thumbnail.image.rakuten.co.jp/@0_mall/shop/cabinet/lotion.jpg?_ex=128x128"


@pytest.fixture
def keys():
    values = {"yahoo_client_id": "yahoo-id", "rakuten_app_id": "rakuten-app", "rakuten_access_key": "rakuten-key"}
    for k, v in values.items():
        object.__setattr__(settings, k, v)
    yield


def _yahoo_hit(name, img=YAHOO_IMG, brand=""):
    return {"name": name, "url": "https://store.shopping.yahoo.co.jp/shop/lotion.html", "brand": {"name": brand},
            "exImage": {"url": img, "width": 600, "height": 600}}


def _serve(monkeypatch, yahoo=None, rakuten=None, calls=None):
    """提供元ごとの応答（dict か ステータスコード）を返す偽の通信を差し込む。"""
    async def handler(request: httpx.Request):
        provider = "yahoo" if "yahooapis" in request.url.host else "rakuten"
        if calls is not None:
            calls.append((provider, request))
        body = yahoo if provider == "yahoo" else rakuten
        if body is None:
            raise AssertionError(f"{provider} は呼ばれない想定")
        if isinstance(body, int):
            return httpx.Response(body)
        return httpx.Response(200, json=body)
    monkeypatch.setattr(product_image, "_transport", httpx.MockTransport(handler))


def _find(brand=BRAND, name=NAME):
    return asyncio.run(product_image.find(brand, name))


def test_yahoo_hit_is_used_and_variant_mismatch_is_skipped(keys, monkeypatch):
    calls = []
    _serve(monkeypatch, yahoo={"hits": [_yahoo_hit("アクアレーベル トリートメントローション（オイルイン）さっぱり", "https://example.com/wrong.jpg"),
                                        _yahoo_hit("資生堂 アクアレーベル トリートメントローション（オイルイン）しっとり 170mL")]},
           calls=calls)
    media = _find()
    assert media.provider == "yahoo" and media.src == YAHOO_IMG
    assert media.credit == "Yahoo!ショッピング" and media.source_url.startswith("https://store.shopping.yahoo.co.jp/")
    assert [c[0] for c in calls] == ["yahoo"]  # 見つかれば楽天は呼ばない
    params = calls[0][1].url.params
    assert params["appid"] == "yahoo-id" and params["image_size"] == "600" and params["results"] == "10"
    assert params["query"] == f"{BRAND} {NAME}"


def test_falls_back_to_rakuten_when_yahoo_has_no_single_item(keys, monkeypatch):
    calls = []
    _serve(monkeypatch,
           yahoo={"hits": [_yahoo_hit("【3個セット】アクアレーベル トリートメントローション（オイルイン）しっとり")]},
           rakuten={"items": [{"itemName": "アクアレーベル トリートメントローション（オイルイン）しっとり 170mL",
                               "itemUrl": "https://item.rakuten.co.jp/shop/lotion/", "mediumImageUrls": [RAKUTEN_IMG]}]},
           calls=calls)
    media = _find()
    assert media.provider == "rakuten" and media.src == RAKUTEN_IMG and media.credit == "楽天市場"
    assert media.source_url == "https://item.rakuten.co.jp/shop/lotion/"  # 楽天の画像の枠には楽天へのリンクを置く
    rakuten = calls[1][1]
    assert rakuten.headers["accessKey"] == "rakuten-key"
    assert rakuten.url.params["applicationId"] == "rakuten-app" and rakuten.url.params["formatVersion"] == "2"


def test_rakuten_old_format_with_image_objects(keys, monkeypatch):
    _serve(monkeypatch, yahoo={"hits": []},
           rakuten={"Items": [{"Item": {"itemName": "アクアレーベル トリートメントローション（オイルイン）しっとり",
                                         "itemUrl": "https://item.rakuten.co.jp/shop/lotion/",
                                         "mediumImageUrls": [{"imageUrl": RAKUTEN_IMG}]}}]})
    assert _find().src == RAKUTEN_IMG


def test_no_photo_when_nothing_matches(keys, monkeypatch):
    _serve(monkeypatch, yahoo={"hits": [_yahoo_hit("アクアレーベル トリートメントローション（オイルイン）しっとり 詰め替え用")]},
           rakuten={"items": [{"itemName": "別ブランド トリートメントローション（オイルイン）しっとり",
                               "itemUrl": "https://item.rakuten.co.jp/shop/x/", "mediumImageUrls": [RAKUTEN_IMG]}]})
    assert _find() is None


def test_rate_limit_or_failure_falls_through_without_stopping(keys, monkeypatch):
    _serve(monkeypatch, yahoo=429,
           rakuten={"items": [{"itemName": "アクアレーベル トリートメントローション（オイルイン）しっとり",
                               "itemUrl": "https://item.rakuten.co.jp/shop/lotion/", "mediumImageUrls": [RAKUTEN_IMG]}]})
    assert _find().provider == "rakuten"
    _serve(monkeypatch, yahoo=500, rakuten=503)
    assert _find() is None


def test_no_keys_means_no_request(monkeypatch):
    _serve(monkeypatch)  # 呼ばれたら AssertionError
    assert _find() is None


def test_slow_lookup_times_out(keys, monkeypatch):
    async def slow(request):
        await asyncio.sleep(5)
        return httpx.Response(200, json={"hits": []})
    monkeypatch.setattr(product_image, "_transport", httpx.MockTransport(slow))
    object.__setattr__(settings, "image_lookup_timeout_sec", 0.05)
    try:
        assert _find() is None
    finally:
        object.__setattr__(settings, "image_lookup_timeout_sec", 8.0)


def test_throttle_spaces_calls_one_second_apart(monkeypatch):
    clock = {"now": 100.0}
    slept = []

    async def fake_sleep(sec):
        slept.append(round(sec, 3))
        clock["now"] += sec
    monkeypatch.setattr(product_image.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(product_image.asyncio, "sleep", fake_sleep)
    t = product_image._Throttle(1.0)

    async def go():
        await t.wait()
        clock["now"] += 0.25
        await t.wait()
        await t.wait()
    asyncio.run(go())
    assert slept == [0.75, 1.0]


@pytest.mark.parametrize("title, listed_brand, ok", [
    ("資生堂 アクアレーベル トリートメントローション（オイルイン）しっとり 170mL", "", True),
    ("アクアレーベル トリートメントローション（オイルイン）とてもしっとり", "", True),  # 語はすべて含む。近い品は残りうる（README に記載）
    ("アクアレーベル トリートメントローション（オイルイン）さっぱり", "", False),
    ("トリートメントローション（オイルイン）しっとり", "", False),  # ブランドを確かめられない
    ("トリートメントローション（オイルイン）しっとり", "アクアレーベル", True),
    ("アクアレーベル トリートメントローション（オイルイン）しっとり ×2本", "", False),
    ("アクアレーベル トリートメントローション（オイルイン）しっとり お試しサイズ", "", False),
])
def test_matches(title, listed_brand, ok):
    assert product_image.matches(BRAND, NAME, title, listed_brand) is ok


def test_refill_product_can_match_refill_listing():
    assert product_image.matches("ちふれ", "濃厚 美容液 詰替用", "ちふれ 濃厚 美容液 詰替用 30mL")
    assert not product_image.matches("ちふれ", "濃厚 美容液", "ちふれ 濃厚 美容液 詰替用 30mL")


def test_product_media_accepts_only_safe_urls():
    assert ProductMedia(src="/assets/products/chifure-rich.png", source_url="https://example.com", credit="c").provider == "registered"
    assert ProductMedia(src=YAHOO_IMG, source_url="https://example.com", credit="c", provider="yahoo").src == YAHOO_IMG
    for src in ("javascript:alert(1)", "http://example.com/a.jpg", "/assets/products/../../etc.png", "data:image/png;base64,AA"):
        with pytest.raises(ValidationError):
            ProductMedia(src=src, source_url="https://example.com", credit="c")
    with pytest.raises(ValidationError):
        ProductMedia(src=YAHOO_IMG, source_url="javascript:alert(1)", credit="c")
