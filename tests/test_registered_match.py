"""登録商品（人が公式ページで確かめたデータ）に一致したら、その場のGoogle検索を省く仕組みの試験。"""

import asyncio

import pytest

from app import catalog, product_image, research
from app.schemas import Claim, Product, ProductMedia, Source

TODAY = "2026-10-15"
OFFICIAL = "https://maker.example/lotion"


def _registered(**kw) -> Product:
    base = dict(product_id="reg_lotion", role="owned", brand="ちふれ", name="化粧水 とてもしっとりタイプ", category="lotion",
                name_aliases=["とてもしっとり 化粧水"], ingredients_full=["水", "グリセリン", "BG", "ヒアルロン酸Na", "PEG-32",
                                                                   "ベタイン", "フェノキシエタノール", "メチルパラベン"],
                ingredients_source_id="S1", price_jpy_tax_included=660, price_source_id="S1",
                claims=[Claim(claim_id="clm_reg_1", text="乾燥を防ぐ", type="marketing", source_id="S1")],
                sources=[Source(source_id="S1", url=OFFICIAL, title="ちふれ 公式", checked_at=TODAY)],
                checked_at=TODAY, data_version="2026-10-15.1")
    base.update(kw)
    return Product(**base)


@pytest.fixture
def registered(monkeypatch):
    p = _registered()
    monkeypatch.setitem(catalog.load().products, p.product_id, p)
    return p


def test_find_registered_matches_name_and_aliases(registered):
    cat = catalog.load()
    assert catalog.find_registered(cat, "ちふれ", "化粧水 とてもしっとりタイプ") is registered
    assert catalog.find_registered(cat, "ちふれ", "ちふれ 化粧水　とてもしっとりタイプ") is registered  # ブランドの重複・全角空白
    assert catalog.find_registered(cat, "ちふれ", "とてもしっとり 化粧水") is registered  # 別の書き方
    assert catalog.find_registered(cat, None, "ちふれ 化粧水 とてもしっとりタイプ") is registered  # ブランドの欄が無い
    assert catalog.find_registered(cat, "ちふれ", "化粧水 しっとりタイプ") is None  # 別のバリエーション
    assert catalog.find_registered(cat, "別ブランド", "化粧水 とてもしっとりタイプ") is None


def test_dummy_products_are_not_used_as_registered():
    cat = catalog.load()
    dummy = next(p for p in cat.products.values() if p.is_dummy)
    assert catalog.find_registered(cat, dummy.brand, dummy.name) is None


def _fake_search(monkeypatch, labels):
    async def grounded(prompt, label):
        labels.append(label)
        return research.GroundedResult(text="口コミ", annotated="口コミ", queries=["q"], entry_point_html="<div>s</div>",
                                       sources=[Source(source_id="S1", url="https://review.example/1", title="review.example", checked_at=TODAY)])

    async def structure(schema, g, instruction, concern_label=None):
        assert schema is research._OpinionsOut, "成分・価格の構造化は呼ばれない想定"
        return research._OpinionsOut(opinions=[research._OpinionOut(source=1, summary="べたつかない", aspects=[
            research._AspectOut(aspect="stickiness", polarity="positive")])])
    monkeypatch.setattr(research, "grounded", grounded)
    monkeypatch.setattr(research, "_structure", structure)


def test_registered_candidate_skips_facts_search_but_keeps_review_search(monkeypatch):
    reg = _registered(role="candidate", product_id="reg_serum", name="濃密 美容液", name_aliases=[], category="serum")
    labels: list[str] = []
    _fake_search(monkeypatch, labels)
    stub = {"brand": "ちふれ", "name": "濃密 美容液"}
    p, revs, finds, entry, steps = asyncio.run(research.research_candidate(stub, "cand_1", registered=reg))
    assert labels == ["candidate_reviews:cand_1"]  # 成分・価格の検索は省く
    assert p.product_id == "cand_1" and p.role == "candidate" and p.ingredients_full == reg.ingredients_full
    assert p.price_source_id == "cand_1_F_S1" and p.claims[0].source_id == "cand_1_F_S1"
    assert reg.claims[0].source_id == "S1" and reg.product_id == "reg_serum"  # 登録データそのものは書き換えない
    assert len(revs) == 1 and finds[revs[0].review_id] == {"stickiness": "positive"}
    assert steps[0].summary == f"登録済みのデータを使いました（確認日 {TODAY}）"
    assert [s.url for s in steps[0].sources] == [OFFICIAL]  # 口コミの出典は混ぜない
    assert entry == "<div>s</div>"


def test_registered_media_skips_photo_api(monkeypatch):
    reg = _registered(role="candidate", media=ProductMedia(src="https://maker.example/lotion.jpg", source_url=OFFICIAL, credit="ちふれ 公式"))

    async def must_not_call(brand, name):
        raise AssertionError("登録画像がある商品では写真APIを呼ばない")
    monkeypatch.setattr(product_image, "find", must_not_call)
    _fake_search(monkeypatch, [])
    p, *_ = asyncio.run(research.research_candidate({"brand": "ちふれ", "name": reg.name}, "cand_1", registered=reg))
    assert p.media.src == "https://maker.example/lotion.jpg" and p.media.provider == "registered"


def test_photo_is_looked_up_in_parallel_when_not_registered(monkeypatch):
    found = ProductMedia(src="https://item-shopping.c.yimg.jp/i/l/x", source_url="https://store.shopping.yahoo.co.jp/x.html",
                         credit="Yahoo!ショッピング", provider="yahoo")
    asked = []

    async def fake_find(brand, name):
        asked.append((brand, name))
        return found
    monkeypatch.setattr(product_image, "find", fake_find)
    reg = _registered()
    p, entry, step = asyncio.run(research.registered_owned({"brand": "ちふれ", "name": "とてもしっとり 化粧水"}, "own_1", reg))
    assert asked == [("ちふれ", "とてもしっとり 化粧水")]
    assert p.media == found and p.product_id == "own_1" and p.searched_as == "ちふれ とてもしっとり 化粧水"
    assert entry is None and step.status == "ok" and "登録済み" in step.summary


def test_photo_failure_does_not_stop_research(monkeypatch):
    async def broken(brand, name):
        raise RuntimeError("api down")
    monkeypatch.setattr(product_image, "find", broken)
    p, *_ = asyncio.run(research.registered_owned({"brand": "ちふれ", "name": "化粧水"}, "own_1", _registered()))
    assert p.media is None
