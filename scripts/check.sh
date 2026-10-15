#!/bin/sh
# 提出前・デプロイ前の検査。1つでも落ちたら止まる（deploy.sh はこれを通らないとデプロイしない）
set -e
cd "$(dirname "$0")/.." || exit 1

echo "== 1. テスト一式（本番データにダミーが残っていないかの検査を含む）"
uv run pytest -q -p no:cacheprovider

echo "== 2. 画面の差し込みの無害化漏れ"
uv run python scripts/check_frontend_escape.py

echo "== 3. 秘密情報がリポジトリに入っていないか"
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo ".env がGitの管理対象になっています。外してください"; exit 1
fi
PATTERN='BEGIN (RSA |EC )?PRIVATE KEY|AIza[0-9A-Za-z_-]{30,}|"private_key"'
if git grep -nIE "$PATTERN" -- . ':!scripts/check.sh' >/dev/null 2>&1; then
  echo "秘密鍵やAPIキーらしき文字列があります:"; git grep -nIE "$PATTERN" -- . ':!scripts/check.sh'; exit 1
fi
ACCOUNT="$(gcloud config get-value account 2>/dev/null || true)"
if [ -n "$ACCOUNT" ] && git grep -nIF "$ACCOUNT" -- . >/dev/null 2>&1; then
  echo "個人のアカウント名がリポジトリに入っています:"; git grep -nIF "$ACCOUNT" -- .; exit 1
fi
# 商品写真のAPIキー（Yahoo!・楽天）は形式が決まっていないため、.env に書いた値そのものを探す（値は表示しない）
for KEY in SKINFIT_YAHOO_CLIENT_ID SKINFIT_RAKUTEN_APP_ID SKINFIT_RAKUTEN_ACCESS_KEY; do
  VALUE="$(sed -n "s/^$KEY=//p" .env 2>/dev/null | head -n 1)"
  if [ -n "$VALUE" ] && git grep -qIF "$VALUE" -- . 2>/dev/null; then
    echo "$KEY の値がリポジトリに入っています。外してください"; exit 1
  fi
done
echo "秘密情報：見つかりませんでした"

echo "== 4. 画面のJavaScriptの構文"
node --check web/app.js

echo "== すべての検査に通りました"
