#!/bin/sh
# デプロイ前に1回だけ行うGCPの準備。済んでいる手順は飛ばすので、何度実行しても結果は同じ
# GCPへの書き込みなので、実行前に必ず承認を得ること
set -e
cd "$(dirname "$0")/.." || exit 1
# 会社のアカウントで操作しないよう、.env に書いた個人のgcloudアカウントに固定する
ACCOUNT="$(sed -n "s/^SKINFIT_GCLOUD_ACCOUNT=//p" .env 2>/dev/null | head -n 1)"
[ -n "$ACCOUNT" ] && export CLOUDSDK_CORE_ACCOUNT="$ACCOUNT"
PROJECT="${SKINFIT_GCP_PROJECT:-winged-vigil-384014}"
SA_NAME="skinfit-run"
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

# ソースからのデプロイは Cloud Build でコンテナを作る。有効済みなら何もしない
gcloud services enable cloudbuild.googleapis.com --project "$PROJECT"

# Cloud Run で動くときの身元。Vertex AIを呼ぶ権限だけを持たせる
if ! gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT" --display-name "SkinFit Cloud Run"
fi
# 作ったばかりのSAは、IAMに反映されるまで「存在しない」と返されることがあるため、10秒おきに6回まで試す
TRY=1
until gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" \
        --role roles/aiplatform.user --condition=None --format=none; do
  [ "$TRY" -ge 6 ] && { echo "権限の付与に失敗しました（$SA）"; exit 1; }
  echo "SAの反映を待って再試行します（$TRY/6）"; TRY=$((TRY + 1)); sleep 10
done

# 商品写真のAPIキーを使うときだけ、追加で次を行う（deploy.sh がシークレットの有無を見て渡す）
#   gcloud services enable secretmanager.googleapis.com
#   skinfit-yahoo-client-id / skinfit-rakuten-app-id / skinfit-rakuten-access-key を作り、
#   $SA に roles/secretmanager.secretAccessor を付ける

echo "GCPの準備が済みました（$PROJECT）"
