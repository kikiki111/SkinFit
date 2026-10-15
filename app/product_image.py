"""商品写真を、Yahoo!ショッピングと楽天市場の公式APIで探す。

検索連携（Google検索）のリンク先は開かない。規約でリンク先の自動取得と、結果の保存を禁じているため。
ここで得た画像URLもサーバーには保存しない（楽天の規約は、不特定多数と共有できる場所への保存を禁じている）。
商品名の語とブランド名がすべて商品タイトルに含まれる単品だけを採り、別の商品の写真を出さないことを優先する。
"""

import asyncio
import datetime
import re
import time
import unicodedata

import httpx

from .config import settings
from .logging_utils import add_usage, log_event
from .media import _key, strip_brand
from .schemas import ProductMedia

YAHOO_URL = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"
RAKUTEN_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
HTTP_TIMEOUT_SEC = 3.0
HITS = 10

# 商品名に無いのにタイトルにあれば、セット品・詰替・お試しの出品とみなして採らない
NOT_SINGLE = re.compile(r"セット|まとめ買い|[×x]\s*[2-9]|(?:[2-9]|\d{2,})\s*(?:個|本|点)|詰替|詰め替え|つめかえ|レフィル|リフィル|refill|トライアル|お試し|サンプル")
SPLIT = re.compile(r"[\s()\[\]{}【】「」『』〈〉《》・/,、。:;+|~〜\-]+")

_transport: httpx.AsyncBaseTransport | None = None  # テストで通信を差し替える


class _Throttle:
    """提供元ごとに、呼び出しの間隔を空ける（Yahoo!は1秒に1回まで）。

    次に呼んでよい時刻を先に予約するので、同時に呼ばれても順番に並ぶ。
    """

    def __init__(self, interval: float):
        self.interval = interval
        self._next = 0.0

    async def wait(self) -> None:
        now = time.monotonic()
        slot = max(now, self._next)
        self._next = slot + self.interval
        if slot > now:
            await asyncio.sleep(slot - now)


_throttles = {"yahoo": _Throttle(1.0), "rakuten": _Throttle(1.0)}


def _tokens(name: str) -> list[str]:
    words = [w for w in SPLIT.split(unicodedata.normalize("NFKC", name).casefold()) if w]
    long = [w for w in words if len(w) >= 2]
    return long or words


def matches(brand: str, name: str, title: str, listed_brand: str = "") -> bool:
    """商品タイトルが、この商品の単品の出品と言えるか。"""
    t = _key(title)
    if not t:
        return False
    if not all(_key(w) in t for w in _tokens(strip_brand(brand, name))):
        return False
    if brand and _key(brand) not in t and _key(brand) not in _key(listed_brand):
        return False
    n = unicodedata.normalize("NFKC", name).casefold()
    return all(m.group(0) in n for m in NOT_SINGLE.finditer(unicodedata.normalize("NFKC", title).casefold()))


async def _get(provider: str, url: str, params: dict, headers: dict | None = None) -> dict:
    await _throttles[provider].wait()
    add_usage(image_queries=1)
    async with httpx.AsyncClient(transport=_transport, timeout=HTTP_TIMEOUT_SEC) as client:
        resp = await client.get(url, params=params, headers=headers)
    resp.raise_for_status()
    return resp.json()


async def _yahoo(brand: str, name: str, query: str) -> ProductMedia | None:
    data = await _get("yahoo", YAHOO_URL, {"appid": settings.yahoo_client_id, "query": query,
                                           "results": HITS, "image_size": 600})
    for hit in data.get("hits") or []:
        src = ((hit.get("exImage") or {}).get("url") or "")
        if src.startswith("https://") and hit.get("url") and matches(brand, name, hit.get("name") or "",
                                                                     (hit.get("brand") or {}).get("name") or ""):
            return ProductMedia(src=src, source_url=hit["url"], credit="Yahoo!ショッピング", provider="yahoo",
                                checked_at=datetime.date.today().isoformat())
    return None


def _rakuten_items(data: dict) -> list[dict]:
    items = data.get("items") or data.get("Items") or []
    return [(i.get("item") or i.get("Item") or i) if isinstance(i, dict) else {} for i in items]


def _first_image(urls) -> str:
    for u in urls or []:
        src = u.get("imageUrl") if isinstance(u, dict) else u
        if isinstance(src, str) and src.startswith("https://"):
            return src
    return ""


async def _rakuten(brand: str, name: str, query: str) -> ProductMedia | None:
    data = await _get("rakuten", RAKUTEN_URL,
                      {"applicationId": settings.rakuten_app_id, "keyword": query, "hits": HITS,
                       "imageFlag": 1, "formatVersion": 2},
                      headers={"accessKey": settings.rakuten_access_key})
    for item in _rakuten_items(data):
        src = _first_image(item.get("mediumImageUrls"))
        if src and item.get("itemUrl") and matches(brand, name, item.get("itemName") or ""):
            return ProductMedia(src=src, source_url=item["itemUrl"], credit="楽天市場", provider="rakuten",
                                checked_at=datetime.date.today().isoformat())
    return None


def _providers():
    out = []
    if settings.yahoo_client_id:
        out.append(("yahoo", _yahoo))
    if settings.rakuten_app_id and settings.rakuten_access_key:
        out.append(("rakuten", _rakuten))
    return out


async def _find(brand: str, name: str) -> ProductMedia | None:
    query = f"{brand} {strip_brand(brand, name)}".strip()
    for provider, search in _providers():
        t = time.time()
        try:
            media = await search(brand, name, query)
        except (httpx.HTTPError, ValueError) as e:  # 429・通信失敗・JSONでない応答は「写真なし」として次へ
            log_event("product_image", severity="WARNING", target=query, provider=provider, result="error",
                      error=type(e).__name__, ms=int((time.time() - t) * 1000))
            continue
        log_event("product_image", target=query, provider=provider, result="found" if media else "not_found",
                  ms=int((time.time() - t) * 1000))
        if media:
            return media
    return None


async def find(brand: str | None, name: str) -> ProductMedia | None:
    """商品写真を探す。見つからない・時間切れ・キー未設定なら None（推薦は止めない）。"""
    if not name or not _providers():
        return None
    try:
        return await asyncio.wait_for(_find(brand or "", name), settings.image_lookup_timeout_sec)
    except TimeoutError:
        log_event("product_image", severity="WARNING", target=f"{brand or ''} {name}".strip(), result="timeout")
        return None
