#!/bin/sh
# Cloud Run へのデプロイ。check.sh の検査に通らなければデプロイしない
# GCPへの書き込みなので、実行前に必ず承認を得ること
set -e
cd "$(dirname "$0")/.." || exit 1
PROJECT="${SKINFIT_GCP_PROJECT:-winged-vigil-384014}"
REGION="${SKINFIT_RUN_REGION:-asia-northeast1}"
# Vertex AIを呼ぶ権限（roles/aiplatform.user）だけを持つ専用SA。既定のCompute SAは権限が広いため使わない
SA="skinfit-run@${PROJECT}.iam.gserviceaccount.com"

./scripts/check.sh

# 商品写真を探す公式API（Yahoo!・楽天）のキーは Secret Manager から渡す。無ければ写真探しを無効のままデプロイする
# シークレットの作成と、$SA への roles/secretmanager.secretAccessor の付与は、GCPへの書き込みなので事前に承認を得ること
SECRETS=""
for PAIR in SKINFIT_YAHOO_CLIENT_ID=skinfit-yahoo-client-id SKINFIT_RAKUTEN_APP_ID=skinfit-rakuten-app-id \
            SKINFIT_RAKUTEN_ACCESS_KEY=skinfit-rakuten-access-key; do
  NAME="${PAIR#*=}"
  if gcloud secrets describe "$NAME" --project "$PROJECT" >/dev/null 2>&1; then
    SECRETS="${SECRETS:+$SECRETS,}${PAIR%%=*}=$NAME:latest"
  else
    echo "Secret Manager に $NAME が無いため、この値なしでデプロイします"
  fi
done

gcloud run deploy skinfit --source . --project "$PROJECT" --region "$REGION" \
  --service-account "$SA" \
  --allow-unauthenticated --max-instances 2 --memory 1Gi --timeout 300 \
  --set-env-vars "SKINFIT_GCP_PROJECT=$PROJECT,SKINFIT_VERTEX_LOCATION=global,SKINFIT_GEMINI_MODEL=gemini-4-argon" \
  ${SECRETS:+"--set-secrets=$SECRETS"}

gcloud run services describe skinfit --project "$PROJECT" --region "$REGION" --format="value(status.url)"
