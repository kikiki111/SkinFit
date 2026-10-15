"""ダミーデータから tests/fixtures/api_examples.json を作る（画面担当との取り決め用）。

口コミの論点判定はGeminiの代わりにキーワードで作る。実際のAPIはGeminiが判定する。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import assemble, explain_template  # noqa: E402
from app.catalog import load  # noqa: E402
from app.schemas import (LIGHT_PRIORITIES, CatalogResponse, Conditions, IntakeResponse, InventoryResponse,  # noqa: E402
                         ProductSummary, RecommendRequest, TexturePreference)

RULES = {
    "stickiness": (["ベタつかない", "さらっと", "ベタつきがなく", "軽い", "軽く"], ["ベタつく", "ベタつきが残る", "ベタつきが気に", "ベタつきは少し", "重め"]),
    "absorption": (["なじみが良い", "すぐなじむ", "なじませると"], []),
    "moisture": (["保湿感は高い", "しっとり", "もちが良い"], ["物足りない"]),
    "scent": (["香りは控えめ", "香りはほぼない"], []),
    "makeup": (["メイク前にも"], []),
    "irritation": ([], ["ピリつく"]),
    "spread": (["伸びがよく"], []),
}


def fake_findings(cat):
    out = {}
    for r in cat.reviews:
        f = {}
        for aspect, (pos, neg) in RULES.items():
            p = any(w in r.summary for w in pos)
            n = any(w in r.summary for w in neg)
            if p or n:
                f[aspect] = "mixed" if p and n else ("positive" if p else "negative")
        out[r.review_id] = f
    return out


def main():
    cat = load()
    conditions = Conditions(budget_jpy_max=3000, texture_preferences=[TexturePreference(aspect="stickiness", preference="avoid")],
                            keep_note="この化粧水は残したい")
    req = RecommendRequest(conditions=conditions, owned_product_ids=["own_lotion", "own_emulsion"], keep_product_ids=["own_lotion"])
    findings = fake_findings(cat)
    dirs = ["hydration", "niacinamide", "retinoid"]
    res = assemble.build(cat, req, dirs, findings, branch_status={"ingredient": "OK", "review": "OK", "routine": "OK"})
    expl = {c.product_id: explain_template.build(c) for c in res.candidates}
    res = assemble.build(cat, req, dirs, findings, expl, branch_status={"ingredient": "OK", "review": "OK", "routine": "OK"})
    res.explanation_mode = "template"
    req2 = req.model_copy(update={"priorities": LIGHT_PRIORITIES})
    res2 = assemble.build(cat, req2, dirs, findings, expl, branch_status=res.branch_status)
    res2.explanation_mode = "template"
    examples = {
        "catalog": CatalogResponse(owned_candidates=[ProductSummary(product_id=p.product_id, brand=p.brand, name=p.name, category=p.category, role=p.role, is_dummy=p.is_dummy) for p in cat.owned_candidates()], data_version=cat.data_version).model_dump(),
        "intake": IntakeResponse(conditions=conditions, follow_up_questions=["乾燥も気になりますか？（乾燥による小じわかどうかで、検討する方向性が変わります）"]).model_dump(),
        "inventory": InventoryResponse(detections=[
            {"brand": "ダミー", "name_guess": "保湿化粧水", "category": "lotion", "visible_text": "ダミー 保湿化粧水", "matches": [{"product_id": "own_lotion", "brand": "ダミー", "name": "ダミー保湿化粧水", "score": 0.92}]},
            {"brand": None, "name_guess": "乳液", "category": "emulsion", "visible_text": "MILK", "matches": [{"product_id": "own_emulsion", "brand": "ダミー", "name": "ダミー乳液", "score": 0.61}]},
        ], note="写真から読み取れた範囲の候補です。製品名とバリエーションは本人が確定してください。").model_dump(),
        "recommend_progress": [
            {"type": "progress", "node": n, "label": l, "status": "done"} for n, l in [
                ("intake_check", "商品と条件を確認"), ("concern_planner", "悩みと手持ちから調査方針を作成"),
                ("candidate_search", "登録済みの製品から候補を抽出"), ("ingredient_branch", "成分・製品表示と手持ちを照合"),
                ("review_branch", "使用感の口コミを分析"), ("routine_branch", "朝夜の配置を計算"), ("join", "調査結果をそろえる"),
                ("rank", "優先順位で候補を比較"), ("explain", "推薦理由を作成"), ("verify", "出典・数値・表現を照合")]
        ],
        "recommend_result": res.model_dump(),
        "rerank_result": res2.model_dump(),
    }
    out = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "api_examples.json"
    out.write_text(json.dumps(examples, ensure_ascii=False, indent=2), encoding="utf-8")
    print("top default:", res.recommended_product_id, "| top light:", res2.recommended_product_id)


if __name__ == "__main__":
    main()
