"""RecommendationWorkflow（ADK 2.x のグラフ型Workflow）。ループの無い流れで、独立した検索は同時に走らせる。

方向性の確定 → 手持ちの検索と探索エージェント3つ（方向性ごと）を同時 → 合流 → 選定エージェント
→ 候補を調べる（並行）→ 3分岐（成分・口コミ・配置）→ 合流 → 順位 → 説明

- 調べる処理は Gemini の Google検索連携を使う（research.py）。検索に失敗したら、登録済みの候補で代替する
- その場で調べた製品・口コミはセッション状態の "bundle" に置き、各ノードはそこから製品データを組み立てる
- 各ノードは失敗しても例外を投げず、status を返す（例外が出るとWorkflow全体が止まり、JoinNodeが揃わないため）
"""

import asyncio
import datetime
import time
from types import SimpleNamespace

from google.adk import Workflow
from google.adk.workflow import JoinNode

from .. import assemble, normalize, research, reviews
from ..catalog import Catalog, catalog_from_bundle, load, search_candidates
from ..config import settings
from ..logging_utils import log_event
from ..schemas import Conditions, Product, RecommendationResult, RecommendRequest, ResearchStep
from . import agents

LIGHT_WORDS = ("さっぱり", "軽", "みずみずし", "ベタつかない", "べたつかない", "さらっと", "サラッと")


def _req(ctx) -> RecommendRequest:
    """手持ちに番号を振った後の依頼（owned_product_ids / keep_product_ids を含む）。"""
    return RecommendRequest.model_validate(ctx.state.get("request_eff") or ctx.state["request"])


def _cat(ctx) -> Catalog:
    b = ctx.state.get("bundle")
    return catalog_from_bundle(b) if b else load()


def _note(ctx, text: str) -> None:
    b = ctx.state.get("bundle") or {}
    b.setdefault("notes", []).append(text)
    ctx.state["bundle"] = b


async def owned_research(ctx, node_input) -> dict:
    """写真から確定した手持ちの全成分を、Google検索で調べる（3品まで並行）。"""
    t = time.time()
    req = RecommendRequest.model_validate(ctx.state["request"])
    base = load()
    owned: list[Product] = [base.product(pid) for pid in req.owned_product_ids if pid in base.products]
    keep_ids = [pid for pid in req.keep_product_ids if pid in base.products]
    suggestions: list[str] = []
    notes: list[str] = []
    log: list[dict] = []
    items = req.owned_items
    results = await asyncio.gather(*(research.research_owned(i.model_dump(), f"own_{n}") for n, i in enumerate(items, 1)),
                                   return_exceptions=True)
    owned_log: list[dict] = []
    for n, (item, r) in enumerate(zip(items, results), 1):
        pid = f"own_{n}"
        if isinstance(r, BaseException):
            log_event("node_error", severity="ERROR", node="owned_research", product_id=pid, error=type(r).__name__)
            notes.append(f"{item.name}：全成分を検索で調べられませんでした")
            owned_log.append({"step": "owned", "target": f"{item.brand or ''} {item.name}".strip(), "status": "failed",
                        "summary": "検索に失敗したため、全成分を確認できませんでした", "details": [], "queries": [], "sources": []})
            p = Product(product_id=pid, role="owned", brand=item.brand or "", name=item.name, category=item.category,
                        checked_at=datetime.date.today().isoformat(), data_version="live",
                        unknown=[{"field": "全成分", "reason": "検索に失敗した"}])
        else:
            p, entry, step = r
            if entry:
                suggestions.append(entry)
            owned_log.append(step.model_dump())
            p.category = item.category if item.category != "other" else p.category
        owned.append(p)
        if item.keep:
            keep_ids.append(pid)
    eff = req.model_copy(update={"owned_product_ids": [p.product_id for p in owned], "keep_product_ids": keep_ids})
    ctx.state["request_eff"] = eff.model_dump()
    # 方向性はまだ確定していない（prepare と同時に走る）。方向性を使う照合は、合流後の prepare_selection で行う
    ctx.state["bundle"] = {"owned": [p.model_dump() for p in owned], "candidates": [], "reviews": [], "findings": None,
                           "mode": "live", "researched_at": datetime.datetime.now().isoformat(timespec="minutes"),
                           "suggestions": suggestions, "notes": notes, "research_log": log + owned_log,
                           "directions": None, "evidence": None,
                           "owned_ids": eff.owned_product_ids, "keep_ids": keep_ids}
    log_event("node", node="owned_research", owned=len(owned), searched=len(items), ms=int((time.time() - t) * 1000))
    return {"status": "OK", "owned": len(owned)}


