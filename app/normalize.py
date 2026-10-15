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
    """全成分表示のうち、この回の方向性（cat.directions）に関わる成分。表示名はそのまま残す。"""
    return names_hits(cat, product.ingredients_full or [])


def names_hits(cat: Catalog, ingredient_names: list[str]) -> list[IngredientHit]:
    """成分名の一覧のうち、この回の方向性（cat.directions）に関わる成分。表示名はそのまま残す。

    表示名を別名辞書で正規名にそろえ、同じ成分の全ての名前で、方向性の代表成分・別名と部分一致を調べる。
    （例：「L-アスコルビン酸 2-グルコシド」→ アスコルビルグルコシド、「パルミチン酸レチノール」→ レチノール）
    """
    valid = set(cat.directions)
    index = _alias_index(cat)
    groups = _alias_groups(cat)
    terms = [(k, c, [d for d in ds if d in valid]) for k, c, ds in _direction_terms(cat)]
    terms = [t for t in terms if t[2]]
    hits: list[IngredientHit] = []
    for name in ingredient_names:
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


def _complete(p: Product) -> bool:
    return bool(p.ingredients_full) and p.ingredients_complete


def _names(cat: Catalog, p: Product) -> set[str]:
    """全成分と有効成分の名前を、照合用のキーにそろえる（有効成分の欄が取れなかった手持ちでも、全成分で拾うため）。"""
    return {_key(canonical(i, cat)) for i in [*(p.ingredients_full or []), *p.active_ingredients] if clean(i)}


def actives_of(cat: Catalog, p: Product) -> list[str]:
    return list(dict.fromkeys(canonical(a, cat) for a in p.active_ingredients if clean(a)))


def owned_analysis(cat: Catalog, owned_ids: list[str], replaced_ids: list[str] | tuple = ()) -> OwnedAnalysis:
    """手持ちの成分の確認。方向性の確認（coverage）は、入れ替える手持ちを除いたセットで計算する。"""
    products = [cat.product(pid) for pid in owned_ids if pid in cat.products]
    replaced = set(replaced_ids)
    views = []
    for p in products:
        views.append(OwnedProductView(
            product_id=p.product_id, brand=p.brand, name=p.name, category=p.category, is_dummy=p.is_dummy,
            searched_as=p.searched_as, ingredients_available=bool(p.ingredients_full),
            ingredients_complete=bool(p.ingredients_full) and p.ingredients_complete,
            ingredients_full=list(p.ingredients_full or []), ingredient_source=cat.source(p, p.ingredients_source_id),
            directions_found=ingredient_hits(cat, p),
            claims=[{"claim_id": c.claim_id, "text": c.text, "type": c.type, "source": cat.source(p, c.source_id)} for c in p.claims],
            replaced=p.product_id in replaced, active_ingredients=actives_of(cat, p),
            maker_texture_description=p.maker_texture_description,
        ))
    # 手持ちの間で共通する成分（基剤も含め、表示上の事実として示す）
    seen: dict[str, list[str]] = {}
    for p in products:
        for name in set(canonical(i, cat) for i in (p.ingredients_full or [])):
            seen.setdefault(name, []).append(p.product_id)
    common = [OwnedOverlap(canonical=k, owned_product_ids=v) for k, v in seen.items() if len(v) >= 2]
    coverage = []
    after = [v for v in views if not v.replaced]
    removed = [v for v in views if v.replaced]
    # 全成分が無い、または一部しか確認できていない手持ちがあれば、「見当たらない」とは言い切らない
    missing_info = [p for p in products if p.product_id not in replaced and not _complete(p)]
    where = "入れ替え後の手持ち" if removed else "手持ち"
    for d in cat.directions.values():
        found = [(v.product_id, h.name) for v in after for h in v.directions_found if h.direction_id == d.direction_id]
        only_in = [v for v in removed if any(h.direction_id == d.direction_id for h in v.directions_found)]
        if found:
            status, note = "found", f"{where}の全成分表示で、この方向性の成分を確認できます"
        elif missing_info:
            names = "・".join(p.name for p in missing_info)
            status, note = "unknown", f"全成分を確認しきれていない手持ち（{names}）があるため判断できません"
        else:
            status, note = "not_found", f"{where}の全成分表示には見当たりません（肌に必要という意味ではありません）"
        if only_in and not found:
            note += "。入れ替える" + "・".join(v.name for v in only_in) + "だけにある成分です"
        coverage.append(DirectionCoverage(
            direction_id=d.direction_id, label=d.label, status=status,
            product_ids=sorted({pid for pid, _ in found}), ingredients=sorted({n for _, n in found}), note=note,
            replaced_only=bool(only_in) and not found,
        ))
    return OwnedAnalysis(products=views, common_ingredients=common, coverage=coverage,
                         replaced_product_ids=[v.product_id for v in removed])


