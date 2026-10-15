from app import routine
from app.catalog import load


def test_current_routine_orders_by_category():
    cat = load()
    plan = routine.current_routine(cat, ["own_emulsion", "own_lotion"])
    assert [s.product_id for s in plan.plan.morning] == ["own_lotion", "own_emulsion"]
    assert plan.steps_morning == 2 and plan.steps_night == 2


def test_candidate_is_added_after_lotion_and_kept_items_are_explained():
    cat = load()
    plan = routine.simulate_routine(cat, ["own_lotion", "own_emulsion"], ["own_lotion"], "cand_a")
    assert [s.product_id for s in plan.plan.night] == ["own_lotion", "cand_a", "own_emulsion"]
    assert plan.plan.night[1].is_new
    add = [d for d in plan.diff if d.type == "add"]
    assert len(add) == 1 and add[0].product_id == "cand_a"
    keep = {d.product_id: d.reason for d in plan.diff if d.type == "keep"}
    assert "残したい" in keep["own_lotion"]


def test_recommended_night_only_is_not_extended_to_morning():
    cat = load()
    plan = routine.simulate_routine(cat, ["own_lotion"], [], "cand_c")
    assert "cand_c" not in [s.product_id for s in plan.plan.morning]
    assert "cand_c" in [s.product_id for s in plan.plan.night]
    assert any("禁止する記載ではありません" in n for n in plan.notes)
    assert plan.steps_morning == 1 and plan.steps_night == 2


def test_same_category_owned_item_is_replaced_in_the_plan():
    """探すアイテムと同じ種類で「残したい」でない手持ちは、配置から外し、差分に入れ替えとして出す。"""
    from app.catalog import live_catalog
    from app.schemas import Product, Usage
    base = load()
    new_lotion = Product(product_id="cand_l", role="candidate", brand="テスト", name="新しい化粧水", category="lotion",
                         usage=Usage(timing=["morning", "night"], timing_strength="not_stated"), checked_at="2026-10-15",
                         data_version="live")
    cat = live_catalog(base, [base.product("own_lotion"), base.product("own_emulsion")], [new_lotion], [], "live", None)
    plan = routine.simulate_routine(cat, ["own_lotion", "own_emulsion"], [], "cand_l")
    assert [s.product_id for s in plan.plan.morning] == ["cand_l", "own_emulsion"]
    remove = [d for d in plan.diff if d.type == "remove"]
    assert [d.product_id for d in remove] == ["own_lotion"] and remove[0].slot == "both"
    assert "残したい" in remove[0].reason
    # 「残したい」にした場合は、外さずに併用する案になる
    kept = routine.simulate_routine(cat, ["own_lotion", "own_emulsion"], ["own_lotion"], "cand_l")
    assert "own_lotion" in [s.product_id for s in kept.plan.morning]
    assert not [d for d in kept.diff if d.type == "remove"]
    assert any("併用する案" in n for n in kept.notes)