def _finish_owned(ctx) -> list[dict]:
    """方向性が確定した後で、手持ちの照合（方向性に当たる成分・手持ちの方向性）を行い、記録に足す。"""
    prep = ctx.state.get("prepared") or {}
    b = ctx.state["bundle"]
    b["directions"], b["evidence"] = prep.get("directions_live"), prep.get("evidence_live")
    b["research_log"] = prep.get("log", []) + b.get("research_log", [])
    b["notes"] = prep.get("notes", []) + b.get("notes", [])
    ctx.state["bundle"] = b
    cat = _cat(ctx)
    labels = {d.direction_id: d.label for d in cat.directions.values()}
    owned_logs = [x for x in b["research_log"] if x.get("step") == "owned"]
    researched = [cat.product(pid) for pid in b.get("owned_ids", []) if pid.startswith("own_") and pid in cat.products]
    for entry_log, p in zip(owned_logs, researched):  # 検索した手持ちと記録は、同じ順で並んでいる
        found: dict[str, list[str]] = {}
        for h in normalize.ingredient_hits(cat, p):
            found.setdefault(labels.get(h.direction_id, h.direction_id), []).append(h.name)
        entry_log["details"] = [f"{k}の成分：{'、'.join(dict.fromkeys(v))}" for k, v in found.items()] or ["方向性に当たる成分は見当たりませんでした"]
        if p.ingredients_full:
            entry_log["details"].append("取得した全成分：" + "、".join(p.ingredients_full))
    ctx.state["bundle"] = b
    coverage = [c.model_dump() for c in normalize.owned_analysis(cat, b.get("owned_ids", [])).coverage]
    return [{k: c[k] for k in ("direction_id", "label", "status", "ingredients")} for c in coverage]


def _choose(stubs: list[dict], conditions: Conditions, owned: list[Product], limit: int) -> tuple[list[dict], list[str]]:
    """詳しく調べる候補を選ぶ。予算・手持ちとの重複で外し、効能表示のあるものと軽い使用感のものを含める。"""
    owned_names = {(p.brand + p.name).replace(" ", "") for p in owned}
    ok, notes = [], []
    for s in stubs:
        label = f"{s.get('brand', '')} {s['name']}"
        if (s.get("brand", "") + s["name"]).replace(" ", "") in owned_names:
            notes.append(f"外した：{label}（手持ちと同じ製品）")
            continue
        price = s.get("price_jpy_tax_included")
        if conditions.budget_jpy_max and price and price > conditions.budget_jpy_max:
            notes.append(f"外した：{label}（予算を超える）")
            continue
        ok.append(s)
    ok.sort(key=lambda s: (not s.get("claim_texts"), s.get("price_jpy_tax_included") is None))
    picked = ok[:limit]
    light = [s for s in ok if any(w in (s.get("texture_note") or "") for w in LIGHT_WORDS)]
    if light and not any(s in picked for s in light) and picked:
        picked[-1] = light[0]
    for s in ok:
        label = f"{s.get('brand', '')} {s['name']}"
        notes.append(f"詳しく調べる：{label}" if s in picked else f"今回は調べない：{label}（候補数の上限{limit}件）")
    return picked, notes


MAX_DIRECTIONS = 3  # 探索エージェントの数（方向性が少ないときは、余ったエージェントは SKIPPED を返す）


