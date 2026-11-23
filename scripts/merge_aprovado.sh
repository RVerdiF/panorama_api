#!/usr/bin/env bash
# Integra um PR aprovado no review limpo (veredito final APPROVED).
#
# Uso:
#   scripts/merge_aprovado.sh <numero-do-pr> [--dry-run] [--skip-sanity]
#
# Guardas (falha fechado, nunca mergeia em estado duvidoso):
#   1 PR não existe / não está OPEN        -> exit 1
#   2 PR não é MERGEABLE (conflito)        -> exit 2
#   3 mergeStateStatus != CLEAN (BEHIND,
#     DIRTY, UNSTABLE, BLOCKED...)         -> exit 3
#   4 suíte hermética falhou após o merge  -> exit 4  (regressão pós-merge)
#
# Saída: imprime o merge commit e a linha de trilha para registrar no card.
set -euo pipefail

PR="${1:-}"
DRY_RUN=0
SKIP_SANITY=0
shift || true
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --skip-sanity) SKIP_SANITY=1 ;;
    *) echo "argumento desconhecido: $arg" >&2; exit 64 ;;
  esac
done

if [[ ! "$PR" =~ ^[0-9]+$ ]]; then
  echo "uso: $0 <numero-do-pr> [--dry-run] [--skip-sanity]" >&2
  exit 64
fi

info() { printf '%s\n' "$*" >&2; }

# --- 1..3: estado do PR -----------------------------------------------------
read -r STATE MERGEABLE MERGE_STATE HEAD < <(
  gh pr view "$PR" --json state,mergeable,mergeStateStatus,headRefName \
    --jq '"\(.state) \(.mergeable) \(.mergeStateStatus) \(.headRefName)"'
)

info "PR #$PR: state=$STATE mergeable=$MERGEABLE mergeState=$MERGE_STATE head=$HEAD"

[[ "$STATE" == "OPEN" ]] || { info "recusado: PR não está OPEN ($STATE)"; exit 1; }
[[ "$MERGEABLE" == "MERGEABLE" ]] || { info "recusado: conflito (mergeable=$MERGEABLE)"; exit 2; }
[[ "$MERGE_STATE" == "CLEAN" ]] || {
  info "recusado: estado de merge $MERGE_STATE (rebase/ajuste necessário) -> changes_requested"
  exit 3
}

if (( DRY_RUN )); then
  info "dry-run: mergearia PR #$PR (head=$HEAD) na main"
  echo "MERGE_OK $PR $HEAD"
  exit 0
fi

# --- merge ------------------------------------------------------------------
gh pr merge "$PR" --merge
MERGE_SHA=$(gh pr view "$PR" --json mergeCommit --jq '.mergeCommit.oid')
info "merge commit: $MERGE_SHA"

git fetch origin --quiet
git merge-base --is-ancestor "$MERGE_SHA" origin/main || {
  info "erro: merge commit $MERGE_SHA não está em origin/main"
  exit 5
}

# --- sanidade pós-merge (§10 do AGENTS.md) ----------------------------------
if (( ! SKIP_SANITY )); then
  WT=$(mktemp -d "${TMPDIR:-/tmp}/sanity-main-XXXXXX")
  trap 'git worktree remove --force "$WT" >/dev/null 2>&1 || true; rm -rf "$WT"' EXIT
  git worktree add --detach "$WT" origin/main --quiet
  PY="$WT/.venv/bin/python"
  if [[ ! -x "$PY" ]]; then
    bash "$WT/scripts/bootstrap_env.sh" >/dev/null 2>&1 || true
    PY="$WT/.venv/bin/python"
  fi
  if [[ -x "$PY" ]] && ( cd "$WT" && "$PY" -m pytest -q -m "not dataset and not integration and not plataforma and not controlled_integration" ); then
    info "sanidade pós-merge: OK"
  else
    info "sanidade pós-merge: FALHOU na main — hotfix obrigatório"
    exit 4
  fi
fi

echo "MERGED $PR $MERGE_SHA"
