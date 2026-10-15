"""SkinFitのAPIと画面。画面は web/ をそのまま配る（手元とCloud Runで同じ起動コマンド）。"""

import json
from typing import Literal
from .preview import build_preview
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import guard, orchestrator
from .catalog import load
from .config import check_project, settings
from .logging_utils import log_event
from .schemas import (concern_id_for, CatalogResponse, IntakeRequest, IntakeResponse, InventoryResponse, ProductSummary,
                      RecommendationResult, RecommendRequest, RerankRequest)
from .workflows import agents, inventory

@asynccontextmanager
async def lifespan(_app):
    cat = load()
    log_event("startup", project=check_project(), model=settings.model, location=settings.location,
              data_version=cat.data_version, uses_dummy=cat.uses_dummy, research_mode=settings.research_mode)
    yield


app = FastAPI(title="SkinFit", lifespan=lifespan)
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/heic", "image/heif", "image/webp"}


@app.exception_handler(RequestValidationError)
async def _validation_error(request, exc):  # 受け取った本文はログにも応答にも含めない
    log_event("bad_request", severity="WARNING", path=request.url.path, errors=len(exc.errors()))
    return JSONResponse(status_code=422, content={"detail": "入力の形式が正しくありません"})


@app.get("/api/preview")
def preview(priority: Literal["concern", "light"] = "concern"):
    return build_preview(priority)


@app.get("/api/health")
def health() -> dict:
    cat = load()
    return {"ok": True, "model": settings.model, "location": settings.location, "data_version": cat.data_version,
            "uses_dummy_data": cat.uses_dummy}


@app.get("/api/catalog", response_model=CatalogResponse)
def catalog() -> CatalogResponse:
    cat = load()
    return CatalogResponse(
        owned_candidates=[ProductSummary(product_id=p.product_id, brand=p.brand, name=p.name, category=p.category,
                                         role=p.role, is_dummy=p.is_dummy) for p in cat.owned_candidates()],
        data_version=cat.data_version,
    )


@app.post("/api/intake/parse", response_model=IntakeResponse)
async def intake(body: IntakeRequest, request: Request) -> IntakeResponse:
    guard.check_rate(request, "light")
    try:
        out = await agents.parse_intake(body.text)
    except Exception as e:  # noqa: BLE001
        log_event("intake", severity="ERROR", error=type(e).__name__)
        raise HTTPException(status_code=502, detail="条件の整理に失敗しました。もう一度試すか、フォームに直接入力してください") from e
    conditions, questions = out.conditions, list(out.follow_up_questions)
    # 悩みは本人の言葉のまま。区分（小じわ / それ以外）だけPythonで決める
    conditions.concern = concern_id_for(conditions.concern_label)
    if not conditions.concern:
        questions = ["優先する悩みを1つ教えてください（例：小じわ、毛穴の目立ち）。"] + [q for q in questions if "悩み" not in q]
    log_event("intake", ok=True, follow_ups=len(questions))
    return IntakeResponse(conditions=conditions, follow_up_questions=questions[:2])


@app.post("/api/inventory/extract", response_model=InventoryResponse)
async def inventory_extract(request: Request, image: UploadFile = File(...)) -> InventoryResponse:
    guard.check_rate(request, "light")
    mime = (image.content_type or "").lower()
    if mime not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="JPEG・PNG・HEICの画像を選んでください")
    data = await image.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="画像が大きすぎます（7MBまで）")
    try:
        result = await inventory.extract(data, mime)
    except Exception as e:  # noqa: BLE001
        log_event("inventory", severity="ERROR", error=type(e).__name__)
        raise HTTPException(status_code=502, detail="写真の読み取りに失敗しました。一覧から選んでください") from e
    log_event("inventory", detections=len(result.detections), bytes=len(data))
    return result


@app.post("/api/recommend")
async def recommend(body: RecommendRequest, request: Request) -> StreamingResponse:
    guard.check_rate(request, "recommend")
    if not guard.try_acquire_recommend_slot():
        raise HTTPException(status_code=429, detail="ただいま混み合っています。1〜2分ほど待ってから試してください")
    try:
        guard.check_daily()
    except HTTPException:
        guard.release_recommend_slot()
        raise

    async def lines():
        try:
            async for ev in orchestrator.run_recommend(body):
                yield json.dumps(ev.model_dump(), ensure_ascii=False) + "\n"
        finally:
            guard.release_recommend_slot()

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@app.post("/api/rerank", response_model=RecommendationResult)
def rerank(body: RerankRequest, request: Request) -> RecommendationResult:
    guard.check_rate(request, "light")
    try:
        return orchestrator.run_rerank(body)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail="比較データを読み取れませんでした。条件からもう一度調査してください。") from exc


@app.get("/")
def index() -> FileResponse:
    return FileResponse(Path(settings.web_dir) / "index.html")


app.mount("/", StaticFiles(directory=settings.web_dir), name="web")