async def prepare(ctx, node_input) -> dict:
    """調べる方向性を確定する。小じわは登録済み、それ以外はその場で調べる（探索の前に必要な唯一の検索）。"""
    req = RecommendRequest.model_validate(ctx.state["request"])
    prepared: dict = {"directions_live": None, "evidence_live": None, "log": [], "notes": []}
    if req.conditions.concern == "custom":
        prepared["directions_live"], prepared["evidence_live"] = [], []
        if settings.research_mode == "live":
            try:
                dirs_, ev_, cstep = await research.research_concern(req.conditions.concern, req.conditions.concern_label)
                prepared["directions_live"] = [d.model_dump() for d in dirs_]
                prepared["evidence_live"] = [e.model_dump() for e in ev_]
                prepared["log"].append(cstep.model_dump())
            except Exception as e:  # noqa: BLE001
                log_event("node_error", severity="ERROR", node="research_concern", error=type(e).__name__)
        if not prepared["directions_live"]:
            prepared["notes"].append(f"悩み「{req.conditions.concern_label}」に関わる成分の方向性を、検索で確かめられませんでした")
        directions = prepared["directions_live"]
    else:
        directions = [d.model_dump() for d in load().directions.values()]
    ctx.state["prepared"] = prepared
    directions = directions[:MAX_DIRECTIONS]
    log_event("node", node="prepare", directions=[d["label"] for d in directions])
    out = [{"direction_id": d["direction_id"], "label": d["label"], "members": d["member_ingredients"]} for d in directions]
    ctx.state["prepared_directions"] = out  # 探索Agentの後ろの構造化ノードが、何番目の方向性かを知るため
    return {"directions": out}


SKIP_PROMPT = "検索しないで『なし』と答えてください。"


def _make_dir(index: int):
    """探索Agent index 番目に渡す検索の指示を作る。方向性が無ければ、検索しない短い指示を渡す。"""

    def dir_node(ctx, node_input: dict) -> str:
        dirs = (node_input or {}).get("directions", [])
        if index >= len(dirs) or settings.research_mode != "live":
            return SKIP_PROMPT
        req = RecommendRequest.model_validate(ctx.state["request"])
        owned_names = [SimpleNamespace(brand=i.brand or "", name=i.name) for i in req.owned_items]
        return research.discover_prompt(req.conditions, [dirs[index]], owned_names, limit=3) + research.MUST_SEARCH

    dir_node.__name__ = f"dir_{index + 1}"
    return dir_node


def _make_discover_structure(index: int):
    """探索Agent index 番目の答えを、状態に保存された出典つきで構造化する。結果は返すだけで、共有の状態には書かない。"""

    async def discover(ctx, node_input) -> dict:
        prep_dirs = (ctx.state.get("prepared_directions") or [])
        if index >= len(prep_dirs) or settings.research_mode != "live":
            return {"status": "SKIPPED", "index": index, "stubs": []}
        d = prep_dirs[index]
        raw = ctx.state.get(f"discover_raw_{index + 1}") or {}
        t = time.time()
        try:
            g = research.grounded_from_raw(raw)
            req = RecommendRequest.model_validate(ctx.state["request"])
            stubs, step = await research.structure_discovery(req.conditions, g, f"{d['label']}：")
        except Exception as e:  # noqa: BLE001
            log_event("node_error", severity="ERROR", node=f"discover_{index + 1}", error=type(e).__name__)
            return {"status": "FAILED", "index": index, "stubs": [], "label": d["label"]}
        for st in stubs:
            st["direction_id"], st["direction_label"] = d["direction_id"], d["label"]
        log_event("node", node=f"discover_{index + 1}", direction=d["label"], stubs=len(stubs), sources=len(g.sources),
                  ms=int((time.time() - t) * 1000))
        return {"status": "OK" if stubs else "FAILED", "index": index, "stubs": stubs, "label": d["label"],
                "entry": g.entry_point_html, "step": step.model_dump()}

    discover.__name__ = f"discover_{index + 1}"
    return discover


