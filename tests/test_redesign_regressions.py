"""デザイン改修時に発見した、判断と状態の境界の回帰テスト。外部APIは呼ばない。"""
import asyncio
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import assemble, normalize, orchestrator, research, routine
from app.catalog import load, search_candidates
from app.config import settings
from app.main import app
from app.media import media_for
from app.ranking import RankInput, rank
from app.schemas import Conditions, OwnedItem, RecommendRequest, RerankRequest, Usage
from tests.helpers import DIRECTIONS, demo_request, keyword_findings


def test_avoid_ingredients_requires_complete_ingredients():
    cat = deepcopy(load())
    cat.products['cand_b'].ingredients_complete = False
    cond = Conditions(budget_jpy_max=3000, avoid_ingredients=['エタノール'])
    ids, excluded = search_candidates(cat, cond, DIRECTIONS)
    assert 'cand_b' not in ids
    assert any(e['product_id'] == 'cand_b' and '判断できない' in e['reason'] for e in excluded)
    ids, _ = search_candidates(cat, Conditions(budget_jpy_max=3000), DIRECTIONS)
    assert 'cand_b' in ids


def test_alcohol_alias_and_case_use_this_catalog():
    cat = deepcopy(load())
    from app.schemas import AliasEntry
    cat.aliases.append(AliasEntry(canonical='エタノール', aliases=['Alcohol']))
    cat.products['cand_b'].ingredients_full.append('Alcohol')
    ids, excluded = search_candidates(cat, Conditions(avoid_ingredients=['アルコール']), DIRECTIONS)
    assert 'cand_b' not in ids
    assert any(e['product_id'] == 'cand_b' and '含む' in e['reason'] for e in excluded)
    assert normalize.canonical('エタノール', cat) != normalize.canonical('フェノキシエタノール', cat)


def test_incomplete_owned_is_not_reported_as_new_direction():
    cat = deepcopy(load())
    cat.products['own_lotion'].ingredients_full = None
    cat.products['own_lotion'].ingredients_complete = False
    relation = normalize.owned_relation(cat, cat.product('cand_b'), ['own_lotion'])
    assert relation.new_directions == []
    assert relation.unconfirmed_directions
    assert '判断できません' in relation.note


def test_unknown_timing_is_unplaced_and_keep_is_preserved():
    cat = deepcopy(load())
    cat.products['own_lotion'].usage = Usage()
    cat.products['cand_a'].usage = Usage()
    plan = routine.simulate_routine(cat, ['own_lotion'], ['own_lotion'], 'cand_a')
    assert not plan.plan.morning and not plan.plan.night
    assert {s.product_id for s in plan.unplaced} == {'own_lotion', 'cand_a'}
    assert plan.status == 'unknown_usage'
    assert all(d.slot == 'unplaced' for d in plan.diff)
    assert any(d.type == 'keep' and '残したい' in d.reason for d in plan.diff)


def test_night_only_owned_diff_does_not_claim_both_and_duplicates_are_removed():
    cat = deepcopy(load())
    cat.products['own_lotion'].usage = Usage(timing=['night'], timing_strength='required')
    plan = routine.simulate_routine(cat, ['own_lotion', 'own_lotion'], [], 'cand_a')
    assert next(d for d in plan.diff if d.type == 'keep').slot == 'night'
    assert len([s for s in plan.plan.night if s.product_id == 'own_lotion']) == 1
    assert not any(s.product_id == 'own_lotion' for s in plan.plan.morning)


def test_exact_ties_do_not_invent_review_count_difference():
    inputs = [RankInput(k,k,'ingredient','good',2000,5) for k in ['a','b']]
    ranking, reasons = rank(inputs, ['concern','price'])
    assert ranking.comparisons[0].deciding_aspect == '同順'
    assert all('件数に差はありません' in r for r in reasons.values())


def test_fourth_candidate_is_not_discarded_before_ranking():
    cat = deepcopy(load())
    fourth = cat.product('cand_a').model_copy(deep=True, update={'product_id':'fourth','price_jpy_tax_included':1})
    cat.products['fourth'] = fourth
    result = assemble.build(cat, demo_request(priorities=['price','concern']), DIRECTIONS, {})
    assert result.recommended_product_id == 'fourth'


@pytest.mark.parametrize('price,text,expected', [(100,'税込1,100円',False),(1100,'税込1,100円',True),
    (1980,'税込1980円',True),(1980,'価格¥1,980',True),(100,'製品番号100',False),(0,'0円',False)])
def test_price_requires_whole_currency_amount(price,text,expected):
    assert research._price_in_text(price,text) is expected


@pytest.mark.parametrize('budget', [0,-1])
def test_invalid_budget_rejected(budget):
    with pytest.raises(ValidationError):
        Conditions(budget_jpy_max=budget)


def test_empty_name_and_empty_priority_rejected():
    with pytest.raises(ValidationError):
        OwnedItem(name='  ')
    with pytest.raises(ValidationError):
        RecommendRequest(conditions=Conditions(), priorities=[])
    with pytest.raises(ValidationError):
        RecommendRequest(conditions=Conditions(), owned_product_ids=[str(i) for i in range(8)], owned_items=[OwnedItem(name='N')])


def test_rerank_does_not_reuse_old_explanation():
    cat = load()
    req = demo_request()
    result = assemble.build(cat,req,DIRECTIONS,keyword_findings(cat.reviews))
    from app.schemas import Explanation
    result.analysis.explanations={c.product_id:Explanation(summary='前の順位での説明') for c in result.candidates}
    reranked = orchestrator.run_rerank(RerankRequest(**req.model_dump(),analysis=result.analysis))
    assert reranked.explanation_mode == 'template'
    assert all(c.explanation.summary != '前の順位での説明' for c in reranked.candidates)


def test_request_deadline_covers_final_explanation(monkeypatch):
    from app.schemas import ProgressEvent
    closed = []
    async def slow_final(_req):
        try:
            yield ProgressEvent(node='explain',label='説明',status='running')
            await asyncio.sleep(10)
        finally:
            closed.append(True)
    monkeypatch.setattr(orchestrator, '_run_recommend', slow_final)
    old = settings.request_timeout_sec
    object.__setattr__(settings, 'request_timeout_sec', .02)
    try:
        async def collect():
            return [ev async for ev in orchestrator.run_recommend(demo_request())]
        events = asyncio.run(collect())
    finally:
        object.__setattr__(settings, 'request_timeout_sec', old)
    assert events[-1].result.status == 'HALTED'
    assert closed == [True]


def test_invalid_rerank_bundle_returns_validation_error():
    body=demo_request().model_dump(); body['analysis']={'bundle':{'owned':[{'name':'invalid'}]}}
    response=TestClient(app).post('/api/rerank',json=body)
    assert response.status_code == 422


def test_media_requires_exact_product_match():
    assert media_for('ちふれ','濃厚 美容液')['src'].endswith('.png')
    assert media_for('ちふれ','濃厚 美容液 詰替用') is None
    assert media_for('別ブランド','濃厚 美容液') is None


def test_preview_is_explicit_and_does_not_fabricate_reviews():
    response=TestClient(app).get('/api/preview')
    assert response.status_code == 200
    result=response.json()
    assert result['is_preview'] is True
    assert all(c['review_scope']['analyzed_count']==0 for c in result['candidates'])
    assert all(c['texture']['stickiness_level']=='insufficient' for c in result['candidates'])
