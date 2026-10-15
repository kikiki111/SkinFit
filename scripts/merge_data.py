"""data/drafts/ の下書きを検査して、本番の data/*.json へ取り込む。

使い方: uv run python scripts/merge_data.py
- 製品: drafts/candidates.json（候補）と drafts/owned.json（手持ち）
- 口コミ: drafts/reviews_*.json（各ファイルは口コミの配列）
- 成分資料: drafts/evidence.json、drafts/ingredient_aliases.json
下書きが無い種類は、今の data/ のまま残す。型に合わない下書きがあれば、取り込まずに止まる。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.schemas import AliasEntry, Direction, Evidence, Product, Review  # noqa: E402

DATA = ROOT / "data"
DRAFTS = DATA / "drafts"
VERSION = "2026-10-15.1"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(name: str, obj) -> None:
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    errors: list[str] = []
    products: list[dict] = []
    for name in ("candidates.json", "owned.json"):
        path = DRAFTS / name
        if path.exists():
            for p in _read(path):
                try:
                    products.append(Product.model_validate(p).model_dump(mode="json"))
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{name} {p.get('product_id')}: {e}")
    reviews: list[dict] = []
    for path in sorted(DRAFTS.glob("reviews_*.json")):
        for r in _read(path):
            try:
                reviews.append(Review.model_validate(r).model_dump(mode="json"))
            except Exception as e:  # noqa: BLE001
                errors.append(f"{path.name} {r.get('review_id')}: {e}")
    evidence = None
    if (DRAFTS / "evidence.json").exists():
        ev = _read(DRAFTS / "evidence.json")
        try:
            evidence = {
                "data_version": VERSION,
                "directions": [Direction.model_validate(d).model_dump(mode="json") for d in ev["directions"]],
                "evidence": [Evidence.model_validate(e).model_dump(mode="json") for e in ev["evidence"]],
            }
        except Exception as e:  # noqa: BLE001
            errors.append(f"evidence.json: {e}")
    aliases = None
    if (DRAFTS / "ingredient_aliases.json").exists():
        try:
            aliases = {"data_version": VERSION,
                       "entries": [AliasEntry.model_validate(a).model_dump(mode="json") for a in _read(DRAFTS / "ingredient_aliases.json")["entries"]]}
        except Exception as e:  # noqa: BLE001
            errors.append(f"ingredient_aliases.json: {e}")

    ids = [p["product_id"] for p in products]
    if len(ids) != len(set(ids)):
        errors.append("製品IDが重複しています")
    known = ids + [p["product_id"] for p in _read(DATA / "products.json")["products"]]
    for r in reviews:
        if r["product_id"] not in known:
            errors.append(f"口コミ {r['review_id']} の製品 {r['product_id']} が製品データにありません")
    if errors:
        print("取り込みを中止しました:\n- " + "\n- ".join(errors[:30]))
        return 1

    # 製品は役割ごとに入れ替える（手持ちの下書きがまだ無ければ、今の手持ちを残す）
    current = _read(DATA / "products.json")["products"]
    roles = {p["role"] for p in products}
    merged = [p for p in current if p["role"] not in roles] + products
    merged_ids = {p["product_id"] for p in merged}
    # 口コミは、残った製品のものだけを残し、下書きを足す
    draft_ids = {r["review_id"] for r in reviews}
    kept = [r for r in _read(DATA / "reviews.json")["reviews"] if r["product_id"] in merged_ids and r["review_id"] not in draft_ids]
    _write("products.json", {"data_version": VERSION, "products": merged})
    _write("reviews.json", {"data_version": VERSION, "collection": {"note": "data/SOURCES.md を参照"}, "reviews": kept + reviews})
    if evidence:
        _write("evidence.json", evidence)
    if aliases:
        _write("ingredient_aliases.json", aliases)
    print(f"取り込み: 製品{len(merged)}（下書き{len(products)}） 口コミ{len(kept) + len(reviews)} 資料{len(evidence['evidence']) if evidence else 0} 別名{len(aliases['entries']) if aliases else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