def _make_discover(index: int):
    """（関数ノード版）方向性 index 番目だけを探す。ADKの探索Agentを使わない構成で使う。"""

    async def discover(ctx, node_input: dict) -> dict:
        dirs = (node_input or {}).get("directions", [])
        if index >= len(dirs) or settings.research_mode != "live":
            return {"status": "SKIPPED", "index": index, "stubs": []}
        d = dirs[index]
        req = RecommendRequest.model_validate(ctx.state["request"])
        owned_names = [SimpleNamespace(brand=i.brand or "", name=i.name) for i in req.owned_items]
        t = time.time()
        try:
            stubs, _, entry, step = await research.discover_candidates(req.conditions, [d], owned_names, limit=3)
        except Exception as e:  # noqa: BLE001
            log_event("node_error", severity="ERROR", node=f"discover_{index + 1}", error=type(e).__name__)
            return {"status": "FAILED", "index": index, "stubs": [], "label": d["label"]}
        for st in stubs:
            st["direction_id"], st["direction_label"] = d["direction_id"], d["label"]
        step.target = f"{d['label']}：{step.target}"
        log_event("node", node=f"discover_{index + 1}", direction=d["label"], stubs=len(stubs), ms=int((time.time() - t) * 1000))
        return {"status": "OK", "index": index, "stubs": stubs, "label": d["label"], "entry": entry, "step": step.model_dump()}

    discover.__name__ = f"discover_{index + 1}"
    return discover


def _stub_key(stub: dict) -> str:
    return (stub.get("brand", "") + stub["name"]).replace(" ", "").replace("　", "")


def prepare_selection(ctx, node_input: dict) -> dict:
    """手持ちの調査と探索の結果をまとめ、必須条件（予算・手持ちとの重複）を当ててから、選定エージェントに渡す。"""
    owned_coverage = _finish_owned(ctx)
    found = [node_input.get(f"discover_{i + 1}") or {} for i in range(MAX_DIRECTIONS)]
    b = ctx.state["bundle"]
    stubs, seen = [], set()
    for f in found:
        if f.get("entry"):
            b["suggestions"].append(f["entry"])
        if f.get("step"):
            b.setdefault("research_log", []).append(f["step"])
        for st in f.get("stubs", []):
            if _stub_key(st) not in seen:  # 別の方向性で同じ製品が見つかったら1つにまとめる
                seen.add(_stub_key(st))
                stubs.append(st)
    req = _req(ctx)
    cat = _cat(ctx)
    owned = [cat.product(pid) for pid in req.owned_product_ids if pid in cat.products]
    # 上限を全件にして呼び、必須条件（予算・手持ちとの重複）だけを当てる
    pool, notes = _choose(stubs, req.conditions, owned, len(stubs) or 1)
    for i, s in enumerate(pool, 1):
        s["candidate_id"] = f"c{i}"
    mode = "live" if pool else ("catalog" if settings.research_mode != "live" else "catalog_fallback")
    if settings.research_mode == "live" and not pool:
        b.setdefault("notes", []).append("検索で条件に合う候補を見つけられなかったため、登録済みの候補で推薦しています")
    ctx.state["bundle"] = b
    ctx.state["selection_pool"] = {"stubs": pool, "excluded_notes": [n for n in notes if n.startswith("外した：")],
                                   "directions": [d.direction_id for d in cat.directions.values()], "mode": mode}
    log_event("node", node="prepare_selection", found=len(stubs), pool=len(pool), mode=mode)
    # 次の Agent ノード（select_agent）への入力
    return {
        "conditions": req.conditions.model_dump(include={"concern_label", "category", "budget_jpy_max", "texture_preferences", "keep_note"}),
        "owned_coverage": owned_coverage,
        "max_select": settings.max_live_candidates,
        "candidates": [{"candidate_id": s["candidate_id"], "brand": s.get("brand"), "name": s["name"],
                        "price_jpy_tax_included": s.get("price_jpy_tax_included"), "direction": s.get("direction_label"),
                        "key_ingredients": s.get("key_ingredients", [])[:5], "claim_texts": s.get("claim_texts", [])[:2],
                        "texture_note": s.get("texture_note")} for s in pool],
    }


