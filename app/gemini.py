"""Vertex AIのGeminiを呼ぶクライアントと認証。

Cloud Runではサービスアカウント、手元ではgcloudの個人アカウントのトークンを使う。
手元のADC（application_default_credentials.json）は会社用のため読まない（futatakuと同じ方針）。
"""

import asyncio
import datetime
import json
import subprocess
import threading

import google.auth
import google.auth.credentials
from google import genai
from google.genai import types
from pydantic import BaseModel

from .config import check_project, on_cloud_run, settings
from .logging_utils import add_usage

_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


class GcloudCliCredentials(google.auth.credentials.Credentials):
    """`gcloud auth print-access-token --account=...` でトークンを取る認証情報。

    gcloudは手持ちのトークンが有効ならそれを返すため、残り時間は分からない。短い有効期限で取り直す。
    """

    def __init__(self, account: str):
        super().__init__()
        self._account = account
        self._lock = threading.Lock()

    def refresh(self, request) -> None:  # noqa: ARG002  google-authの規約に合わせた引数
        with self._lock:
            out = subprocess.run(
                ["gcloud", "auth", "print-access-token", f"--account={self._account}"],
                capture_output=True, text=True, check=True, timeout=30,
            )
            self.token = out.stdout.strip()
            # google-authは時刻をタイムゾーンなしのUTCで比べる
            self.expiry = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) + datetime.timedelta(minutes=5)


_credentials = None


def credentials() -> google.auth.credentials.Credentials:
    global _credentials
    if _credentials is None:
        if on_cloud_run():
            _credentials, _ = google.auth.default(scopes=_SCOPES)
        else:
            if not settings.gcloud_account:
                raise RuntimeError("SKINFIT_GCLOUD_ACCOUNT が未設定です。.env に個人のgcloudアカウントを書いてください")
            _credentials = GcloudCliCredentials(settings.gcloud_account)
    return _credentials


def client_kwargs() -> dict:
    """google-genaiのClient（ADKのGeminiモデルにも渡す）の共通設定。"""
    return {
        "vertexai": True,
        "project": check_project(),
        "location": settings.location,
        "credentials": credentials(),
    }


_clients: dict[int, genai.Client] = {}


def client() -> genai.Client:
    """イベントループごとにクライアントを持つ（閉じたループのクライアントを使い回さないため）。"""
    try:
        key = id(asyncio.get_running_loop())
    except RuntimeError:
        key = 0
    if key not in _clients:
        _clients[key] = genai.Client(**client_kwargs())
    return _clients[key]


def adk_model(task: str):
    """ADKのAgentに渡すGeminiモデル。認証は手元のADCではなく client_kwargs() を使う。"""
    from google.adk.models import Gemini

    return Gemini(model=settings.model, client_kwargs=client_kwargs())


def generate_config(task: str, schema: type[BaseModel] | None = None, system: str | None = None) -> types.GenerateContentConfig:
    kwargs: dict = {"thinking_config": types.ThinkingConfig(thinking_level=settings.thinking[task])}
    if schema is not None:
        kwargs["response_mime_type"] = "application/json"
        kwargs["response_schema"] = schema
    if system:
        kwargs["system_instruction"] = system
    return types.GenerateContentConfig(**kwargs)


async def generate_json(task: str, schema: type[BaseModel], contents, system: str | None = None) -> BaseModel:
    """構造化出力でGeminiを呼び、スキーマで検証した結果を返す。"""
    resp = await client().aio.models.generate_content(
        model=settings.model, contents=contents, config=generate_config(task, schema, system),
    )
    add_usage(resp)
    if resp.parsed is not None:
        return resp.parsed if isinstance(resp.parsed, schema) else schema.model_validate(resp.parsed)
    return schema.model_validate(json.loads(resp.text))
