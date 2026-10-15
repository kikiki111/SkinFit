"""InventoryWorkflow：洗面台の写真から商品候補を抽出し、カタログと照合する。本人が確定するまで成分は確定しない。

写真はこの解析にだけ使い、保存もログ出力もしない。見えない成分を写真から推測しない。
"""

import difflib
import unicodedata

from google.genai import types
from pydantic import BaseModel

from .. import gemini
from ..catalog import load
from ..schemas import Detection, DetectionMatch, InventoryResponse


class _Item(BaseModel):
    brand: str | None
    name_guess: str | None
    alternatives: list[str]  # 同じ容器について考えられる、ほかの製品名
    is_sample: bool  # 試供品・サンプルの小袋やミニサイズ
    category: str | None
    visible_text: str | None


class _PhotoOutput(BaseModel):
    items: list[_Item]


PHOTO_SYSTEM = """あなたは洗面台の写真から、スキンケア製品のボトルやパッケージを見つける担当です。
写っている容器1つにつき1件だけ返します。同じ容器について製品名の候補が複数考えられるとき（シリーズ違い・タイプ違いなど）は、
1件にまとめ、最も確からしいものを name_guess に、ほかの候補を alternatives に入れてください。別の容器として数えないでください。
各件について、ラベルから読み取れるブランド名（brand）、製品名の推定（name_guess）、カテゴリ（cleanser / lotion / serum / emulsion / cream / sunscreen / other）、
ラベルから実際に読み取れた文字（visible_text）を返します。試供品・サンプルの小袋やミニサイズの容器は is_sample を true にしてください。読み取れない項目は null にし、推測で埋めないでください。成分は推測しないでください。最大8件。"""


def _norm(s: str | None) -> str:
    return unicodedata.normalize("NFKC", s or "").lower().replace(" ", "").replace("　", "")


def match_catalog(item: _Item, limit: int = 3) -> list[DetectionMatch]:
    """ブランド名と製品名の文字の近さで、カタログ内の候補を並べる。確定は本人が行う。"""
    cat = load()
    query = _norm(f"{item.brand or ''}{item.name_guess or ''}{item.visible_text or ''}")
    scored = []
    for p in cat.products.values():
        target = _norm(f"{p.brand}{p.name}")
        score = difflib.SequenceMatcher(None, query, target).ratio()
        if item.brand and _norm(item.brand) and _norm(item.brand) in target:
            score += 0.2
        if item.category and item.category == p.category:
            score += 0.1
        scored.append((min(score, 1.0), p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [DetectionMatch(product_id=p.product_id, brand=p.brand, name=p.name, score=round(s, 2))
            for s, p in scored[:limit] if s >= 0.3]


async def extract(image: bytes, mime_type: str) -> InventoryResponse:
    contents = [types.Part.from_bytes(data=image, mime_type=mime_type), "この写真に写っているスキンケア製品を挙げてください。"]
    out = await gemini.generate_json("inventory", _PhotoOutput, contents, system=PHOTO_SYSTEM)
    detections = [Detection(**i.model_dump(), matches=match_catalog(i)) for i in out.items[:8]]
    note = "写真から読み取れた範囲の候補です。製品名とバリエーションは本人が確定してください。"
    if not detections:
        note = "写真から製品を見つけられませんでした。一覧から選んでください。"
    return InventoryResponse(detections=detections, note=note)
