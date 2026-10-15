"""手持ちを「入れ替え後のセット」として扱う照合の試験。入れ替えの判定・方向性・有効成分・使用感・別の種類のアイテムの案。"""

from app import normalize, routine
from app.catalog import live_catalog, load
from app.schemas import Conditions, Product, RecommendRequest, Usage
from app.workflows.recommendation import other_step_plan

TODAY = "2026-10-15"


def _p(pid, role, category, ings, actives=(), complete=True, texture=None, name=None):
    return Product(product_id=pid, role=role, brand="テスト", name=name or pid, category=category, ingredients_full=list(ings),
                   ingredients_complete=complete, active_ingredients=list(actives), maker_texture_description=texture,
                   usage=Usage(timing=["morning", "night"], timing_strength="not_stated"),
                   checked_at=TODAY, data_version="live")


LOTION = _p("own_l", "owned", "lotion", ["水", "グリセリン", "ナイアシンアミド", "グリチルリチン酸2K"],
            actives=["グリチルリチン酸2K"], texture="美容液のようなさっぱりタイプ", name="化粧水A")
EMULSION = _p("own_e", "owned", "emulsion", ["水", "スクワラン", "セラミドNP", "トラネキサム酸＊"], name="乳液C")
NEW_LOTION = _p("cand_l", "candidate", "lotion", ["トラネキサム酸", "水", "グリセリン", "ナイアシンアミド"],
                actives=["トラネキサム酸"], texture="さらっとなじんでべたつかない")


def _cat(*owned, cands=(NEW_LOTION,)):
    return live_catalog(load(), list(owned), list(cands), [], "live", TODAY)


def _req(category="lotion", owned=("own_l", "own_e"), keep=()):
    return RecommendRequest(conditions=Conditions(category=category), owned_product_ids=list(owned), keep_product_ids=list(keep))


def test_same_category_is_replaced_unless_kept():
    cat = load()
    assert routine.replaced_ids(cat, ["own_lotion", "own_emulsion"], [], "lotion") == ["own_lotion"]
    assert routine.replaced_ids(cat, ["own_lotion", "own_emulsion"], ["own_lotion"], "lotion") == []
    assert routine.replaced_ids(cat, ["own_lotion", "own_emulsion"], [], "serum") == []
    other = _p("own_x", "owned", "other", ["水"])
    assert routine.replaced_ids(_cat(other), ["own_x"], [], "other") == []  # 種類が分からない手持ちは入れ替えない


def test_coverage_is_computed_without_the_replaced_item():
    cat = _cat(LOTION, EMULSION)
    analysis = normalize.owned_analysis(cat, ["own_l", "own_e"], ["own_l"])
    cov = {c.direction_id: c for c in analysis.coverage}
    assert cov["niacinamide"].status == "not_found" and cov["niacinamide"].replaced_only
    assert "入れ替える化粧水Aだけにある成分" in cov["niacinamide"].note
    assert cov["hydration"].status == "found" and not cov["hydration"].replaced_only  # 乳液のセラミドNPで確認できる
    assert {p.product_id: p.replaced for p in analysis.products} == {"own_l": True, "own_e": False}
    assert analysis.replaced_product_ids == ["own_l"]


def test_replaced_item_does_not_count_as_owned_direction():
    cat = _cat(LOTION, EMULSION)
    with_replace = normalize.owned_relation(cat, NEW_LOTION, ["own_l", "own_e"], ["own_l"])
    assert with_replace.routine_level == "adds" and "niacinamide" in with_replace.new_directions
    assert with_replace.note.startswith("今の化粧水Aと入れ替える前提で")
    without = normalize.owned_relation(cat, NEW_LOTION, ["own_l", "own_e"])
    assert without.routine_level == "overlap" and "niacinamide" in without.shared_directions


def test_routine_level_is_unknown_without_owned_or_with_incomplete_ingredients():
    assert normalize.owned_relation(_cat(LOTION), NEW_LOTION, ["own_l"], ["own_l"]).routine_level == "unknown"
    partial = EMULSION.model_copy(update={"ingredients_complete": False})
    assert normalize.owned_relation(_cat(LOTION, partial), NEW_LOTION, ["own_l", "own_e"], ["own_l"]).routine_level == "unknown"


