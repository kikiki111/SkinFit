"""設定値。モデルIDと場所はここだけに書く。値は環境変数（手元では .env）で上書きできる。"""

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """手元用の .env を読む。既に設定された環境変数は上書きしない。"""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    # GOOGLE_CLOUD_PROJECT はシェルに会社の値が入っていることがあるため、専用の変数名を使う
    project: str = os.environ.get("SKINFIT_GCP_PROJECT", "winged-vigil-384014")
    # Vertex AIの場所。Gemini 4 Argonは global / us / eu だけで、Cloud Runのリージョンとは別の値になる
    location: str = os.environ.get("SKINFIT_VERTEX_LOCATION", "global")
    model: str = os.environ.get("SKINFIT_GEMINI_MODEL", "gemini-4-argon")
    # 手元でトークンを取るgcloudのアカウント。手元のADCは会社用のため読まない
    gcloud_account: str = os.environ.get("SKINFIT_GCLOUD_ACCOUNT", "")
    # 処理ごとの思考の深さ。Gemini 4 Argonは LOW / MEDIUM / HIGH（MINIMALは400エラー）
    thinking: dict = field(default_factory=lambda: {
        "inventory": os.environ.get("SKINFIT_THINKING_INVENTORY", "LOW"),
        "intake": os.environ.get("SKINFIT_THINKING_INTAKE", "LOW"),
        "reviews": os.environ.get("SKINFIT_THINKING_REVIEWS", "LOW"),
        "planner": os.environ.get("SKINFIT_THINKING_PLANNER", "MEDIUM"),
        "explain": os.environ.get("SKINFIT_THINKING_EXPLAIN", "LOW"),
        "research": os.environ.get("SKINFIT_THINKING_RESEARCH", "LOW"),
        "structure": os.environ.get("SKINFIT_THINKING_STRUCTURE", "LOW"),
    })
    # live: その場でGoogle検索して調べる（失敗時は登録済みの候補で代替） / catalog: 登録済みの候補だけ
    research_mode: str = os.environ.get("SKINFIT_RESEARCH_MODE", "live")
    research_timeout_sec: float = float(os.environ.get("SKINFIT_RESEARCH_TIMEOUT_SEC", "75"))
    hedge_after_sec: float = float(os.environ.get("SKINFIT_HEDGE_AFTER_SEC", "20"))  # これを過ぎたら同じ検索をもう1本出す
    max_live_candidates: int = 3
    request_timeout_sec: float = float(os.environ.get("SKINFIT_REQUEST_TIMEOUT_SEC", "270"))
    max_explain_retries: int = 2
    # 利用回数の制限（公開URLでの費用の暴走を防ぐ）
    recommend_per_client: int = int(os.environ.get("SKINFIT_RECOMMEND_PER_CLIENT", "5"))
    light_per_client: int = int(os.environ.get("SKINFIT_LIGHT_PER_CLIENT", "30"))  # 条件の整理・写真の読み取り
    rate_window_sec: int = int(os.environ.get("SKINFIT_RATE_WINDOW_SEC", "600"))
    max_concurrent_recommends: int = int(os.environ.get("SKINFIT_MAX_CONCURRENT_RECOMMENDS", "3"))
    daily_recommend_limit: int = int(os.environ.get("SKINFIT_DAILY_RECOMMEND_LIMIT", "150"))
    max_upload_bytes: int = 7 * 1024 * 1024  # Gemini 4 Argonのインライン1ファイル上限
    data_dir: Path = ROOT / "data"
    web_dir: Path = ROOT / "web"


settings = Settings()

COMPANY_PROJECTS = {"qumoa-genai-02-project"}


def check_project() -> str:
    """呼び出し先のプロジェクトを確かめる。会社のプロジェクトなら止める。"""
    if settings.project in COMPANY_PROJECTS:
        raise SystemExit(f"{settings.project} は会社のプロジェクトのため使えません。SKINFIT_GCP_PROJECT を確認してください")
    return settings.project


def on_cloud_run() -> bool:
    return bool(os.environ.get("K_SERVICE"))  # Cloud Runが設定する環境変数
