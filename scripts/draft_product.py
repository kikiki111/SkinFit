"""公式ページのURLから、登録データ（data/products.json）の製品の下書きを作る。

使い方: uv run python scripts/draft_product.py --url <公式ページのURL> --role owned|candidate [--category lotion] [--alias 別の書き方 ...]

- ページは人が選んだURLをPythonが直接取得する。Google検索連携は使わない（検索連携の結果は規約で保存できないため）
- 本文の構造化は、その場の調査と同じ処理（research._structure・research._facts_to_product）を使う。
  本文に無い成分・価格・効能表示は落ちる。構造化のGeminiには検索ツールを付けない
- 画像はダウンロードせず、ページの og:image のURLだけを持つ（公式ECは複製を禁じているため）
- 下書きは data/drafts/pending/ に書く。人が公式ページと見比べて確かめたら、drafts/owned.json か candidates.json の
  配列へ移し、scripts/merge_data.py で取り込む。この移動を「人の確認」とする
"""

import argparse
import asyncio
import datetime
import hashlib
import html
import json
import re
import sys
from pathlib import Path
from typing import get_args
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import research  # noqa: E402
from app.catalog import GROUNDING_REDIRECT_HOST  # noqa: E402
from app.media import product_key  # noqa: E402
from app.schemas import Category, Product, ProductMedia, Source  # noqa: E402

PENDING = ROOT / "data" / "drafts" / "pending"
MAX_TEXT = 30000
USER_AGENT = "Mozilla/5.0 (compatible; SkinFit-draft/0.1)"


def check_url(url: str) -> str:
    """人が選んだ公式ページだけを受け付ける。検索連携の転送URLは使わない。"""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("https の公式ページのURLを指定してください")
    if parsed.hostname == GROUNDING_REDIRECT_HOST:
        raise ValueError("Google検索連携の転送URLは使えません。公式ページのURLを直接指定してください")
    return url


def fetch_page(url: str) -> tuple[str, str]:
    with httpx.Client(follow_redirects=True, timeout=15, headers={"User-Agent": USER_AGENT}) as client:
        resp = client.get(check_url(url))
    resp.raise_for_status()
    return check_url(str(resp.url)), resp.text


def _meta(page: str, prop: str) -> str | None:
    for tag in re.findall(r"<meta\b[^>]*>", page, flags=re.I):
        attrs = dict((k.lower(), v) for k, _, v in re.findall(r'([\w:-]+)\s*=\s*(["\'])(.*?)\2', tag, flags=re.S))
        if (attrs.get("property") or attrs.get("name") or "").lower() == prop and attrs.get("content"):
            return html.unescape(attrs["content"]).strip()
    return None


def parse_page(page: str) -> tuple[str, str | None, str | None]:
    """本文テキスト（行ごと）、ページ題名、og:image を取り出す。"""
    title = _meta(page, "og:title")
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", page, flags=re.I | re.S)
        title = html.unescape(m.group(1)).strip() if m else None
    body = re.sub(r"<(script|style|noscript|svg)\b.*?</\1>", " ", page, flags=re.I | re.S)
    body = re.sub(r"<br\s*/?>|</(p|div|li|tr|h\d|dt|dd|section|table)>", "\n", body, flags=re.I)
    body = html.unescape(re.sub(r"<[^>]+>", " ", body))
    lines = [re.sub(r"[ \t　]+", " ", line).strip() for line in body.splitlines()]
    text = "\n".join(line for line in lines if line)[:MAX_TEXT]
    return text, title, _meta(page, "og:image")


def _grounded_like(text: str, url: str, title: str | None) -> research.GroundedResult:
    """公式ページ1件を出典 S1 として、その場の調査と同じ構造化に渡す形にする（検索はしていない）。"""
    host = urlparse(url).hostname or url
    today = datetime.date.today().isoformat()
    annotated = "\n".join(f"{line} [S1]" for line in text.splitlines())
    return research.GroundedResult(text=text, annotated=annotated, queries=[], entry_point_html=None,
                                   sources=[Source(source_id="S1", url=url, title=title or host, publisher=host, checked_at=today)])


async def draft(url: str, role: str, category: str | None, aliases: list[str]) -> Product:
    final_url, page = fetch_page(url)
    text, title, image = parse_page(page)
    if not text:
        raise ValueError("ページの本文を読み取れませんでした")
    g = _grounded_like(text, final_url, title)
    f = await research._structure(research._FactsOut, g, "この製品の事実を構造化してください。本文はメーカー公式ページです。")
    key = product_key(f.brand, f.name or title or final_url)
    pid = "reg_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
    p = research._facts_to_product(f, g, pid, role, {"name": title, "category": category})
    today = datetime.date.today().isoformat()
    p.searched_as = None
    p.data_version = f"registered-{today}"
    p.category = category or p.category
    p.name_aliases = list(dict.fromkeys(a for a in aliases if a.strip()))
    if p.price_jpy_tax_included:
        p.price_note = "公式ページの表示価格"
    for u in p.unknown:
        u.reason = u.reason.replace("検索", "公式ページ")
    if image:
        try:
            p.media = ProductMedia(src=urljoin(final_url, image), source_url=final_url, credit=f"{p.brand} 公式サイト".strip(),
                                   provider="registered", checked_at=today)
        except ValidationError:
            pass  # https でない画像は持たない
    return p


def summary(p: Product, path: Path) -> str:
    claims = [f"  - {c.text}（{c.type}）" for c in p.claims]
    unknown = [f"  - {u.field}：{u.reason}" for u in p.unknown]
    return "\n".join([
        f"下書き: {path}",
        f"製品: {p.brand} {p.name}（{p.category} / {p.role}）",
        f"全成分: {len(p.ingredients_full or [])}成分（{'全体を確認' if p.ingredients_complete else '一部だけ'}）",
        f"価格: {'税込' + format(p.price_jpy_tax_included, ',') + '円' if p.price_jpy_tax_included else '確認できず'}",
        "効能表示:", *(claims or ["  - なし"]),
        "確認できなかった項目:", *(unknown or ["  - なし"]),
        f"画像: {p.media.src if p.media else 'なし'}",
        f"別の書き方: {'、'.join(p.name_aliases) or 'なし'}",
        "",
        "次の手順: 公式ページと見比べて内容を確かめ、data/drafts/owned.json か candidates.json の配列へ移してから、"
        "uv run python scripts/merge_data.py を実行してください。",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="公式ページのURLから登録データの下書きを作る（Google検索連携は使わない）")
    parser.add_argument("--url", required=True, help="メーカー公式の製品ページ（https）")
    parser.add_argument("--role", required=True, choices=["owned", "candidate"], help="手持ちとして登録するか、候補として登録するか")
    parser.add_argument("--category", choices=list(get_args(Category)), help="製品の種類。省略すると本文から判断する")
    parser.add_argument("--alias", action="append", default=[], help="写真や手入力で使われそうな別の書き方（何度でも指定できる）")
    args = parser.parse_args(argv)
    try:
        p = asyncio.run(draft(args.url, args.role, args.category, args.alias))
    except (ValueError, httpx.HTTPError) as e:
        print(f"下書きを作れませんでした: {e}")
        return 1
    PENDING.mkdir(parents=True, exist_ok=True)
    path = PENDING / f"{p.product_id}.json"
    path.write_text(json.dumps(p.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(summary(p, path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
