"""資料で確認できた時間帯だけに配置する。併用の安全性を判定する機能ではない。"""
from .catalog import Catalog
from .media import media_of
from .schemas import Product, RoutineDiff, RoutinePlan, RoutineSlotPlan, RoutineStep

ORDER = {"cleanser": 0, "lotion": 1, "serum": 2, "emulsion": 3, "cream": 4, "sunscreen": 5, "other": 6}
SLOT_LABEL = {"morning": "朝", "night": "夜"}


def _slots(p: Product) -> tuple[list[str], str | None]:
    if p.usage.timing:
        return list(dict.fromkeys(p.usage.timing)), None
    return [], f"{p.name}は使用する時間帯が未確認です。製品の使い方を確認してから配置してください"


def _step(p: Product, is_new: bool = False) -> RoutineStep:
    return RoutineStep(product_id=p.product_id, brand=p.brand, name=p.name, category=p.category, is_new=is_new, media=media_of(p))


def _plan(products: list[Product], new_id: str | None):
    slots: dict[str, list[Product]] = {"morning": [], "night": []}
    notes, unplaced = [], []
    for p in {p.product_id: p for p in products}.values():
        where, note = _slots(p)
        if note:
            notes.append(note)
            unplaced.append(_step(p, p.product_id == new_id))
        for s in where:
            slots[s].append(p)
    for s in slots:
        slots[s].sort(key=lambda p: (ORDER.get(p.category, 9), p.product_id))
    plan = RoutineSlotPlan(**{s: [_step(p, p.product_id == new_id) for p in ps] for s, ps in slots.items()})
    return plan, notes, unplaced


def current_routine(cat: Catalog, owned_ids: list[str]) -> RoutinePlan:
    owned = [cat.product(pid) for pid in dict.fromkeys(owned_ids) if pid in cat.products]
    plan, notes, unplaced = _plan(owned, None)
    return RoutinePlan(product_id=None, plan=plan, diff=[], steps_morning=len(plan.morning),
                       steps_night=len(plan.night), status="unknown_usage" if unplaced else "ok",
                       notes=notes, unplaced=unplaced)


def simulate_routine(cat: Catalog, owned_ids: list[str], keep_ids: list[str], candidate_id: str) -> RoutinePlan:
    owned = [cat.product(pid) for pid in dict.fromkeys(owned_ids) if pid in cat.products and pid != candidate_id]
    cand = cat.product(candidate_id)
    plan, notes, unplaced = _plan([*owned, cand], candidate_id)
    where, _ = _slots(cand)
    diff = []
    if where:
        timing_text = "・".join(SLOT_LABEL[s] for s in where)
        diff.append(RoutineDiff(type="add", product_id=candidate_id, slot="both" if len(where) == 2 else where[0],
                                reason=f"資料に記載された時間帯（{timing_text}）に追加する案です"))
    else:
        diff.append(RoutineDiff(type="add", product_id=candidate_id, slot="unplaced",
                                reason="使う時間帯が未確認のため、確認待ちに追加します"))
    same_cat = [o for o in owned if o.category == cand.category]
    if same_cat:
        notes.append("同じカテゴリの手持ちがあります。追加する案を表示しています。置き換えや併用については製品の使い方を確認してください")
    for o in owned:
        slots, _ = _slots(o)
        reason = "残したい商品として指定されています" if o.product_id in keep_ids else "手持ちとして残します"
        if not slots:
            reason += "。使う時間帯は確認待ちです"
        diff.append(RoutineDiff(type="keep", product_id=o.product_id,
                                slot=("both" if len(slots) == 2 else slots[0]) if slots else "unplaced", reason=reason))
    if cand.usage.timing_strength == "recommended" and len(where) == 1:
        notes.append(f"{cand.name}は資料で{SLOT_LABEL[where[0]]}の使用が推奨されています（それ以外の時間帯を禁止する記載ではありません）")
    notes.append("並び順はカテゴリをもとにした目安です。各製品の用法・使用頻度を優先してください")
    return RoutinePlan(product_id=candidate_id, plan=plan, diff=diff, steps_morning=len(plan.morning),
                       steps_night=len(plan.night), status="unknown_usage" if unplaced else "ok",
                       notes=notes, unplaced=unplaced)
