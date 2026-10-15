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

gcloud run deploy skinfit --source . --project "$PROJECT" --region "$REGION" \
  --service-account "$SA" \
  --allow-unauthenticated --max-instances 2 --memory 1Gi --timeout 300 \
  --set-env-vars "SKINFIT_GCP_PROJECT=$PROJECT,SKINFIT_VERTEX_LOCATION=global,SKINFIT_GEMINI_MODEL=gemini-4-argon"

gcloud run services describe skinfit --project "$PROJECT" --region "$REGION" --format="value(status.url)"
