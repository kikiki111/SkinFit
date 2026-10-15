import json
from pathlib import Path

import pytest

from app import assemble
from app.catalog import load
from app.ranking import RankInput, rank
from app.schemas import DEFAULT_PRIORITIES, LIGHT_PRIORITIES
from tests.helpers import DIRECTIONS, demo_request, keyword_findings

ROOT = Path(__file__).resolve().parent.parent


def _inputs():
    return [
        RankInput("a", "A", "claim", "bad", 2970, 5),
        RankInput("b", "B", "ingredient", "good", 2200, 5),
        RankInput("c", "C", "ingredient", "insufficient", 2750, 3),
    ]


def test_switching_to_light_priority_changes_the_top():
    default, _ = rank(_inputs(), DEFAULT_PRIORITIES)
    light, _ = rank(_inputs(), LIGHT_PRIORITIES)
    assert default.order[0] == "a"
    assert light.order[0] == "b"
    assert default.comparisons[0].deciding_aspect == "悩みとの関連"
    assert light.comparisons[0].deciding_aspect == "ベタつきの少なさ"


def test_required_texture_evidence_excludes_insufficient():
    r, _ = rank(_inputs(), DEFAULT_PRIORITIES, require_texture_evidence=True)
    assert "c" not in r.order
    assert r.excluded[0]["product_id"] == "c"


def test_tie_breaks_by_analyzed_count():
    xs = [RankInput("x", "X", "ingredient", "good", 2000, 3), RankInput("y", "Y", "ingredient", "good", 2000, 8)]
    r, reasons = rank(xs, DEFAULT_PRIORITIES)
    assert r.order == ["y", "x"]
    assert "差がなく" in reasons["x"]


def test_flip_on_fixture_catalog_end_to_end():
    cat = load()
    findings = keyword_findings(cat.reviews)
    a = assemble.build(cat, demo_request(), DIRECTIONS, findings)
    b = assemble.build(cat, demo_request(priorities=LIGHT_PRIORITIES), DIRECTIONS, findings)
    assert a.recommended_product_id != b.recommended_product_id


def test_marketing_claims_do_not_count_as_concern_claims():
    from app.schemas import Claim

    cat = load()
    p = cat.product("cand_b")
    p.claims.append(Claim(claim_id="clm_mkt", text="エイジングケア美容液", type="marketing", concern_tags=["fine_lines"], source_id=p.sources[0].source_id))
    rel = assemble.concern_relevance(cat, "cand_b", "fine_lines", DIRECTIONS)
    assert rel.level == "ingredient"
    assert rel.claims == []


def test_ingredient_matching_handles_prefixes_and_variants():
    """医薬部外品の前置きや別の表記でも、方向性の成分として拾う。"""
    from app import normalize
    from app.schemas import Product

    cat = load()
    p = Product(product_id="x", role="owned", brand="b", name="n", category="lotion", checked_at="2026-10-15", data_version="t",
                ingredients_full=["有効成分：ナイアシンアミド", "その他の成分：精製水", "パルミチン酸レチノール", "＊ヒアルロン酸ナトリウム（2）", "BG"])
    found = {(h.name, h.direction_id) for h in normalize.ingredient_hits(cat, p)}
    assert ("有効成分：ナイアシンアミド", "niacinamide") in found
    assert ("パルミチン酸レチノール", "retinoid") in found
    assert ("＊ヒアルロン酸ナトリウム（2）", "hydration") in found
    assert not any(n == "BG" for n, _ in found)


def test_ingredient_matching_uses_this_runs_directions_and_quasi_drug_names():
    """その場で調べた方向性（毛穴など）にも、医薬部外品の表示名や小じわ用の別名の成分で照合できる。"""
    from app import normalize
    from app.catalog import Catalog
    from app.schemas import AliasEntry, Direction, Product

    base = load()
    aliases = list(base.aliases) + [
        AliasEntry(canonical="アスコルビルグルコシド", aliases=["L-アスコルビン酸 2-グルコシド"]),
        AliasEntry(canonical="パルミチン酸レチノール", aliases=[], direction_ids=["retinoid"]),
    ]
    cat = Catalog(data_version="t", products={}, reviews=[], evidence=[], aliases=aliases, uses_dummy=False,
                  directions={"live_1": Direction(direction_id="live_1", label="皮脂", concern="custom", summary="s",
                                                  member_ingredients=["アスコルビルグルコシド"]),
                              "live_2": Direction(direction_id="live_2", label="ハリ", concern="custom", summary="s",
                                                  member_ingredients=["パルミチン酸レチノール"])})
    p = Product(product_id="x", role="candidate", brand="b", name="n", category="lotion", checked_at="t", data_version="t",
                ingredients_full=["有効成分：L-アスコルビン酸 2-グルコシド（持続型ビタミンC誘導体）", "パルミチン酸レチノール"])
    found = {(h.name, h.direction_id) for h in normalize.ingredient_hits(cat, p)}
    assert any(n.startswith("有効成分：L-アスコルビン酸") and d == "live_1" for n, d in found)
    assert ("パルミチン酸レチノール", "live_2") in found
    assert not any(d == "retinoid" for _, d in found)  # この回に無い方向性は付けない
