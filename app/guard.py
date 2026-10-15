"""利用回数の制限。公開URLから推薦を連打されて、検索とGeminiの費用が膨らむのを防ぐ。

- 1人あたり（IPアドレス）: 一定時間内の回数
- 同時実行: 推薦は同時に数件まで
- 1日の上限: 推薦の総回数

記録はインスタンスのメモリに持つ（Cloud Runのインスタンスごとに数える。max-instances 倍が実質の上限）。
"""

import datetime
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from .config import settings
from .logging_utils import log_event

_hits: dict[tuple[str, str], deque] = defaultdict(deque)
_daily: dict[str, int] = defaultdict(int)
_active_recommends = 0  # 実行中の推薦の数（1つのイベントループ内で数えるので排他は不要）

LIMITS = {  # (回数, 秒)
    "recommend": (settings.recommend_per_client, settings.rate_window_sec),
    "light": (settings.light_per_client, settings.rate_window_sec),
}


def client_key(request: Request) -> str:
    """利用者のIP。X-Forwarded-For の先頭は利用者が書き換えられるため、Googleが末尾に付け足す値を使う。

    すり抜けられても、同時実行と1日の上限は全体で効くので、費用の上限は保たれる。
    """
    fwd = [x.strip() for x in request.headers.get("x-forwarded-for", "").split(",") if x.strip()]
    return fwd[-1] if fwd else (request.client.host if request.client else "unknown")


def check_rate(request: Request, kind: str) -> None:
    limit, window = LIMITS[kind]
    key = (client_key(request), kind)
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        log_event("rate_limited", severity="WARNING", kind=kind, reason="per_client")
        raise HTTPException(status_code=429, detail=f"短い時間に何度も実行されたため、制限しています。{int(window // 60)}分ほど待ってから試してください")
    q.append(now)


def check_daily() -> None:
    today = datetime.date.today().isoformat()
    if _daily[today] >= settings.daily_recommend_limit:
        log_event("rate_limited", severity="WARNING", kind="recommend", reason="daily")
        raise HTTPException(status_code=429, detail="本日の推薦の上限に達しました。明日あらためて試してください")
    _daily[today] += 1


def try_acquire_recommend_slot() -> bool:
    """空きがあれば確保する。待たずに断る（推薦は数分かかるため、待たせると接続が切れやすい）。"""
    global _active_recommends
    if _active_recommends >= settings.max_concurrent_recommends:
        log_event("rate_limited", severity="WARNING", kind="recommend", reason="concurrency")
        return False
    _active_recommends += 1
    return True


def release_recommend_slot() -> None:
    global _active_recommends
    _active_recommends = max(0, _active_recommends - 1)


def reset_for_tests() -> None:
    global _active_recommends
    _hits.clear()
    _daily.clear()
    _active_recommends = 0