def owned_relation(cat: Catalog, candidate: Product, owned_ids: list[str], replaced_ids: list[str] | tuple = ()) -> OwnedRelation:
    """候補と、入れ替え後の手持ちとの関係。方向性・有効成分の重なりと、入れ替えで手放す有効成分。"""
    replaced = [cat.product(pid) for pid in dict.fromkeys(replaced_ids) if pid in cat.products]
    after = [cat.product(pid) for pid in owned_ids if pid in cat.products and pid not in set(replaced_ids)]
    cand_hits = ingredient_hits(cat, candidate)
    cand_dirs = {h.direction_id for h in cand_hits}
    owned_dirs: set[str] = set()
    overlaps: dict[str, list[str]] = {}
    for o in after:
        for h in ingredient_hits(cat, o):
            owned_dirs.add(h.direction_id)
        owned_names = {canonical(i, cat) for i in (o.ingredients_full or [])}
        for h in cand_hits:
            if h.canonical in owned_names:
                overlaps.setdefault(h.canonical, []).append(o.product_id)
    shared = sorted(cand_dirs & owned_dirs)
    new = sorted(cand_dirs - owned_dirs)
    incomplete = any(not _complete(o) for o in after)
    unconfirmed = new if incomplete else []
    if incomplete:
        new = []
    if not after:
        level = "unknown"  # 比べる手持ちが無い
    elif new:
        level = "adds"
    elif incomplete:
        level = "unknown"
    else:
        level = "overlap"
    # 有効成分：候補の有効成分が入れ替え後の手持ちにもあるか。入れ替える手持ちの有効成分が、セットから無くなるか
    cand_actives = actives_of(cat, candidate)
    active_overlaps: dict[str, list[str]] = {}
    for a in cand_actives:
        for o in after:
            if _key(a) in _names(cat, o):
                active_overlaps.setdefault(a, []).append(o.product_id)
    kept_names = set().union(_names(cat, candidate), *(_names(cat, o) for o in after))
    released: dict[str, list[str]] = {}
    actives_unconfirmed = False
    if any(r.active_ingredients for r in replaced):
        if all(_complete(x) for x in [candidate, *after]):
            for r in replaced:
                for a in actives_of(cat, r):
                    if _key(a) not in kept_names:
                        released.setdefault(a, []).append(r.product_id)
        else:
            actives_unconfirmed = True
    labels = {d.direction_id: d.label for d in cat.directions.values()}
    names = {p.product_id: p.name for p in [*after, *replaced]}
    parts = []
    if replaced:
        parts.append("今の" + "・".join(r.name for r in replaced) + "と入れ替える前提で、残りの手持ちと比べています")
    if new:
        parts.append("手持ちでは確認できない方向性（" + "・".join(labels.get(d, d) for d in new) + "）の成分を含みます")
    if shared:
        parts.append("手持ちと同じ方向性（" + "・".join(labels.get(d, d) for d in shared) + "）の成分も含みます。重なり自体は不要・危険という意味ではありません")
    if unconfirmed:
        parts.append("手持ちの全成分を確認しきれていないため、新しく加わる方向性かは判断できません")
    if not (new or shared or unconfirmed):
        parts.append("登録済みの方向性に関わる成分の重なりは確認できません")
    for a, pids in active_overlaps.items():
        parts.append(f"有効成分の{a}は、手持ちの" + "・".join(names[p] for p in pids) + "にも含まれます。重なり自体は不要・危険という意味ではありません")
    for r in replaced:
        lost = [a for a, pids in released.items() if r.product_id in pids]
        if lost:
            parts.append(f"入れ替える{r.name}の有効成分（" + "・".join(lost) + "）は、残りの手持ちとこの候補の全成分表示には見当たりません")
    if actives_unconfirmed:
        parts.append("全成分を確認しきれない製品があるため、入れ替えで手放す有効成分があるかは判断できません")
    return OwnedRelation(
        overlaps=[OwnedOverlap(canonical=k, owned_product_ids=sorted(set(v))) for k, v in overlaps.items()],
        new_directions=new, shared_directions=shared, unconfirmed_directions=unconfirmed,
        routine_level=level, replaced_product_ids=[r.product_id for r in replaced], active_ingredients=cand_actives,
        active_overlaps=[OwnedOverlap(canonical=k, owned_product_ids=sorted(set(v))) for k, v in active_overlaps.items()],
        released_actives=[OwnedOverlap(canonical=k, owned_product_ids=sorted(set(v))) for k, v in released.items()],
        actives_unconfirmed=actives_unconfirmed,
        replaced_textures={r.name: r.maker_texture_description for r in replaced}, note="。".join(parts) + "。",
    )
