"""画面作り用のスタブ。tests/fixtures/api_examples.json の例を返す（Geminiを呼ばない）。

起動: uv run uvicorn app.stub:app --port 8090
"""

import asyncio
import json
from typing import Literal
from .preview import build_preview
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT, settings

app = FastAPI(title="SkinFit stub")
FIXTURE = ROOT / "tests" / "fixtures" / "api_examples.json"


def _example(name: str):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))[name]
    if isinstance(data, dict) and data.get("status") == "RECOMMENDATION_READY":
        # 保存時点の古い配置ルールを画面確認に持ち込まない。
        from .catalog import catalog_from_bundle
        from .media import media_for
        from .routine import current_routine, simulate_routine

        bundle = data.get("analysis", {}).get("bundle")
        if bundle:
            cat = catalog_from_bundle(bundle)
            ids, keep = bundle.get("owned_ids", []), bundle.get("keep_ids", [])
            plans = [current_routine(cat, ids)]
            plans += [simulate_routine(cat, ids, keep, c["product_id"]) for c in data["candidates"]]
            data["routines"] = [p.model_dump() for p in plans]
        for candidate in data["candidates"]:
            candidate["media"] = media_for(candidate["brand"], candidate["name"])
    return data


@app.get("/api/preview")
def preview(priority: Literal["concern", "light"] = "concern"):
    return build_preview(priority)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "stub": True}


@app.get("/api/catalog")
def catalog() -> dict:
    return _example("catalog")


@app.post("/api/intake/parse")
def intake(body: dict) -> dict:
    return _example("intake")


@app.post("/api/inventory/extract")
async def inventory(image: UploadFile = File(...)) -> dict:
    return _example("inventory")


@app.post("/api/recommend")
async def recommend(body: dict) -> StreamingResponse:
    async def lines():
        for ev in _example("recommend_progress_live"):
            yield json.dumps(ev, ensure_ascii=False) + "\n"
            await asyncio.sleep(0.3)
        yield json.dumps({"type": "result", "result": _example("recommend_result_live")}, ensure_ascii=False) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@app.post("/api/rerank")
def rerank(body: dict) -> dict:
    if body.get("priorities", [None])[0] == "stickiness":
        return _example("rerank_result_live")
    return _example("recommend_result_live")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(Path(settings.web_dir) / "index.html")


app.mount("/", StaticFiles(directory=settings.web_dir), name="web")
