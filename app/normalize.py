"""成分名の正規化と、手持ち・候補の成分の照合。濃度や効果の強さは計算しない。"""

import re
import unicodedata

from .catalog import Catalog
from .schemas import (DirectionCoverage, IngredientHit, OwnedAnalysis, OwnedOverlap, OwnedProductView,
                      OwnedRelation, Product)


# 全成分表示の前置き・記号（医薬部外品の「有効成分：」、注記の「＊」など）
_PREFIX = re.compile(r"^(有効成分|その他の成分|その他成分|全成分|配合成分|成分)\s*[:：]?\s*")
_DECOR = re.compile(r"[＊*※●◎○☆★†‡]+")
_TRAIL_NOTE = re.compile(r"[（(][^（）()]*[）)]$")
_MIN_SUBSTRING = 3  # これより短い名前（BG等）は部分一致に使わない


def clean(name: str) -> str:
    """表示名から前置き・記号・末尾の注記を外す。"""
    s = _DECOR.sub("", unicodedata.normalize("NFKC", name or "")).strip()
    s = _PREFIX.sub("", s)
    s = _TRAIL_NOTE.sub("", s).strip()
    return s


def _key(name: str) -> str:
    return clean(name).replace(" ", "").replace("　", "").lower()


def _alias_index(cat: Catalog) -> dict[str, tuple[str, list[str]]]:
    index: dict[str, tuple[str, list[str]]] = {}
    for e in cat.aliases:
        for n in [e.canonical, *e.aliases, *([e.inci] if e.inci else [])]:
            index[_key(n)] = (e.canonical, e.direction_ids)
    return index


def _direction_terms(cat: Catalog) -> list[tuple[str, str, list[str]]]:
    """方向性に関わる名前（別名・方向性の代表成分）を、長い順に並べる。部分一致の照合に使う。"""
    terms: dict[str, tuple[str, set[str]]] = {}
    for e in cat.aliases:
        if not e.direction_ids:
            continue
        for n in [e.canonical, *e.aliases, *([e.inci] if e.inci else [])]:
            canon, dirs = terms.get(_key(n), (e.canonical, set()))
            terms[_key(n)] = (canon, dirs | set(e.direction_ids))
    for d in cat.directions.values():
        for m in d.member_ingredients:
            canon, dirs = terms.get(_key(m), (m, set()))
            terms[_key(m)] = (canon, dirs | {d.direction_id})
    return sorted(((k, c, sorted(ds)) for k, (c, ds) in terms.items() if len(k) >= _MIN_SUBSTRING),
                  key=lambda t: len(t[0]), reverse=True)


def canonical(name: str, cat: Catalog | None = None) -> str:
    from .catalog import load

    entry = _alias_index(cat or load()).get(_key(name))
    if _key(name) == "アルコール":
        return "エタノール"
    return entry[0] if entry else clean(name)


def _alias_groups(cat: Catalog) -> dict[str, set[str]]:
    """正規名 → 同じ成分の名前（別名・INCI）の照合用キーの集合。"""
    groups: dict[str, set[str]] = {}
    for e in cat.aliases:
        groups.setdefault(e.canonical, set()).update(_key(n) for n in [e.canonical, *e.aliases, *([e.inci] if e.inci else [])])
    return groups


def ingredient_hits(cat: Catalog, product: Product) -> list[IngredientHit]:
    """全成分表示のうち、この回の方向性（cat.directions）に関わる成分。表示名はそのまま残す。

    表示名を別名辞書で正規名にそろえ、同じ成分の全ての名前で、方向性の代表成分・別名と部分一致を調べる。
    （例：「L-アスコルビン酸 2-グルコシド」→ アスコルビルグルコシド、「パルミチン酸レチノール」→ レチノール）
    """
    valid = set(cat.directions)
    index = _alias_index(cat)
    groups = _alias_groups(cat)
    terms = [(k, c, [d for d in ds if d in valid]) for k, c, ds in _direction_terms(cat)]
    terms = [t for t in terms if t[2]]
    hits: list[IngredientHit] = []
    for name in product.ingredients_full or []:
        key = _key(name)
        entry = index.get(key)
        canon = entry[0] if entry else clean(name)
        names = {key, _key(canon)} | groups.get(canon, set())
        dirs = set(entry[1]) & valid if entry else set()
        for k, _c, ds in terms:
            if any(k in n for n in names):
                dirs |= set(ds)
        for d in sorted(dirs):
            hits.append(IngredientHit(name=name, canonical=canon, direction_id=d))
    return hits


