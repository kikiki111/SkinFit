"""本番の data/ を検査する。ローカルOKの判定とCloud Runへの移行の前に、必ず通すこと。"""

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def _load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def test_no_dummy_data_remains():
    products = _load("products.json")["products"]
    reviews = _load("reviews.json")["reviews"]
    evidence = _load("evidence.json")
    aliases = _load("ingredient_aliases.json")
    dummies = [p["product_id"] for p in products if p.get("is_dummy")]
    dummies += [r["review_id"] for r in reviews if r.get("is_dummy")]
    dummies += [e["evidence_id"] for e in evidence["evidence"] if e.get("is_dummy")]
    if aliases.get("is_dummy"):
        dummies.append("ingredient_aliases.json")
    assert not dummies, f"ダミーデータが残っています: {dummies[:10]}"


def test_sources_and_references_are_complete():
    products = _load("products.json")["products"]
    problems = []
    for p in products:
        ids = {s["source_id"] for s in p.get("sources", [])}
        for s in p.get("sources", []):
            if not s.get("url", "").startswith("http") or not s.get("checked_at"):
                problems.append(f"{p['product_id']}: 出典 {s.get('source_id')} のURLか確認日が欠けている")
        for key in ("price_source_id", "ingredients_source_id"):
            if p.get(key) and p[key] not in ids:
                problems.append(f"{p['product_id']}: {key} {p[key]} が sources にない")
        for c in p.get("claims", []):
            if c["source_id"] not in ids:
                problems.append(f"{p['product_id']}: claim {c['claim_id']} の出典がない")
        if p.get("usage", {}).get("source_id") and p["usage"]["source_id"] not in ids:
            problems.append(f"{p['product_id']}: 用法の出典がない")
    pids = {p["product_id"] for p in products}
    for r in _load("reviews.json")["reviews"]:
        if r["product_id"] not in pids:
            problems.append(f"{r['review_id']}: 製品 {r['product_id']} がない")
        if not r.get("url", "").startswith("http"):
            problems.append(f"{r['review_id']}: URLがない")
    for e in _load("evidence.json")["evidence"]:
        if not e["source"].get("url", "").startswith("http"):
            problems.append(f"{e['evidence_id']}: 出典URLがない")
    assert not problems, "\n".join(problems[:20])
