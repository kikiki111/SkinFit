"""Pythonで決まる部分の組み立て。/api/recommend（Workflow内）と /api/rerank の両方が同じ関数を使う。

Geminiから受け取るのは、調査の方向性（direction_id）、口コミの論点判定、説明文だけ。
順位・件数・価格・配置はここで計算する。
"""

from . import normalize, reviews, routine
from .catalog import Catalog, search_candidates, source_ref
from .media import media_of
from .ranking import RankInput, rank
from .schemas import (CandidateView, ClaimView, ConcernRelevance, DirectionView, EvidenceView, Explanation,
                      RecommendationResult, RecommendRequest, UsageView)

EFFICACY_TYPES = {"efficacy_tested", "quasi_drug_efficacy"}
CONCERN_LABEL = {"claim": "製品の表示が悩みに対応", "ingredient": "悩みに関わる方向性の成分を配合", "none": "悩みとの関連を確認できない"}


def valid_directions(cat: Catalog, direction_ids: list[str]) -> list[str]:
    return [d for d in dict.fromkeys(direction_ids) if d in cat.directions][:3]


def concern_relevance(cat: Catalog, product_id: str, concern: str, direction_ids: list[str]) -> ConcernRelevance:
    p = cat.product(product_id)
    # 「表示が悩みに対応」と扱うのは効能表示だけ。宣伝文句（marketing）は含めない
    claims = [ClaimView(claim_id=c.claim_id, text=c.text, type=c.type, source=cat.source(p, c.source_id))
              for c in p.claims if concern in c.concern_tags and c.type in EFFICACY_TYPES]
    hits = [h for h in normalize.ingredient_hits(cat, p) if h.direction_id in direction_ids]
    level = "claim" if claims else ("ingredient" if hits else "none")
    used_dirs = sorted({h.direction_id for h in hits})
    evidence = [EvidenceView(evidence_id=e.evidence_id, direction_id=e.direction_id, summary=e.summary, scope=e.scope,
                             limitations=e.limitations, source=source_ref(e.source)) for e in cat.evidence_for(used_dirs)]
    return ConcernRelevance(level=level, label=CONCERN_LABEL[level], claims=claims, ingredients=hits, evidence=evidence)


def research_ingredients(cat: Catalog, req: RecommendRequest, candidate_ids: list[str], direction_ids: list[str]) -> dict:
    """成分・製品表示の調査（Workflowの ingredient_branch）。"""
    return {
        pid: {
            "concern": concern_relevance(cat, pid, req.conditions.concern, direction_ids).model_dump(),
            "owned": normalize.owned_relation(cat, cat.product(pid), req.owned_product_ids).model_dump(),
        }
        for pid in candidate_ids
    }


def plan_routines(cat: Catalog, req: RecommendRequest, candidate_ids: list[str]) -> list[dict]:
    """朝夜の配置（Workflowの routine_branch）。先頭が今の棚。"""
    plans = [routine.current_routine(cat, req.owned_product_ids)]
    plans += [routine.simulate_routine(cat, req.owned_product_ids, req.keep_product_ids, pid) for pid in candidate_ids]
    return [p.model_dump() for p in plans]


