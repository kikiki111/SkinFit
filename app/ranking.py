"""推奨1本の決め方。優先順位の高い観点から順に比べる辞書式順序で、点数は作らない。"""

from dataclasses import dataclass

from .schemas import PRIORITY_LABELS, Comparison, Ranking

CONCERN_LEVEL = {"claim": 2, "ingredient": 1, "none": 0}
CONCERN_TEXT = {"claim": "製品の表示が悩みに対応", "ingredient": "方向性の成分を配合", "none": "関連を確認できない"}
STICKINESS_LEVEL = {"good": 3, "mixed": 2, "bad": 1, "insufficient": 0}
STICKINESS_TEXT = {"good": "否定的な口コミが少ない", "mixed": "評価が分かれる", "bad": "否定的な口コミが多い", "insufficient": "情報不足"}


@dataclass
class RankInput:
    product_id: str
    name: str
    concern_level: str  # claim / ingredient / none
    stickiness_level: str  # good / mixed / bad / insufficient
    price: int
    analyzed_count: int


def _value(c: RankInput, key: str) -> int:
    if key == "concern":
        return CONCERN_LEVEL[c.concern_level]
    if key == "stickiness":
        return STICKINESS_LEVEL[c.stickiness_level]
    if key == "price":
        return -c.price
    raise ValueError(key)


def _describe(c: RankInput, key: str) -> str:
    if key == "concern":
        return CONCERN_TEXT[c.concern_level]
    if key == "stickiness":
        return STICKINESS_TEXT[c.stickiness_level]
    return f"{c.price:,}円"


def _deciding(a: RankInput, b: RankInput, priorities: list[str]) -> tuple[str, str]:
    for key in priorities:
        if _value(a, key) != _value(b, key):
            label = PRIORITY_LABELS[key]
            return label, f"{label}：{a.name}は「{_describe(a, key)}」、{b.name}は「{_describe(b, key)}」"
    if a.analyzed_count != b.analyzed_count:
        return "情報量", "比べた観点に差がなく、分析できた情報の件数が多い方を上にしました"
    return "同順", "比べた観点と情報の件数に差はありません。表示順は商品IDで固定しています"


def rank(inputs: list[RankInput], priorities: list[str], require_texture_evidence: bool = False) -> tuple[Ranking, dict[str, str]]:
    excluded = []
    pool = []
    for c in inputs:
        if require_texture_evidence and c.stickiness_level == "insufficient":
            excluded.append({"product_id": c.product_id, "name": c.name, "reason": "使用感の根拠を確認できない（本人が必須にした条件）"})
        else:
            pool.append(c)
    ordered = sorted(
        pool, key=lambda c: (tuple(_value(c, k) for k in priorities), c.analyzed_count, c.product_id), reverse=True,
    )
    comparisons = []
    reasons: dict[str, str] = {}
    for i, c in enumerate(ordered):
        if i + 1 < len(ordered):
            aspect, detail = _deciding(c, ordered[i + 1], priorities)
            comparisons.append(Comparison(winner=c.product_id, loser=ordered[i + 1].product_id, deciding_aspect=aspect, detail=detail))
        if i == 0:
            reasons[c.product_id] = comparisons[0].detail if comparisons else "条件を満たした候補はこの1品です"
        else:
            reasons[c.product_id] = comparisons[i - 1].detail
    order_text = " → ".join(PRIORITY_LABELS[k] for k in priorities)
    if ordered:
        top = ordered[0]
        why = f"優先順位（{order_text}）の順に比べ、{top.name}を推奨します。"
        if comparisons:
            why += f"2位との差がついた観点は「{comparisons[0].deciding_aspect}」です。"
    else:
        why = "条件を満たす候補がありません。"
    return Ranking(priorities=priorities, order=[c.product_id for c in ordered], why_top=why,
                   comparisons=comparisons, excluded=excluded), reasons
