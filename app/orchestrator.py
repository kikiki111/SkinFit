"""Workflowの外側。前段の確認（intake_check）と、後段の必須照合（verify）・説明のやり直しを受け持つ。

- 前: 商品・悩みが確定していなければ Workflow を動かさず NEEDS_MORE_INFO を返す
- 後: verify がNGなら、違反内容を添えて説明だけを作り直す（最大2回）。それでもNGなら定型文に切り替える
- HALTED は、API障害・時間切れ・データ不整合（Pythonの確定値側の問題）のときだけ
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator

from google.adk import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from . import assemble, explain_template, normalize, reviews, verify
from .catalog import Catalog, catalog_from_bundle, load, search_candidates
from .config import settings
from .logging_utils import estimate_cost_usd, log_event, run_id_var, start_usage
from .schemas import (concern_id_for, Explanation, ProgressEvent, ProgressStage, RecommendationResult, RecommendRequest,
                      RerankRequest, ResultEvent)
from .workflows import agents
from .workflows.recommendation import build_workflow

# 進捗を送るノードの一覧。ノード → (画面の段階, 表示名)
# 画面はノード名を知らず、段階だけで表示する。段階の種類は web/app.js の progressStages と一致させる（test_orchestrator.py で検査）
PROGRESS: dict[str, tuple[ProgressStage, str]] = {
    "intake_check": ("owned", "商品と条件を確認"),
    "owned_research": ("owned", "手持ちの全成分をGoogle検索で調査"),
    "prepare": ("discover", "調べる方向性を確認（小じわ以外は悩みに関わる成分をGoogle検索で調査）"),
    "dir_1": ("discover", "探索エージェント1に方向性1を渡す"),
    "dir_2": ("discover", "探索エージェント2に方向性2を渡す"),
    "dir_3": ("discover", "探索エージェント3に方向性3を渡す"),
    "discover_agent_1": ("discover", "探索エージェント1（ADK）：方向性1の候補をGoogle検索で探索"),
    "discover_agent_2": ("discover", "探索エージェント2（ADK）：方向性2の候補をGoogle検索で探索"),
    "discover_agent_3": ("discover", "探索エージェント3（ADK）：方向性3の候補をGoogle検索で探索"),
    "discover_1": ("discover", "探索エージェント1の結果を出典つきで整理"),
    "discover_2": ("discover", "探索エージェント2の結果を出典つきで整理"),
    "discover_3": ("discover", "探索エージェント3の結果を出典つきで整理"),
    "gather": ("discover", "手持ちの調査と探索の結果をそろえる"),
    "prepare_selection": ("discover", "予算・手持ちとの重複で候補を絞る"),
    "select_agent": ("discover", "選定エージェント：手持ちを踏まえて詳しく調べる候補を選ぶ"),
    "candidate_research": ("compare", "候補の成分・効能表示・口コミをGoogle検索で調査"),
    "other_step_research": ("compare", "探すアイテムで補えない方向性を、別の種類のアイテムでGoogle検索"),
    "ingredient_branch": ("compare", "成分・製品表示と手持ちを照合"),
    "review_branch": ("compare", "使用感の口コミを分析"),
    "routine_branch": ("compare", "朝夜の配置を計算"),
    "join": ("compare", "調査結果をそろえる"),
    "rank": ("finish", "優先順位で候補を比較"),
    "explain": ("finish", "推薦理由を作成"),
    "verify": ("finish", "出典・数値・表現を照合"),
}
APP_NAME = "skinfit"
# 時間のかかる処理は、始まったことも画面に出す
NEXT_RUNNING = {"prepare": ["discover_agent_1", "discover_agent_2", "discover_agent_3"],
                "prepare_selection": ["select_agent"], "select_agent": ["candidate_research"],
                "join": ["rank"], "rank": ["explain"]}


def _progress(node: str, status: str = "done") -> ProgressEvent:
    stage, label = PROGRESS.get(node, (None, node))
    return ProgressEvent(node=node, label=label, status=status, stage=stage)


def _empty(cat: Catalog, status: str, message: str, **kw) -> RecommendationResult:
    return RecommendationResult(status=status, status_message=message, data_version=cat.data_version,
                                uses_dummy_data=cat.uses_dummy, **kw)


def intake_check(cat: Catalog, req: RecommendRequest) -> RecommendationResult | None:
    questions = []
    owned = [pid for pid in req.owned_product_ids if pid in cat.products] + [i.name for i in req.owned_items if i.name.strip()]
    if not owned:
        questions.append("手持ちの商品を1つ以上確定してください（写真から選ぶか、一覧から選べます）。")
    if not (req.conditions.concern_label or "").strip():
        questions.append("優先する悩みを1つ教えてください（例：小じわ、毛穴の目立ち）。")
    if questions:
        return _empty(cat, "NEEDS_MORE_INFO", "推薦に必要な情報が足りません。", follow_up_questions=questions)
    return None


def finalize(cat: Catalog, req: RecommendRequest, result: RecommendationResult,
             explanations: dict[str, Explanation], retry=None) -> tuple[RecommendationResult, list[str]]:
    """説明を付けて照合する。説明のNGは定型文で補い、確定値側のNGは HALTED にする。"""
    if result.status != "RECOMMENDATION_READY":
        return result, []
    for c in result.candidates:
        c.explanation = explanations.get(c.product_id)
    structural = [v for v in verify.check_result(cat, result) if not v.where.startswith(("summary", "reasons", "tradeoffs", "unverified", "explanation"))]
    if structural:
        log_event("verify", severity="ERROR", result="halted", violations=[v.text() for v in structural])
        return _empty(cat, "HALTED", "照合に失敗したため、推薦を完成できませんでした（データの不整合）。",
                      missing=[v.text() for v in structural]), [v.text() for v in structural]
    templated = []
    for c in result.candidates:
        if verify.check_explanation(cat, c, c.explanation):
            c.explanation = explain_template.build(c)
            templated.append(c.product_id)
    result.explanation_mode = "template" if templated else "llm"
    result.analysis.explanations = {c.product_id: c.explanation for c in result.candidates}
    return result, templated


def normalize_request(req: RecommendRequest) -> RecommendRequest:
    """悩みの区分は、画面から来た値ではなく悩みの言葉から決め直す。"""
    cond = req.conditions.model_copy(update={"concern": concern_id_for(req.conditions.concern_label)})
    return req.model_copy(update={"conditions": cond})


async def _run_recommend(req: RecommendRequest) -> AsyncIterator[ProgressEvent | ResultEvent]:
    req = normalize_request(req)
    cat = load()
    run_id = uuid.uuid4().hex[:8]
    run_id_var.set(run_id)  # 以降のログ（ノード・検索）にこの識別子が付く
    usage = start_usage()
    t0 = time.time()
    yield _progress("intake_check")
    early = intake_check(cat, req)
    if early:
        log_event("recommend", run_id=run_id, status=early.status)
        yield ResultEvent(result=early)
        return

    outputs: dict[str, dict] = {}
    try:
        async with asyncio.timeout(settings.request_timeout_sec):
            session_service = InMemorySessionService()
            runner = Runner(app_name=APP_NAME, agent=build_workflow(), session_service=session_service)
            session = await session_service.create_session(app_name=APP_NAME, user_id=run_id, state={"request": req.model_dump()})
            message = types.Content(role="user", parts=[types.Part(text="start")])
            # 手持ちの調査を先に送る（後に送ると、画面で1段目が一瞬「完了」に見える）
            yield _progress("owned_research", "running")
            yield _progress("prepare", "running")
            async for ev in runner.run_async(user_id=run_id, session_id=session.id, new_message=message):
                node_info = getattr(ev, "node_info", None)
                out = getattr(ev, "output", None)
                if node_info is None or out is None:
                    continue
                node = str(node_info.path).split("/")[-1].split("@")[0]
                outputs[node] = out
                # ADKのAgentノード（探索エージェント）は終わりの記録に結果が載らないため、後ろの整理ノードが終わった時点で完了にする
                if node.startswith("discover_") and not node.startswith("discover_agent_"):
                    yield _progress(node.replace("discover_", "discover_agent_"))
                # 別の種類のアイテムの案は、条件を満たさなければ検索しない。そのときは「省略」と出す
                skipped = node == "other_step_research" and isinstance(out, dict) and out.get("status") == "SKIPPED"
                yield _progress(node, "skipped" if skipped else "done")
                for nxt in NEXT_RUNNING.get(node, []):
                    yield _progress(nxt, "running")
    except TimeoutError:
        log_event("recommend", severity="ERROR", run_id=run_id, status="HALTED", reason="timeout")
        yield ResultEvent(result=_empty(cat, "HALTED", f"処理時間の上限（{int(settings.request_timeout_sec)}秒）に達したため、推薦を完成できませんでした。"))
        return
    except Exception as e:  # noqa: BLE001  API障害など
        log_event("recommend", severity="ERROR", run_id=run_id, status="HALTED", error=type(e).__name__)
        yield ResultEvent(result=_empty(cat, "HALTED", "AIの呼び出しに失敗したため、推薦を完成できませんでした。時間をおいて試してください。"))
        return

    final = outputs.get("explain") or {}
    if "result" not in final:
        yield ResultEvent(result=_empty(cat, "HALTED", "調査の途中で処理が終わったため、推薦を完成できませんでした。"))
        return
    result = RecommendationResult.model_validate(final["result"])
    if result.analysis.bundle:
        cat = catalog_from_bundle(result.analysis.bundle)
    if not final.get("directions") and result.status == "NO_MATCH_IN_SCOPE":
        result.status_message = ("悩みに関わる成分の方向性を、出典付きで確かめられなかったため、候補を絞り込めませんでした。"
                                 "時間をおいて試すか、悩みの書き方を変えてください。")
    explanations = {k: Explanation.model_validate(v) for k, v in (final.get("explanations") or {}).items()}

    # 照合NGの説明は、違反内容を添えて作り直す（最大2回）
    attempts = 0
    if result.status == "RECOMMENDATION_READY":
        while attempts < settings.max_explain_retries:
            for c in result.candidates:
                c.explanation = explanations.get(c.product_id)
            bad = [v.text() for c in result.candidates for v in verify.check_explanation(cat, c, c.explanation)]
            if not bad:
                break
            attempts += 1
            log_event("verify", run_id=run_id, result="retry", attempt=attempts, violations=bad[:10])
            try:
                explanations.update(await agents.explain(req.conditions, result.candidates, bad))
            except Exception as e:  # noqa: BLE001
                log_event("node_error", severity="ERROR", node="explain_retry", error=type(e).__name__)
                break
    result, templated = finalize(cat, req, result, explanations)
    yield _progress("verify")
    log_event("usage", **usage, est_cost_usd=estimate_cost_usd(usage), ms=int((time.time() - t0) * 1000))
    log_event("recommend", run_id=run_id, status=result.status, recommended=result.recommended_product_id,
              explanation_mode=result.explanation_mode, templated=templated, retries=attempts,
              branch_status=result.branch_status, data_version=cat.data_version, ms=int((time.time() - t0) * 1000))
    yield ResultEvent(result=result)


def run_rerank(req: RerankRequest) -> RecommendationResult:
    """Geminiを呼ばずに、画面から戻ってきた分析結果を検算して並べ替える。"""
    from .workflows.recommendation import attach_research

    req = normalize_request(req)
    bundle = req.analysis.bundle
    if bundle:
        cat = catalog_from_bundle(bundle)
        req = req.model_copy(update={"owned_product_ids": bundle.get("owned_ids") or [], "keep_product_ids": bundle.get("keep_ids") or []})
    else:
        cat = load()
    early = intake_check(cat, req)
    if early:
        return early
    directions = assemble.valid_directions(cat, req.analysis.plan_directions)
    cand_ids, _ = search_candidates(cat, req.conditions, directions)
    findings = reviews.sanitize_findings(cat, cand_ids, req.analysis.review_findings)
    result = assemble.build(cat, req, directions, findings, branch_status={"rerank": "OK"})
    result = attach_research(result, bundle)
    # 優先順位の変わった結果に、前の順位を前提にした説明を使い回さない。
    result, templated = finalize(cat, req, result, {})
    log_event("rerank", status=result.status, recommended=result.recommended_product_id, priorities=list(req.priorities),
              templated=templated, data_version=cat.data_version)
    return result


async def run_recommend(req: RecommendRequest) -> AsyncIterator[ProgressEvent | ResultEvent]:
    """説明の再生成と照合も含めてリクエスト全体の上限を適用する。"""
    stream = _run_recommend(req)
    try:
        async with asyncio.timeout(settings.request_timeout_sec):
            async for event in stream:
                yield event
    except TimeoutError:
        yield ResultEvent(result=_empty(load(), "HALTED", "調査の時間上限に達しました。条件を見直すか、時間をおいてもう一度お試しください。"))
    finally:
        await stream.aclose()
