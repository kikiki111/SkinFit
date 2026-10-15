"""利用回数の制限。公開URLでの費用の暴走を防ぐ。"""

import pytest
from fastapi.testclient import TestClient

from app import guard, main, orchestrator
from app.config import settings
from app.schemas import ResultEvent, RecommendationResult


@pytest.fixture(autouse=True)
def fresh():
    guard.reset_for_tests()
    yield
    guard.reset_for_tests()


async def _fake_run(req):
    yield ResultEvent(result=RecommendationResult(status="HALTED", status_message="t", data_version="t"))


def _body():
    return {"conditions": {"concern_label": "小じわ"}, "owned_items": [{"name": "化粧水"}]}


def test_per_client_limit(monkeypatch):
    monkeypatch.setattr(orchestrator, "run_recommend", _fake_run)
    c = TestClient(main.app)
    codes = [c.post("/api/recommend", json=_body()).status_code for _ in range(settings.recommend_per_client + 1)]
    assert codes[:-1] == [200] * settings.recommend_per_client
    assert codes[-1] == 429


def test_concurrency_limit_releases_slot(monkeypatch):
    monkeypatch.setattr(orchestrator, "run_recommend", _fake_run)
    for _ in range(settings.max_concurrent_recommends):
        assert guard.try_acquire_recommend_slot()
    r = TestClient(main.app).post("/api/recommend", json=_body())
    assert r.status_code == 429 and "混み合って" in r.json()["detail"]
    guard.release_recommend_slot()
    assert TestClient(main.app).post("/api/recommend", json=_body()).status_code == 200
    assert guard._active_recommends == settings.max_concurrent_recommends - 1  # 終わった推薦は枠を返す


def test_daily_limit(monkeypatch):
    monkeypatch.setattr(orchestrator, "run_recommend", _fake_run)
    object.__setattr__(settings, "daily_recommend_limit", 1)
    try:
        c = TestClient(main.app)
        assert c.post("/api/recommend", json=_body(), headers={"x-forwarded-for": "1.1.1.1"}).status_code == 200
        r = c.post("/api/recommend", json=_body(), headers={"x-forwarded-for": "2.2.2.2"})
        assert r.status_code == 429 and "本日" in r.json()["detail"]
    finally:
        object.__setattr__(settings, "daily_recommend_limit", 150)