def _apply_selection(ctx, selection: dict | None) -> tuple[list[dict], str, list[str]]:
    """選定エージェントの答えを検査して、詳しく調べる候補を決める。探索に無いIDは捨て、使えなければPythonの選び方で代替する。"""
    pool_info = ctx.state.get("selection_pool") or {}
    pool = pool_info.get("stubs", [])
    by_id = {s["candidate_id"]: s for s in pool}
    limit = settings.max_live_candidates
    picked: list[dict] = []
    notes = list(pool_info.get("excluded_notes", []))
    for item in (selection or {}).get("selected", [])[:limit]:
        s = by_id.get(item.get("candidate_id"))
        if s is not None and s not in picked:
            picked.append(s)
            notes.append(f"詳しく調べる：{s.get('brand', '')} {s['name']}（{item.get('why', '')}）")
    how = "agent"
    if not picked and pool:
        req = _req(ctx)
        cat = _cat(ctx)
        owned = [cat.product(pid) for pid in req.owned_product_ids if pid in cat.products]
        picked, more = _choose(pool, req.conditions, owned, limit)
        notes += [n for n in more if n.startswith("詳しく調べる")]
        how = "fallback"
    reasons = {x.get("candidate_id"): x.get("why", "") for x in (selection or {}).get("excluded", [])}
    for s in pool:
        if s not in picked:
            why = reasons.get(s.get("candidate_id"), "")
            notes.append(f"今回は調べない：{s.get('brand', '')} {s['name']}" + (f"（{why}）" if why else ""))
    return picked, how, notes


async def candidate_discovery(ctx, node_input: dict) -> dict:
    """方向性と予算に合う商品を、Google検索で探す。失敗したら登録済みの候補で代替する。"""
    cat = _cat(ctx)
    req = _req(ctx)
    planned = [d.get("direction_id") for d in (node_input or {}).get("directions", [])]
    directions = assemble.valid_directions(cat, planned)
    out = {"directions": directions, "needs_more_info": bool((node_input or {}).get("needs_more_info")),
           "questions": (node_input or {}).get("questions", [])[:2], "stubs": [], "mode": "live"}
    if settings.research_mode != "live":
        out["mode"] = "catalog"
        return out
    try:
        dirs = [{"label": cat.directions[d].label, "members": cat.directions[d].member_ingredients} for d in directions]
        owned = [cat.product(pid) for pid in req.owned_product_ids if pid in cat.products]
        stubs, _, entry, step = await research.discover_candidates(req.conditions, dirs, owned)
        out["stubs"], choose_notes = _choose(stubs, req.conditions, owned, settings.max_live_candidates)
        step.details = step.details + choose_notes
        b = ctx.state["bundle"]
        if entry:
            b["suggestions"].append(entry)
        b.setdefault("research_log", []).append(step.model_dump())
        ctx.state["bundle"] = b
        if not out["stubs"]:
            out["mode"] = "catalog_fallback"
            _note(ctx, "検索で条件に合う候補を見つけられなかったため、登録済みの候補で推薦しています")
    except Exception as e:  # noqa: BLE001
        log_event("node_error", severity="ERROR", node="candidate_discovery", error=type(e).__name__)
        out["mode"] = "catalog_fallback"
        _note(ctx, "候補の検索に失敗したため、登録済みの候補で推薦しています")
    log_event("node", node="candidate_discovery", mode=out["mode"], stubs=[s["name"] for s in out["stubs"]], directions=directions)
    return out


