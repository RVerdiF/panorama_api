#!/usr/bin/env bash
# Deploy do serviço Cloud Run — SOMENTE com autorização explícita do dono.
#
# Uso:
#   IMAGE=us-central1-docker.pkg.dev/panorama-escola-staging/panorama-api/api@sha256:... \
#   DATA_VERSION=<run de publicação> \
#   bash infra/cloud-run/deploy.sh
#
# O manifesto é a fonte única de min/max instances, concurrency e timeout;
# as guardas abaixo falham fechadas se alguém tentar furar a regra do dono.
set -euo pipefail

PROJECT="${GCP_PROJECT:-panorama-escola-staging}"
# Mesma região do dataset `panorama_serving` e do Artifact Registry (Tier 1).
REGION="us-central1"
IMAGE="${IMAGE:?defina IMAGE (referência completa no Artifact Registry)}"
DATA_VERSION="${DATA_VERSION:?defina DATA_VERSION (identificador do run de publicação)}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="$(mktemp)"
trap 'rm -f "$MANIFEST"' EXIT

sed -e "s|\${IMAGE}|${IMAGE}|g" -e "s|\${DATA_VERSION}|${DATA_VERSION}|g" \
    "$HERE/service.yaml" > "$MANIFEST"

# Nenhum placeholder pode sobrar: manifesto incompleto não vai para o Cloud Run.
if grep -q '\${' "$MANIFEST"; then
    echo "manifesto com placeholder não substituído:" >&2
    grep '\${' "$MANIFEST" >&2
    exit 1
fi

# Guardas da franquia gratuita: scale-to-zero obrigatório e no máximo 3 instâncias.
grep -q 'autoscaling.knative.dev/minScale: "0"' "$MANIFEST" || {
    echo "minScale != 0: o serviço não pode ficar quente (regra do dono)" >&2
    exit 1
}
MAX_SCALE="$(sed -n 's/.*autoscaling.knative.dev\/maxScale: "\([0-9][0-9]*\)".*/\1/p' "$MANIFEST")"
if [ -z "$MAX_SCALE" ] || [ "$MAX_SCALE" -gt 3 ]; then
    echo "maxScale ausente ou > 3 (valor: '${MAX_SCALE}'): regra do dono" >&2
    exit 1
fi

gcloud run services replace "$MANIFEST" --region "$REGION" --project "$PROJECT"
