"""外部APIを呼ばない比較サンプル。価格・表示は登録済み実データ、口コミは補わない。"""
from . import assemble, explain_template
from .catalog import load
from .schemas import Conditions, RecommendRequest, DEFAULT_PRIORITIES, LIGHT_PRIORITIES


def build_preview(priority: str = "concern"):
    cat = load()
    req = RecommendRequest(conditions=Conditions(budget_jpy_max=3000),
                           priorities=list(LIGHT_PRIORITIES if priority == "light" else DEFAULT_PRIORITIES))
    result = assemble.build(cat, req, list(cat.directions), {})
    result.is_preview = True
    for candidate in result.candidates:
        candidate.explanation = explain_template.build(candidate)
    result.explanation_mode = "template"
    return result