async def candidate_research(ctx, node_input: dict) -> dict:
    """選定エージェントが選んだ候補ごとに、全成分・効能表示・用法・使用感の口コミをGoogle検索で調べる（並行）。"""
    t = time.time()
    base = load()
    pool_info = ctx.state.get("selection_pool") or {}
    stubs, how, sel_notes = _apply_selection(ctx, node_input)
    b = ctx.state["bundle"]
    b.setdefault("research_log", []).append({
        "step": "discover", "target": "詳しく調べる候補の選定", "status": "ok" if stubs else "failed",
        "summary": ("選定エージェントが" if how == "agent" else "決まった規則で") + f"{len(stubs)}品を選びました",
        "details": sel_notes, "queries": [], "sources": []})
    node_input = {"stubs": stubs, "mode": pool_info.get("mode", "catalog_fallback"),
                  "directions": pool_info.get("directions", []), "needs_more_info": False, "questions": []}
    mode = node_input["mode"]
    if mode == "live":
        cond = _req(ctx).conditions
        results = await asyncio.gather(*(research.research_candidate(s, f"cand_{n}", cond.concern, cond.concern_label)
                                         for n, s in enumerate(node_input["stubs"], 1)), return_exceptions=True)
        cands, revs, findings = [], [], {}
        for s, r in zip(node_input["stubs"], results):
            if isinstance(r, BaseException):
                log_event("node_error", severity="ERROR", node="candidate_research", name=s["name"], error=type(r).__name__)
                b.setdefault("notes", []).append(f"{s['name']}：検索で詳しく調べられなかったため候補から外しました")
                continue
            p, rv, f, entry, steps = r
            b.setdefault("research_log", []).extend(x.model_dump() for x in steps)
            cands.append(p.model_dump())
            revs += [x.model_dump() for x in rv]
            findings.update(f)
            if entry:
                b["suggestions"].append(entry)
        if not cands:
            mode = "catalog_fallback"
            b.setdefault("notes", []).append("候補の検索に失敗したため、登録済みの候補で推薦しています")
        else:
            b.update(candidates=cands, reviews=revs, findings=findings)
    if mode != "live":
        # 登録済みの候補は小じわ向け。ほかの悩みでは代替に使わない
        regs = [p for p in base.products.values() if p.role == "candidate"] if _req(ctx).conditions.concern == "fine_lines" else []
        if not regs:
            b.setdefault("notes", []).append("登録済みの代替候補は小じわ向けのため、この悩みでは使っていません")
        b.update(candidates=[p.model_dump() for p in regs], reviews=[r.model_dump() for r in base.reviews], findings=None)
    b["mode"] = mode
    ctx.state["bundle"] = b
    cat = _cat(ctx)
    ids, excluded = search_candidates(cat, _req(ctx).conditions, node_input["directions"])
    log_event("node", node="candidate_research", mode=mode, candidates=ids, excluded=len(excluded), ms=int((time.time() - t) * 1000))
    return {**node_input, "mode": mode, "candidate_ids": ids, "excluded": excluded}


def ingredient_branch(ctx, node_input: dict) -> dict:
    if not node_input["candidate_ids"]:
        return {"status": "SKIPPED", "search": node_input}
    try:
        info = assemble.research_ingredients(_cat(ctx), _req(ctx), node_input["candidate_ids"], node_input["directions"])
        status = "OK"
    except Exception as e:  # noqa: BLE001  分岐の失敗は状態として返す
        info, status = None, "FAILED"
        log_event("node_error", severity="ERROR", node="ingredient_branch", error=type(e).__name__)
    return {"status": status, "info": info, "search": node_input}


async def review_branch(ctx, node_input: dict) -> dict:
    """口コミの論点判定。その場の検索では調べた時点で判定済み。登録済みの口コミはここでGeminiが判定する。"""
    t = time.time()
    ids = node_input["candidate_ids"]
    if not ids:
        return {"status": "SKIPPED", "findings": {}, "failed": []}
    b = ctx.state.get("bundle") or {}
    if b.get("findings") is not None:
        cat = _cat(ctx)
        none = [pid for pid in ids if not cat.reviews_for(pid)]
        return {"status": "OK" if not none else "INSUFFICIENT", "findings": b["findings"], "failed": []}
    cat = _cat(ctx)

    async def one(pid: str):
        uniq, _ = reviews.unique_reviews(cat, pid)
        if not uniq:
            return pid, {}
        return pid, await reviews.extract_findings(cat.product(pid).name, uniq)

    results = await asyncio.gather(*(one(pid) for pid in ids), return_exceptions=True)
    findings: dict[str, dict[str, str]] = {}
    failed: list[str] = []
    for pid, r in zip(ids, results):
        if isinstance(r, BaseException):
            failed.append(pid)
            log_event("node_error", severity="ERROR", node="review_branch", product_id=pid, error=type(r).__name__)
        else:
            findings.update(r[1])
    status = "OK" if not failed else ("FAILED" if len(failed) == len(ids) else "INSUFFICIENT")
    log_event("node", node="review_branch", status=status, analyzed=len(findings), failed=failed, ms=int((time.time() - t) * 1000))
    return {"status": status, "findings": findings, "failed": failed}


