#!/usr/bin/env bash
# Cria (idempotente) o repositório Docker da imagem da API no Artifact Registry e
# aplica a política de limpeza. Decisão D1 do card `t_cab24513`.
#
# Uso (do repo, na raiz):
#   bash infra/artifact-registry/ensure.sh          # só mostra o plano
#   bash infra/artifact-registry/ensure.sh --yes    # cria/aplica em staging
#
# Regra do dono: franquia de 0,5 GB → manter apenas as 3 tags mais recentes.
# Ação em GCP exige autorização explícita do dono; por isso o `--yes`.
set -euo pipefail

PROJECT="${GCP_PROJECT:-panorama-escola-staging}"
LOCATION="us-central1"
REPOSITORY="panorama-api"
POLICY_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/cleanup-policy.json"

CONFIRMED=0
for arg in "$@"; do
    case "$arg" in
        --yes) CONFIRMED=1 ;;
        *) echo "argumento desconhecido: $arg" >&2; exit 2 ;;
    esac
done

echo "projeto:    $PROJECT"
echo "região:     $LOCATION"
echo "repositório: $REPOSITORY (docker)"
echo "política:   $POLICY_FILE"

if gcloud artifacts repositories describe "$REPOSITORY" \
    --location="$LOCATION" --project="$PROJECT" >/dev/null 2>&1; then
    echo "estado: repositório já existe"
else
    echo "estado: repositório ausente"
fi

if [ "$CONFIRMED" -ne 1 ]; then
    echo "dry-run: nada foi alterado (use --yes para aplicar)" >&2
    exit 0
fi

if ! gcloud artifacts repositories describe "$REPOSITORY" \
    --location="$LOCATION" --project="$PROJECT" >/dev/null 2>&1; then
    gcloud artifacts repositories create "$REPOSITORY" \
        --repository-format=docker \
        --location="$LOCATION" \
        --description="Imagem da API do Panorama Escola" \
        --project="$PROJECT"
fi

gcloud artifacts repositories set-cleanup-policies "$REPOSITORY" \
    --policy="$POLICY_FILE" \
    --location="$LOCATION" \
    --project="$PROJECT"

gcloud artifacts repositories describe "$REPOSITORY" \
    --location="$LOCATION" --project="$PROJECT"
