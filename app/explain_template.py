"""確定値と理由コードから組み立てる定型の説明文。照合に必ず通るように、禁止語・数値を含めない。"""

from .schemas import CandidateView, Explanation, Reason

CONCERN_SENTENCE = {
    "claim": "悩みに対応する効能表示を確認できました。表示の原文は、詳しい根拠から確認できます。",
    "ingredient": "悩みに関わる方向性の成分を配合しています。成分の一般的な知見が、この製品にそのまま当てはまるとは限りません。",
    "none": "悩みとの関係は確認できませんでした。",
}


def build(c: CandidateView) -> Explanation:
    concern = CONCERN_SENTENCE[c.concern_relevance.level]
    texture = ("使用感を判断できる口コミの情報は、まだ揃っていません。"
               if c.texture.stickiness_level == "insufficient" else f"使用感については、{c.texture.stickiness_label}。")
    reasons = [
        Reason(category="concern", text=concern,
               source_ids=[cl.source.source_id for cl in c.concern_relevance.claims if cl.source]
               + [e.source.source_id for e in c.concern_relevance.evidence]),
        Reason(category="texture", text=texture, source_ids=[ex.review_id for a in c.texture.aspects for ex in a.examples][:4]),
        Reason(category="owned", text=c.owned_relation.note, source_ids=[]),
        Reason(category="price", text="税込参考価格は確認日時点のものです（価格の欄を参照）。",
               source_ids=[c.price_source.source_id] if c.price_source else []),
    ]
    if c.usage.timing:
        when = "・".join({"morning": "朝", "night": "夜"}[t] for t in c.usage.timing)
        reasons.append(Reason(category="usage", text=f"資料に記載された時間帯（{when}）で手持ちに組み込めます。",
                              source_ids=[c.usage.source.source_id] if c.usage.source else []))
    tradeoffs = []
    if c.texture.stickiness_level in ("mixed", "bad"):
        tradeoffs.append("ベタつきを気にする場合は、口コミの評価が分かれる点に注意が必要です。")
    if c.concern_relevance.level == "ingredient":
        tradeoffs.append("悩みに対応する効能表示は確認できていません。")
    unverified = list(c.unknown)
    if c.review_scope.insufficient:
        unverified.append("口コミが少なく、使用感の傾向は判断しきれません。")
    return Explanation(
        summary=concern + texture,
        reasons=reasons, tradeoffs=tradeoffs, unverified=unverified,
    )