def routine_branch(ctx, node_input: dict) -> dict:
    try:
        plans = assemble.plan_routines(_cat(ctx), _req(ctx), node_input["candidate_ids"])
        status = "OK" if node_input["candidate_ids"] else "SKIPPED"
    except Exception as e:  # noqa: BLE001
        plans, status = None, "FAILED"
        log_event("node_error", severity="ERROR", node="routine_branch", error=type(e).__name__)
    return {"status": status, "plans": plans}


def attach_research(result: RecommendationResult, bundle: dict | None) -> RecommendationResult:
    """その場の調査の情報（方式・時刻・検索候補・注記）と、並べ替え用の bundle を結果に付ける。"""
    if not bundle:
        return result
    result.research_mode = bundle.get("mode", "catalog")
    result.researched_at = bundle.get("researched_at")
    result.research_notes = list(dict.fromkeys(bundle.get("notes") or []))
    result.search_suggestions_html = list(dict.fromkeys(bundle.get("suggestions") or []))[:3]
    result.research_log = [ResearchStep.model_validate(x) for x in bundle.get("research_log") or []]
    result.analysis.bundle = {k: bundle.get(k) for k in ("owned", "candidates", "reviews", "mode", "researched_at",
                                                         "owned_ids", "keep_ids", "notes", "suggestions", "research_log",
                                                         "directions", "evidence")}
    return result


def rank(ctx, node_input: dict) -> dict:
    """合流した調査結果から、Pythonで順位と表示用の結果を組み立てる。"""
    ing, rev, rou = node_input["ingredient_branch"], node_input["review_branch"], node_input["routine_branch"]
    search = ing["search"]
    branch_status = {"ingredient": ing["status"], "review": rev["status"], "routine": rou["status"]}
    result = assemble.build(
        _cat(ctx), _req(ctx), search["directions"], rev.get("findings") or {},
        branch_status=branch_status, ingredient_info=ing.get("info"), routine_plans=rou.get("plans"),
        failed_review_products=set(rev.get("failed") or []),
    )
    if search["questions"]:
        result.follow_up_questions = search["questions"]
    result = attach_research(result, ctx.state.get("bundle"))
    log_event("node", node="rank", status=result.status, mode=result.research_mode,
              order=result.ranking.order if result.ranking else [], branch_status=branch_status)
    return {"result": result.model_dump(), "needs_more_info": search["needs_more_info"], "directions": search["directions"]}


async def explain(ctx, node_input: dict) -> dict:
    result = RecommendationResult.model_validate(node_input["result"])
    if result.status != "RECOMMENDATION_READY":
        return {**node_input, "explanations": {}, "explain_status": "SKIPPED"}
    try:
        expl = await agents.explain(_req(ctx).conditions, result.candidates)
        return {**node_input, "explanations": {k: v.model_dump() for k, v in expl.items()}, "explain_status": "OK"}
    except Exception as e:  # noqa: BLE001  説明の失敗は orchestrator が定型文で補う
        log_event("node_error", severity="ERROR", node="explain", error=type(e).__name__)
        return {**node_input, "explanations": {}, "explain_status": "FAILED"}


def build_workflow() -> Workflow:
    """方向性の確定 → 手持ちの検索と探索エージェント3つを同時 → 合流 → 選定エージェント → 候補の調査 → 3分岐 → 合流 → 順位 → 説明。"""
    gather = JoinNode(name="gather")
    join = JoinNode(name="join")
    # 探索は方向性ごとに「検索の指示を作る → ADKの探索Agent（google_search）→ 出典つきで構造化」の3段
    chains = [(prepare, _make_dir(i), agents.discover_agent(i), _make_discover_structure(i), gather) for i in range(MAX_DIRECTIONS)]
    return Workflow(name="recommendation", edges=[
        # 手持ちの検索は方向性を待たずに最初から走らせる。探索エージェントは方向性の確定（prepare）を待つ
        ("START", owned_research, gather),
        ("START", prepare),
        *chains,
        (gather, prepare_selection, agents.select_agent(), candidate_research),
        (candidate_research, ingredient_branch, join),
        (candidate_research, review_branch, join),
        (candidate_research, routine_branch, join),
        (join, rank, explain),
    ])
