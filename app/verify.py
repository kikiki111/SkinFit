"""必須照合。出典・1位・説明文の表現・数値・用法を、Pythonの確定値と突き合わせる。

科学的な解釈の正しさすべてを証明するものではない。照合を通らない説明は完成した推薦として出さない。
"""

import re
from dataclasses import dataclass

from .catalog import Catalog
from .schemas import CandidateView, Explanation, RecommendationResult

# 否定文でも使わせない（指示文で明示する）。否定の文脈を推測する例外は作らない
FORBIDDEN = ["治る", "治す", "治療", "必ず", "絶対", "安全", "副作用", "消える", "効く", "効果がある", "完璧", "最適", "劇的", "保証"]
NUMBER_PATTERNS = [re.compile(r"\d[\d,]*\s*円"), re.compile(r"\d+\s*件"), re.compile(r"\d+\s*[%％]")]


@dataclass
class Violation:
    product_id: str
    where: str
    message: str

    def text(self) -> str:
        return f"[{self.product_id}] {self.where}: {self.message}"


def allowed_source_ids(cat: Catalog, c: CandidateView) -> set[str]:
    p = cat.product(c.product_id)
    ids = {s.source_id for s in p.sources}
    ids |= {e.source.source_id for e in c.concern_relevance.evidence}
    ids |= {r.review_id for r in cat.reviews_for(c.product_id)}
    return ids


def check_explanation(cat: Catalog, c: CandidateView, e: Explanation | None) -> list[Violation]:
    if e is None:
        return [Violation(c.product_id, "explanation", "説明がありません")]
    out: list[Violation] = []
    texts = [("summary", e.summary)] + [(f"reasons[{i}]", r.text) for i, r in enumerate(e.reasons)]
    texts += [(f"tradeoffs[{i}]", t) for i, t in enumerate(e.tradeoffs)] + [(f"unverified[{i}]", t) for i, t in enumerate(e.unverified)]
    for where, t in texts:
        for w in FORBIDDEN:
            if w in t:
                out.append(Violation(c.product_id, where, f"禁止語「{w}」が含まれています（否定文でも使えません）"))
        for pat in NUMBER_PATTERNS:
            if pat.search(t):
                out.append(Violation(c.product_id, where, "価格・件数・割合の数値は説明文に書けません（画面がデータの値を表示します）"))
    allowed = allowed_source_ids(cat, c)
    for i, r in enumerate(e.reasons):
        for sid in r.source_ids:
            if sid not in allowed:
                out.append(Violation(c.product_id, f"reasons[{i}].source_ids", f"出典ID {sid} はこの製品の資料にありません"))
    return out


def check_result(cat: Catalog, result: RecommendationResult) -> list[Violation]:
    out: list[Violation] = []
    if result.status != "RECOMMENDATION_READY":
        return out
    if not result.ranking or not result.ranking.order or result.recommended_product_id != result.ranking.order[0]:
        out.append(Violation(result.recommended_product_id or "-", "recommended_product_id", "推奨1本が順位の1位と一致しません"))
    for c in result.candidates:
        p = cat.product(c.product_id)
        if c.price_jpy != p.price_jpy_tax_included:
            out.append(Violation(c.product_id, "price_jpy", "価格がデータと一致しません"))
        for cl in c.concern_relevance.claims:
            if cl.text not in {x.text for x in p.claims}:
                out.append(Violation(c.product_id, "claims", "効能表示がデータの原文と一致しません"))
        out.extend(check_explanation(cat, c, c.explanation))
    for plan in result.routines:
        if not plan.product_id:
            continue
        p = cat.product(plan.product_id)
        if p.usage.timing_strength == "required" and p.usage.timing:
            placed = {s for s, steps in (("morning", plan.plan.morning), ("night", plan.plan.night))
                      if any(st.product_id == p.product_id for st in steps)}
            if not placed <= set(p.usage.timing):
                out.append(Violation(p.product_id, "routine", "資料で指定された時間帯以外に置いています"))
    return out