def test_active_overlap_is_found_through_full_ingredients():
    """手持ちの有効成分の欄が空でも、全成分表示（記号付き）にあれば重なりとして示す。"""
    rel = normalize.owned_relation(_cat(LOTION, EMULSION), NEW_LOTION, ["own_l", "own_e"], ["own_l"])
    assert rel.active_ingredients == ["トラネキサム酸"]
    assert [(o.canonical, o.owned_product_ids) for o in rel.active_overlaps] == [("トラネキサム酸", ["own_e"])]
    assert "有効成分のトラネキサム酸は、手持ちの乳液Cにも含まれます" in rel.note
    assert "不要・危険という意味ではありません" in rel.note


def test_released_actives_are_reported_only_when_confirmed():
    rel = normalize.owned_relation(_cat(LOTION, EMULSION), NEW_LOTION, ["own_l", "own_e"], ["own_l"])
    assert [(o.canonical, o.owned_product_ids) for o in rel.released_actives] == [("グリチルリチン酸2K", ["own_l"])]
    assert "入れ替える化粧水Aの有効成分（グリチルリチン酸2K）は" in rel.note
    # 残りの手持ちにあれば、手放すとは言わない
    kept = EMULSION.model_copy(update={"ingredients_full": [*EMULSION.ingredients_full, "グリチルリチン酸2K"]})
    assert normalize.owned_relation(_cat(LOTION, kept), NEW_LOTION, ["own_l", "own_e"], ["own_l"]).released_actives == []
    # 全成分を確認しきれない手持ちがあれば、判断できないと示す
    partial = EMULSION.model_copy(update={"ingredients_complete": False})
    rel2 = normalize.owned_relation(_cat(LOTION, partial), NEW_LOTION, ["own_l", "own_e"], ["own_l"])
    assert rel2.released_actives == [] and rel2.actives_unconfirmed
    assert "判断できません" in rel2.note


def test_replaced_textures_are_listed_for_comparison():
    rel = normalize.owned_relation(_cat(LOTION, EMULSION), NEW_LOTION, ["own_l", "own_e"], ["own_l"])
    assert rel.replaced_textures == {"化粧水A": "美容液のようなさっぱりタイプ"}
    views = {p.product_id: p for p in normalize.owned_analysis(_cat(LOTION, EMULSION), ["own_l", "own_e"], ["own_l"]).products}
    assert views["own_l"].maker_texture_description == "美容液のようなさっぱりタイプ"
    assert views["own_l"].active_ingredients == ["グリチルリチン酸2K"]


SELECTION = {"other_step": [{"direction_id": "retinoid", "category": "emulsion", "why": "テスト"}]}


def test_other_step_is_planned_only_when_conditions_hold():
    cat = _cat(LOTION, EMULSION)
    plan = other_step_plan(cat, _req(), SELECTION, [])
    assert plan["action"] == "replace" and plan["replaced_product_id"] == "own_e" and plan["replaced_name"] == "乳液C"
    add = other_step_plan(cat, _req(), {"other_step": [{"direction_id": "retinoid", "category": "serum", "why": ""}]}, [])
    assert add["action"] == "add" and add["replaced_product_id"] is None


def test_other_step_is_skipped_when_conditions_fail():
    cat = _cat(LOTION, EMULSION)
    found = {"other_step": [{"direction_id": "hydration", "category": "emulsion", "why": ""}]}
    assert other_step_plan(cat, _req(), found, []) is None  # 方向性が手持ちで確認できる
    assert other_step_plan(cat, _req(), SELECTION, [{"direction_id": "retinoid"}]) is None  # 候補で補えている
    same = {"other_step": [{"direction_id": "retinoid", "category": "lotion", "why": ""}]}
    assert other_step_plan(cat, _req(), same, []) is None  # 探すアイテムと同じ種類
    uv = {"other_step": [{"direction_id": "retinoid", "category": "sunscreen", "why": ""}]}
    assert other_step_plan(cat, _req(), uv, []) is None  # 対象外の種類
    assert other_step_plan(cat, _req(keep=("own_e",)), SELECTION, []) is None  # 残したい乳液は替えない
    partial = _cat(LOTION, EMULSION.model_copy(update={"ingredients_complete": False}))
    assert other_step_plan(partial, _req(), SELECTION, []) is None  # 見当たらないと言い切れない
    assert other_step_plan(cat, _req(), {}, []) is None
