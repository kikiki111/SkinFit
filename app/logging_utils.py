"""構造化ログ。標準出力へJSONで出す（Cloud Run上ではCloud Loggingに入る）。

相談の全文・写真・口コミ投稿者の情報・モデルの内部思考は出さない。
"""

import contextvars
import json
import logging
import sys
import time

# 推薦1回分のログをつなぐ識別子と、AI・検索の使用量。非同期のタスクにも引き継がれる
run_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("run_id", default=None)
usage_var: contextvars.ContextVar[dict | None] = contextvars.ContextVar("usage", default=None)

_logger = logging.getLogger("skinfit")
if not _logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_h)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False


def log_event(event: str, severity: str = "INFO", **fields) -> None:
    run_id = run_id_var.get()
    extra = {"run_id": run_id} if run_id and "run_id" not in fields else {}
    _logger.info(json.dumps({"severity": severity, "event": event, "ts": round(time.time(), 3), **extra, **fields},
                            ensure_ascii=False, default=str))


def start_usage() -> dict:
    usage = {"gemini_calls": 0, "search_calls": 0, "search_queries": 0, "input_tokens": 0, "output_tokens": 0,
             "thought_tokens": 0, "hedged_calls": 0, "retried_searches": 0}
    usage_var.set(usage)
    return usage


def add_usage(resp=None, *, search_queries: int = 0, search: bool = False, **counters) -> None:
    """Geminiの応答の usage_metadata と検索回数を、この推薦の使用量に足す。"""
    usage = usage_var.get()
    if usage is None:
        return
    usage["gemini_calls"] += 1 if resp is not None else 0
    usage["search_calls"] += 1 if search else 0
    usage["search_queries"] += search_queries
    meta = getattr(resp, "usage_metadata", None) if resp is not None else None
    if meta is not None:
        usage["input_tokens"] += (meta.prompt_token_count or 0) + (getattr(meta, "tool_use_prompt_token_count", 0) or 0)
        usage["output_tokens"] += meta.candidates_token_count or 0
        usage["thought_tokens"] += getattr(meta, "thoughts_token_count", 0) or 0
    for k, v in counters.items():
        usage[k] = usage.get(k, 0) + v


# Gemini 4 Argon（global）の単価。2026-11-30までの販促価格（Pickoryの記録、2026-10-14確認）。検索の課金は含めない（未確認）
PRICE_PER_M_INPUT_USD = 2.0
PRICE_PER_M_OUTPUT_USD = 10.0  # 思考トークンを含む


def estimate_cost_usd(usage: dict) -> float:
    return round(usage["input_tokens"] / 1e6 * PRICE_PER_M_INPUT_USD
                 + (usage["output_tokens"] + usage["thought_tokens"]) / 1e6 * PRICE_PER_M_OUTPUT_USD, 4)
