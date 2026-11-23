#!/usr/bin/env bash
# Gate hermético local — é O gate de pré-merge deste repositório.
#
# GitHub Actions está DESABILITADO neste repo (decisão do dono) e não é o
# caminho: o gate hermético rodado localmente, via este script, é o passo
# obrigatório antes de abrir PR.
#
# O que o gate garante:
#   1. `pytest -m "not dataset and not integration and not plataforma and not controlled_integration"`
#      passa SEM data/, rede, BigQuery, Docker/GCP.
#   2. O checkout NÃO é alterado (git status --short antes == depois).
#
# Ambiente: o worker não pode contaminar o gate. `PYTHONPATH`/`PYTHONHOME`
# herdados apontando para outro site-packages quebram o venv; por isso são
# descartados aqui. O `.venv` é provisionado por `scripts/bootstrap_env.sh`.
#
# Interpretadores temporários do worker (`TMPDIR`/`TEMP`/`TMP`) são legítimos e
# NÃO são descartados: os testes usam `tempfile.gettempdir()`, não o literal /tmp.
#
# Uso:
#   bash scripts/test_hermetic.sh
#   PY=/caminho/venv/bin/python bash scripts/test_hermetic.sh   # venv já preparado
set -euo pipefail

unset PYTHONPATH PYTHONHOME

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

PY="${PY:-}"
if [ -z "$PY" ]; then
  echo "==> provisionando o .venv do repo (scripts/bootstrap_env.sh)"
  bash "$REPO/scripts/bootstrap_env.sh"
  PY="$REPO/.venv/bin/python"
elif [ ! -x "$PY" ]; then
  echo "ERRO: PY=$PY não é executável." >&2
  exit 2
fi

if "$PY" -c "import pip" >/dev/null 2>&1; then
  "$PY" -m pip check
fi

echo "==> snapshot do checkout antes (git status --short)"
STATUS_BEFORE="$(git status --short)"

echo "==> pytest hermético (sem dataset, rede, BigQuery ou GCP)"
"$PY" -m pytest -m "not dataset and not integration and not plataforma and not controlled_integration" -q

echo "==> verificando que o checkout NÃO foi sujado (antes == depois)"
STATUS_AFTER="$(git status --short)"
if [ "$STATUS_AFTER" != "$STATUS_BEFORE" ]; then
  echo "ERRO: o gate hermético alterou o checkout:" >&2
  git status --short >&2
  exit 3
fi

echo
echo "OK: gate hermético passou — suíte verde e checkout não alterado."
