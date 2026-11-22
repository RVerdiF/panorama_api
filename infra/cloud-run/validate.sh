#!/usr/bin/env bash
# Renderiza o manifesto do serviço (sem placeholders) e valida contra a API do
# Cloud Run. SOMENTE VALIDAÇÃO: `--dry-run` não cria nem altera nada.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
OUT="${1:-$HERE/service.rendered.yaml}"

sed -e "s|\${IMAGE}|us-central1-docker.pkg.dev/panorama-escola-staging/panorama-api/api:dry-run|g" \
    -e "s|\${DATA_VERSION}|dry-run|g" \
    "$REPO_ROOT/infra/cloud-run/service.yaml" > "$OUT"

if grep -q '\${' "$OUT"; then
    echo "placeholder não substituído:" >&2
    grep '\${' "$OUT" >&2
    exit 1
fi

echo "manifesto renderizado: $OUT"
gcloud run services replace "$OUT" \
    --region us-central1 \
    --project panorama-escola-staging \
    --dry-run