def build(
    cat: Catalog,
    req: RecommendRequest,
    direction_ids: list[str],
    findings: dict[str, dict[str, str]] | None,
    explanations: dict[str, Explanation] | None = None,
    branch_status: dict[str, str] | None = None,
    ingredient_info: dict | None = None,
    routine_plans: list[dict] | None = None,
    failed_review_products: set[str] | None = None,
) -> RecommendationResult:
    direction_ids = valid_directions(cat, direction_ids)
    candidate_ids, excluded = search_candidates(cat, req.conditions, direction_ids)
    ingredient_info = ingredient_info or research_ingredients(cat, req, candidate_ids, direction_ids)
    routine_plans = routine_plans or plan_routines(cat, req, candidate_ids)
    failed_review_products = failed_review_products or set()
    base = dict(
        data_version=cat.data_version, uses_dummy_data=cat.uses_dummy,
        plan_directions=[DirectionView(direction_id=d, label=cat.directions[d].label, why=cat.directions[d].summary) for d in direction_ids],
        owned_analysis=normalize.owned_analysis(cat, req.owned_product_ids),
        branch_status=branch_status or {},
        analysis={"plan_directions": direction_ids, "review_findings": findings or {}, "explanations": explanations or {}},
    )
    if not candidate_ids:
        return RecommendationResult(
            status="NO_MATCH_IN_SCOPE",
            status_message="登録済みの製品の範囲では、必須条件と根拠を満たす候補がありません（市場全体に候補がないという意味ではありません）。",
            ranking=None, routines=[routine_plans[0]], missing=[f"{e['name']}：{e['reason']}" for e in excluded], **base,
        )
    views: dict[str, CandidateView] = {}
    inputs: list[RankInput] = []
    for pid in candidate_ids:
        p = cat.product(pid)
        f = None if pid in failed_review_products else {rid: v for rid, v in (findings or {}).items()
                                                        if rid in {r.review_id for r in cat.reviews_for(pid)}}
        texture, scope = reviews.aggregate(cat, pid, f)
        info = ingredient_info[pid]
        field_labels = {"cautions": "使用上の注意", "ingredients_full": "全成分", "usage": "使い方",
                        "usage_timing": "使用する時間帯", "price_jpy_tax_included": "税込価格", "claims": "効能表示"}
        unknown = [f"{field_labels.get(u.field, u.field)}：{u.reason}" for u in p.unknown]
        views[pid] = CandidateView(
            product_id=pid, brand=p.brand, name=p.name, category=p.category, is_dummy=p.is_dummy,
            media=media_of(p),
            regulatory_class=p.regulatory_class, price_jpy=p.price_jpy_tax_included, price_note=p.price_note,
            volume_text=f"{p.volume.value:g}{p.volume.unit}" if p.volume else None, price_checked_at=p.checked_at,
            price_source=cat.source(p, p.price_source_id), concern_relevance=info["concern"], texture=texture,
            review_scope=scope, owned_relation=info["owned"],
            usage=UsageView(timing=p.usage.timing, timing_strength=p.usage.timing_strength, order_note=p.usage.order_note,
                            source=cat.source(p, p.usage.source_id)),
            cautions=p.cautions, unknown=unknown, rank=0, rank_reason="",
        )
        inputs.append(RankInput(product_id=pid, name=p.name, concern_level=views[pid].concern_relevance.level,
                                stickiness_level=texture.stickiness_level, price=p.price_jpy_tax_included or 0,
                                analyzed_count=scope.analyzed_count))
    ranking, reasons = rank(inputs, list(req.priorities), req.conditions.require_texture_evidence)
    ranking.excluded = excluded + ranking.excluded
    if not ranking.order:
        return RecommendationResult(
            status="NO_MATCH_IN_SCOPE", status_message="本人が必須にした条件を満たす候補がありません。",
            ranking=ranking, routines=[routine_plans[0]], **base,
        )
    ordered = []
    for i, pid in enumerate(ranking.order, 1):
        v = views[pid]
        v.rank, v.rank_reason = i, reasons[pid]
        v.explanation = (explanations or {}).get(pid)
        ordered.append(v)
    keep = set(ranking.order)
    missing = [f"{e['name']}：{e['reason']}" for e in ranking.excluded]
    missing += [f"{v.name}：口コミの分析に失敗" for v in ordered if v.product_id in failed_review_products]
    return RecommendationResult(
        status="RECOMMENDATION_READY",
        status_message="確認できた候補・根拠・希望の範囲で、優先する1本を示します。本人への効果を保証するものではありません。",
        candidates=ordered, recommended_product_id=ranking.order[0], alternative_product_ids=ranking.order[1:3],
        ranking=ranking, routines=[routine_plans[0]] + [r for r in routine_plans[1:] if r["product_id"] in keep],
        missing=missing, **base,
    )
