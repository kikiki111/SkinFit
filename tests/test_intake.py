"""相談文の整理（/api/intake/parse）。Geminiはモックにする。悩みは本人の言葉のまま扱う。"""

from fastapi.testclient import TestClient

from app import main
from app.schemas import Conditions
from app.workflows import agents


class _Out:
    def __init__(self, conditions, questions):
        self.conditions, self.follow_up_questions = conditions, questions


def _post(monkeypatch, conditions, questions, text):
    async def fake(_text):
        return _Out(conditions, questions)
    monkeypatch.setattr(agents, "parse_intake", fake)
    return TestClient(main.app).post("/api/intake/parse", json={"text": text}).json()


def test_other_concern_is_kept_as_the_users_words(monkeypatch):
    r = _post(monkeypatch, Conditions(concern="", concern_label="毛穴の目立ち", category="lotion"), [], "毛穴が目立つ")
    assert r["conditions"]["concern_label"] == "毛穴の目立ち"
    assert r["conditions"]["concern"] == "custom"


def test_fine_lines_words_map_to_registered_concern(monkeypatch):
    r = _post(monkeypatch, Conditions(concern="", concern_label="目元の小ジワ"), [], "目元の小ジワが気になる")
    assert r["conditions"]["concern"] == "fine_lines"
    assert r["conditions"]["concern_label"] == "目元の小ジワ"


def test_missing_concern_asks_without_guessing(monkeypatch):
    r = _post(monkeypatch, Conditions(concern="", concern_label="", category="lotion"), ["どのような肌悩みですか？", "ご予算は？"], "新しい化粧水が欲しい")
    assert r["conditions"]["concern"] == "" and r["conditions"]["concern_label"] == ""
    assert r["follow_up_questions"][0].startswith("優先する悩みを1つ")
    assert all("悩み" not in q for q in r["follow_up_questions"][1:])
