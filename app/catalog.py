"""登録済みデータ（data/*.json）の読み込みと、候補の絞り込み。"""

import json
from dataclasses import dataclass
from functools import lru_cache

from .config import settings
from .schemas import AliasEntry, Conditions, Direction, Evidence, Product, Review, Source, SourceRef


@dataclass
class Catalog:
    data_version: str
    products: dict[str, Product]
    reviews: list[Review]
    directions: dict[str, Direction]
    evidence: list[Evidence]
    aliases: list[AliasEntry]
    uses_dummy: bool
    mode: str = "catalog"  # catalog: 登録済み / live: その場の検索 / catalog_fallback: 検索失敗時の代替
    researched_at: str | None = None
    min_reviews: int = 5  # これ未満は「口コミが少ない」と表示する
    review_unit: str = "posts"

    def product(self, product_id: str) -> Product:
        return self.products[product_id]

    def source(self, product: Product, source_id: str | None) -> SourceRef | None:
        for s in product.sources:
            if s.source_id == source_id:
                return SourceRef(source_id=s.source_id, url=s.url, title=s.title)
        return None

    def evidence_for(self, direction_ids: list[str]) -> list[Evidence]:
        return [e for e in self.evidence if e.direction_id in direction_ids]

    def owned_candidates(self) -> list[Product]:
        return [p for p in self.products.values() if p.role == "owned"]

    def reviews_for(self, product_id: str) -> list[Review]:
        return [r for r in self.reviews if r.product_id == product_id]


def _read(name: str) -> dict:
    return json.loads((settings.data_dir / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load() -> Catalog:
    products_raw = _read("products.json")
    reviews_raw = _read("reviews.json")
    evidence_raw = _read("evidence.json")
    aliases_raw = _read("ingredient_aliases.json")
    products = {p["product_id"]: Product.model_validate(p) for p in products_raw["products"]}
    reviews = [Review.model_validate(r) for r in reviews_raw["reviews"]]
    directions = {d["direction_id"]: Direction.model_validate(d) for d in evidence_raw["directions"]}
    evidence = [Evidence.model_validate(e) for e in evidence_raw["evidence"]]
    aliases = [AliasEntry.model_validate(a) for a in aliases_raw["entries"]]
    uses_dummy = (
        any(p.is_dummy for p in products.values())
        or any(r.is_dummy for r in reviews)
        or any(e.get("is_dummy") for e in evidence_raw["evidence"])
        or bool(aliases_raw.get("is_dummy"))
    )
    return Catalog(
        data_version=products_raw.get("data_version", "unknown"),
        products=products, reviews=reviews, directions=directions, evidence=evidence,
        aliases=aliases, uses_dummy=uses_dummy,
    )


def live_catalog(base: Catalog, owned: list[Product], candidates: list[Product], reviews: list[Review],
                 mode: str, researched_at: str | None) -> Catalog:
    """リクエストごとの製品データ。成分の知識（方向性・資料・別名）は登録済みのものを使う。

    live: 製品・口コミとも検索で得たもの。口コミは「検索で確認できた情報源」単位で数える
    catalog_fallback: 手持ちは検索結果、候補と口コミは登録済みのもの
    """
    products = {p.product_id: p for p in [*owned, *candidates]}
    live = mode == "live"
    return Catalog(
        data_version=f"live-{researched_at}" if live else base.data_version,
        products=products, reviews=reviews, directions=base.directions, evidence=base.evidence, aliases=base.aliases,
        uses_dummy=any(p.is_dummy for p in products.values()) or any(r.is_dummy for r in reviews),
        mode=mode, researched_at=researched_at, min_reviews=3 if live else base.min_reviews,
        review_unit="sources" if live else "posts",
    )


def catalog_from_bundle(bundle: dict) -> Catalog:
    """セッション状態や /api/rerank で受け取った bundle から製品データを組み立てる（型で検査する）。

    小じわ以外の悩みでは、その場で調べた方向性・資料を、登録済みのものの代わりに使う。
    """
    base = load()
    if bundle.get("directions") is not None:
        base = Catalog(
            data_version=base.data_version, products=base.products, reviews=base.reviews,
            directions={d["direction_id"]: Direction.model_validate(d) for d in bundle["directions"]},
            evidence=[Evidence.model_validate(e) for e in bundle.get("evidence") or []],
            aliases=base.aliases, uses_dummy=base.uses_dummy,
        )
    return live_catalog(
        base,
        [Product.model_validate(p) for p in bundle.get("owned") or []],
        [Product.model_validate(p) for p in bundle.get("candidates") or []],
        [Review.model_validate(r) for r in bundle.get("reviews") or []],
        bundle.get("mode") or "live", bundle.get("researched_at"),
    )


def source_ref(source: Source) -> SourceRef:
    return SourceRef(source_id=source.source_id, url=source.url, title=source.title)


def search_candidates(cat: Catalog, conditions: Conditions, direction_ids: list[str]) -> tuple[list[str], list[dict]]:
    """必須条件（カテゴリ・予算・除外成分・必要な製品情報・悩みとの関連）で候補を絞る。"""
    from .normalize import canonical, ingredient_hits

    avoid = {canonical(a, cat).casefold() for a in conditions.avoid_ingredients if a.strip()}
    picked: list[str] = []
    excluded: list[dict] = []
    for p in cat.products.values():
        if p.role != "candidate":
            continue
        reason = None
        if p.category != conditions.category:
            reason = "カテゴリが希望と異なる"
        elif p.price_jpy_tax_included is None:
            reason = "価格を確認できない"
        elif conditions.budget_jpy_max is not None and p.price_jpy_tax_included > conditions.budget_jpy_max:
            reason = f"予算（{conditions.budget_jpy_max:,}円）を超える"
        elif not p.ingredients_full:
            reason = "全成分を確認できない"
        elif avoid & {canonical(i, cat).casefold() for i in p.ingredients_full}:
            reason = "避けたい成分を含む"
        elif avoid and not p.ingredients_complete:
            reason = "全成分の一部が未確認のため、避けたい成分の有無を判断できない"
        else:
            has_claim = any(conditions.concern in c.concern_tags and c.type in ("efficacy_tested", "quasi_drug_efficacy") for c in p.claims)
            has_ingredient = any(h.direction_id in direction_ids for h in ingredient_hits(cat, p))
            if not (has_claim or has_ingredient):
                reason = "悩みに関わる表示・成分を確認できない"
        if reason:
            excluded.append({"product_id": p.product_id, "name": p.name, "reason": reason})
        else:
            picked.append(p.product_id)
    return picked, excluded
