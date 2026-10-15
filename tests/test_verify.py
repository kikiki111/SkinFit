from app import assemble, explain_template, verify
from app.catalog import load
from app.schemas import Explanation, Reason
from tests.helpers import DIRECTIONS, demo_request, keyword_findings


def _result():
    cat = load()
    res = assemble.build(cat, demo_request(), DIRECTIONS, keyword_findings(cat.reviews))
    for c in res.candidates:
        c.explanation = explain_template.build(c)
    return cat, res


def test_template_always_passes():
    cat, res = _result()
    assert verify.check_result(cat, res) == []


def test_unknown_source_id_is_rejected():
    cat, res = _result()
    c = res.candidates[0]
    c.explanation = Explanation(summary="候補です。", reasons=[Reason(category="concern", text="表示があります。", source_ids=["src_fake"])])
    assert any("src_fake" in v.message for v in verify.check_explanation(cat, c, c.explanation))


def test_forbidden_words_even_in_negation():
    cat, res = _result()
    c = res.candidates[0]
    for text in ["シワが消えるわけではありません", "安全にお使いいただけます", "必ず効くとは言えません"]:
        e = Explanation(summary=text)
        assert verify.check_explanation(cat, c, e), text


def test_numbers_are_not_allowed_in_text():
    cat, res = _result()
    c = res.candidates[0]
    assert verify.check_explanation(cat, c, Explanation(summary="2,970円で買えます"))
    assert verify.check_explanation(cat, c, Explanation(summary="口コミ5件のうち"))


def test_price_and_rank_mismatch_are_structural_errors():
    cat, res = _result()
    res.candidates[0].price_jpy = 1
    res.recommended_product_id = res.candidates[1].product_id
    wheres = {v.where for v in verify.check_result(cat, res)}
    assert {"price_jpy", "recommended_product_id"} <= wheres
