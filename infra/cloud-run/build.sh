#!/usr/bin/env bash
# Dispara o build da imagem da API no Cloud Build (`cloudbuild.yaml`) e imprime a
# referência publicada no Artifact Registry. Decisão D1 do card `t_cab24513`.
#
# Uso (da raiz do repo):
#   bash infra/cloud-run/build.sh                 # SHA curto do HEAD
#   TAG=manual-1 bash infra/cloud-run/build.sh    # tag explícita
#
# É uma ação em GCP (consome a franquia de 120 min/dia do Cloud Build) e por isso
# só roda com autorização do dono — o card registra a execução real.
set -euo pipefail

PROJECT="${GCP_PROJECT:-panorama-escola-staging}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG="${REPO_ROOT}/cloudbuild.yaml"

# Identidade do build: a SA de CI/CD do projeto (Terraform do repo
# `panorama_escola`), que é a única com `roles/cloudbuild.builds.builder` em
# staging. A SA default (`…-compute`) não tem o papel e falha com 403 no upload
# do source — por isso a flag é obrigatória aqui, não opcional.
BUILD_SA_EMAIL="${BUILD_SA_EMAIL:-panorama-data-build@${PROJECT}.iam.gserviceaccount.com}"

TAG="${TAG:-$(git -C "$REPO_ROOT" rev-parse --short=7 HEAD)}"
IMAGE="${AR_HOST:-us-central1-docker.pkg.dev}/${PROJECT}/${AR_REPOSITORY:-panorama-api}/api"

echo "projeto: $PROJECT"
echo "tag:     $TAG"
echo "imagem:  ${IMAGE}:${TAG}"
echo "build SA: ${BUILD_SA_EMAIL}"

# Falha fechado: sem tag, o build gravaria ':latest' de forma ambígua.
if [ -z "$TAG" ]; then
    echo "TAG vazia: defina TAG=... ou rode dentro do repo git" >&2
    exit 1
fi

gcloud builds submit "$REPO_ROOT" \
    --config "$CONFIG" \
    --project "$PROJECT" \
    --service-account "projects/${PROJECT}/serviceAccounts/${BUILD_SA_EMAIL}" \
    --substitutions="_TAG=${TAG}"

echo "--- imagens publicadas ---"
gcloud artifacts docker images list "${IMAGE}" \
    --project "$PROJECT" \
    --include-tags \
    --format="table(version,tags,create_time)"
echo
echo "referência para o deploy:"
echo "  ${IMAGE}:${TAG}"
