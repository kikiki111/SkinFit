import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import catalog  # noqa: E402
from app.config import settings  # noqa: E402

FIXTURE_DATA = ROOT / "tests" / "fixtures" / "data"


@pytest.fixture(autouse=True)
def fixture_data(request):
    """テストは tests/fixtures/data のダミーデータで動かす（本番の data/ が実データに替わっても壊れない）。

    test_data_integrity.py だけは本番の data/ を検査する。
    """
    real = request.node.fspath.basename == "test_data_integrity.py"
    object.__setattr__(settings, "data_dir", (ROOT / "data") if real else FIXTURE_DATA)
    # テストでは本物のGoogle検索を呼ばない。その場で調べる方式は test_live_research.py でモックを使って試す
    object.__setattr__(settings, "research_mode", "catalog")
    catalog.load.cache_clear()
    yield
    object.__setattr__(settings, "data_dir", ROOT / "data")
    catalog.load.cache_clear()


def _discover_agent_stub(index):
    """探索Agent（ADK・google_search）の代わり。出典つきの答えを状態に置くだけで、本物の検索は呼ばない。"""
    def stub(ctx, node_input):
        ctx.state[f"discover_raw_{index + 1}"] = {
            "text": "テスト用の検索結果", "chunks": [{"index": 0, "url": "https://example.com/discover", "title": "example.com"}],
            "supports": [], "queries": ["テスト"], "entry_html": None}
        return "テスト用の検索結果"
    stub.__name__ = f"discover_agent_{index + 1}"
    return stub


@pytest.fixture(autouse=True)
def no_real_discover_agents(monkeypatch):
    from app.workflows import agents
    monkeypatch.setattr(agents, "discover_agent", _discover_agent_stub)
