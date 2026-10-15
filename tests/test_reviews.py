import json
import os
from pathlib import Path

import pytest

from app import reviews
from app.catalog import load
from tests.helpers import keyword_findings

GOLDEN = Path(__file__).parent / "fixtures" / "golden_reviews.json"


def test_duplicates_are_removed():
    cat = load()
    uniq_b, removed_b = reviews.unique_reviews(cat, "cand_b")
    assert removed_b == 1  # duplicate_of の指定
    assert "rv_cand_b_6" not in {r.review_id for r in uniq_b}
    uniq_a, removed_a = reviews.unique_reviews(cat, "cand_a")
    assert removed_a == 1  # 同じURLの再掲
    assert len(uniq_a) == 5


def test_aggregate_counts_come_from_unique_reviews():
    cat = load()
    findings = keyword_findings(cat.reviews)
    texture, scope = reviews.aggregate(cat, "cand_b", findings)
    stick = next(a for a in texture.aspects if a.aspect == "stickiness")
    assert scope.analyzed_count == 5
    assert stick.total == 5
    assert stick.positive + stick.negative + stick.mixed + stick.unknown == 5
    assert texture.stickiness_level == "good"
    assert scope.incentivized_count == 1
    assert scope.skin_type_stated_count == 3
    assert scope.duplicates_removed == 1
    assert set(scope.media) == {"amazon", "cosme"}


def test_few_reviews_are_insufficient_and_single_medium_is_flagged():
    cat = load()
    texture, scope = reviews.aggregate(cat, "cand_c", keyword_findings(cat.reviews))
    assert scope.insufficient and scope.single_medium
    assert texture.stickiness_level == "insufficient"
    assert any("目安" in n for n in scope.notes)


def test_failed_analysis_is_reported():
    cat = load()
    texture, scope = reviews.aggregate(cat, "cand_a", None)
    assert scope.analyzed_count == 0
    assert texture.stickiness_level == "insufficient"
    assert any("失敗" in n for n in scope.notes)


def test_sanitize_drops_unknown_or_foreign_review_ids():
    cat = load()
    dirty = {"rv_cand_a_1": {"stickiness": "negative", "bogus": "x"}, "rv_unknown": {"stickiness": "positive"},
             "rv_cand_b_1": {"stickiness": "nonsense"}}
    clean = reviews.sanitize_findings(cat, ["cand_a"], dirty)
    assert clean == {"rv_cand_a_1": {"stickiness": "negative"}}


@pytest.mark.skipif(not os.environ.get("SKINFIT_LIVE"), reason="Geminiを呼ぶ。SKINFIT_LIVE=1 のときだけ実行")
def test_live_extraction_matches_golden():
    import asyncio

    cat = load()
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    by_product: dict[str, list] = {}
    for g in golden["items"]:
        by_product.setdefault(g["product_id"], []).append(g)
    hits = total = 0
    for pid, items in by_product.items():
        uniq, _ = reviews.unique_reviews(cat, pid)
        found = asyncio.run(reviews.extract_findings(cat.product(pid).name, uniq))
        for g in items:
            total += 1
            hits += found.get(g["review_id"], {}).get(g["aspect"], "unknown") == g["polarity"]
    assert hits / total >= 0.8, f"{hits}/{total}"
