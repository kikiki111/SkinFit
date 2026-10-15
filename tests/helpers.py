"""テスト用の共通部品。Geminiの代わりにキーワードで口コミを判定する。"""

from app.schemas import Conditions, RecommendRequest, TexturePreference

RULES = {
    "stickiness": (["ベタつかない", "さらっと", "ベタつきがなく", "軽い", "軽く"], ["ベタつく", "ベタつきが残る", "ベタつきが気に", "ベタつきは少し", "重め"]),
    "moisture": (["保湿感は高い", "しっとり", "もちが良い"], ["物足りない"]),
    "irritation": ([], ["ピリつく"]),
}


def keyword_findings(reviews) -> dict:
    out = {}
    for r in reviews:
        f = {}
        for aspect, (pos, neg) in RULES.items():
            p = any(w in r.summary for w in pos)
            n = any(w in r.summary for w in neg)
            if p or n:
                f[aspect] = "mixed" if p and n else ("positive" if p else "negative")
        out[r.review_id] = f
    return out


def demo_request(**kw) -> RecommendRequest:
    conditions = Conditions(budget_jpy_max=kw.pop("budget", 3000),
                            texture_preferences=[TexturePreference(aspect="stickiness", preference="avoid")],
                            keep_note="この化粧水は残したい")
    return RecommendRequest(conditions=conditions, owned_product_ids=kw.pop("owned", ["own_lotion", "own_emulsion"]),
                            keep_product_ids=["own_lotion"], **kw)


DIRECTIONS = ["hydration", "niacinamide", "retinoid"]


def select_stub(ctx, node_input):
    """選定エージェントの代わり。候補を上から3件選ぶ（本物のGeminiを呼ばない）。"""
    cands = (node_input or {}).get("candidates", [])
    return {"selected": [{"candidate_id": c["candidate_id"], "why": "テスト"} for c in cands[:3]],
            "excluded": [{"candidate_id": c["candidate_id"], "why": "上限"} for c in cands[3:]]}


select_stub.__name__ = "select_agent"  # 本番の選定エージェントと同じノード名にする
