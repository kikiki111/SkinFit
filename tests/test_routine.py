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