def owned_analysis(cat: Catalog, owned_ids: list[str]) -> OwnedAnalysis:
    products = [cat.product(pid) for pid in owned_ids if pid in cat.products]
    views = []
    for p in products:
        views.append(OwnedProductView(
            product_id=p.product_id, brand=p.brand, name=p.name, category=p.category, is_dummy=p.is_dummy,
            searched_as=p.searched_as, ingredients_available=bool(p.ingredients_full),
            ingredients_complete=bool(p.ingredients_full) and p.ingredients_complete,
            ingredients_full=list(p.ingredients_full or []), ingredient_source=cat.source(p, p.ingredients_source_id),
            directions_found=ingredient_hits(cat, p),
            claims=[{"claim_id": c.claim_id, "text": c.text, "type": c.type, "source": cat.source(p, c.source_id)} for c in p.claims],
        ))
    # 手持ちの間で共通する成分（基剤も含め、表示上の事実として示す）
    seen: dict[str, list[str]] = {}
    for p in products:
        for name in set(canonical(i, cat) for i in (p.ingredients_full or [])):
            seen.setdefault(name, []).append(p.product_id)
    common = [OwnedOverlap(canonical=k, owned_product_ids=v) for k, v in seen.items() if len(v) >= 2]
    coverage = []
    # 全成分が無い、または一部しか確認できていない手持ちがあれば、「見当たらない」とは言い切らない
    missing_info = [p for p in products if not p.ingredients_full or not p.ingredients_complete]
    for d in cat.directions.values():
        found = [(v.product_id, h.name) for v in views for h in v.directions_found if h.direction_id == d.direction_id]
        if found:
            status, note = "found", "手持ちの全成分表示で、この方向性の成分を確認できます"
        elif missing_info:
            names = "・".join(p.name for p in missing_info)
            status, note = "unknown", f"全成分を確認しきれていない手持ち（{names}）があるため判断できません"
        else:
            status, note = "not_found", "手持ちの全成分表示には見当たりません（肌に必要という意味ではありません）"
        coverage.append(DirectionCoverage(
            direction_id=d.direction_id, label=d.label, status=status,
            product_ids=sorted({pid for pid, _ in found}), ingredients=sorted({n for _, n in found}), note=note,
        ))
    return OwnedAnalysis(products=views, common_ingredients=common, coverage=coverage)


def owned_relation(cat: Catalog, candidate: Product, owned_ids: list[str]) -> OwnedRelation:
    cand_hits = ingredient_hits(cat, candidate)
    cand_dirs = {h.direction_id for h in cand_hits}
    owned_dirs: set[str] = set()
    overlaps: dict[str, list[str]] = {}
    for pid in owned_ids:
        if pid not in cat.products:
            continue
        o = cat.product(pid)
        for h in ingredient_hits(cat, o):
            owned_dirs.add(h.direction_id)
        owned_names = {canonical(i, cat) for i in (o.ingredients_full or [])}
        for h in cand_hits:
            if h.canonical in owned_names:
                overlaps.setdefault(h.canonical, []).append(pid)
    shared = sorted(cand_dirs & owned_dirs)
    new = sorted(cand_dirs - owned_dirs)
    incomplete = any(not cat.product(pid).ingredients_full or not cat.product(pid).ingredients_complete
                     for pid in owned_ids if pid in cat.products)
    unconfirmed = new if incomplete else []
    if incomplete:
        new = []
    labels = {d.direction_id: d.label for d in cat.directions.values()}
    parts = []
    if new:
        parts.append("手持ちでは確認できない方向性（" + "・".join(labels.get(d, d) for d in new) + "）の成分を含みます")
    if shared:
        parts.append("手持ちと同じ方向性（" + "・".join(labels.get(d, d) for d in shared) + "）の成分も含みます。重なり自体は不要・危険という意味ではありません")
    if unconfirmed:
        parts.append("手持ちの全成分を確認しきれていないため、新しく加わる方向性かは判断できません")
    if not parts:
        parts.append("登録済みの方向性に関わる成分の重なりは確認できません")
    return OwnedRelation(
        overlaps=[OwnedOverlap(canonical=k, owned_product_ids=sorted(set(v))) for k, v in overlaps.items()],
        new_directions=new, shared_directions=shared, unconfirmed_directions=unconfirmed, note="。".join(parts) + "。",
    )
