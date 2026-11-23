"""Guardas de scripts/merge_aprovado.sh — o merge nunca acontece em estado duvidoso.

Teste hermético: `gh` e `git` falsos no PATH, nenhum acesso à rede nem ao
GitHub real. Cobre as guardas (exit 1/2/3), o dry-run, o caminho REAL de merge
(prova que `gh pr merge` existe), exit 5 (merge commit fora da main) e uso
inválido (64).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "merge_aprovado.sh"

FAKE_GH = """#!/usr/bin/env bash
# gh falso: responde `pr view` com o estado do fixture e registra `pr merge`.
if [[ "$1 $2" == "pr view" ]]; then
  if [[ "$*" == *mergeCommit* ]]; then
    echo "{merge_sha}"
  else
    echo "{state} {mergeable} {merge_state} wt/fake"
  fi
  exit 0
fi
if [[ "$1 $2" == "pr merge" ]]; then
  echo "merge-called $3" >> "{log}"
  exit 0
fi
exit 1
"""

FAKE_GIT = """#!/usr/bin/env bash
# git falso: só o que o script usa antes da sanidade.
case "$1" in
  rev-parse) echo "{repo}"; exit 0 ;;
  fetch) exit 0 ;;
  merge-base) exit "${{FAKE_ANCESTOR_RC:-0}}" ;;
  worktree) exit 0 ;;
  *) exit 0 ;;
esac
"""


def run(
    tmp_path: Path,
    *args: str,
    state: str = "OPEN",
    mergeable: str = "MERGEABLE",
    merge_state: str = "CLEAN",
    merge_sha: str = "deadbeef",
    extra_env: dict | None = None,
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "merge.log"

    gh = bin_dir / "gh"
    gh.write_text(
        FAKE_GH.format(
            state=state,
            mergeable=mergeable,
            merge_state=merge_state,
            merge_sha=merge_sha,
            log=log,
        )
    )
    gh.chmod(0o755)

    git = bin_dir / "git"
    git.write_text(FAKE_GIT.format(repo=REPO))
    git.chmod(0o755)

    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", **(extra_env or {})}
    proc = subprocess.run(
        ["bash", str(SCRIPT), "42", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO,
    )
    return proc, log


def test_pr_nao_aberto_recusa(tmp_path):
    proc, log = run(tmp_path, state="MERGED", mergeable="UNKNOWN", merge_state="UNKNOWN")
    assert proc.returncode == 1
    assert not log.exists()


def test_conflito_recusa(tmp_path):
    proc, log = run(tmp_path, mergeable="CONFLICTING", merge_state="DIRTY")
    assert proc.returncode == 2
    assert "conflito" in proc.stderr
    assert not log.exists()


def test_branch_atras_da_main_recusa(tmp_path):
    proc, log = run(tmp_path, merge_state="BEHIND")
    assert proc.returncode == 3
    assert "changes_requested" in proc.stderr
    assert not log.exists()


def test_limpo_dry_run_nao_mergeia(tmp_path):
    proc, log = run(tmp_path, "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert "MERGE_OK 42 wt/fake" in proc.stdout
    assert not log.exists(), "dry-run não pode chamar gh pr merge"


def test_limpo_mergeia_de_verdade(tmp_path):
    """Caminho não-dry-run: se a chamada a `gh pr merge` sumir, este teste falha."""
    proc, log = run(tmp_path, "--skip-sanity")
    assert proc.returncode == 0, proc.stderr
    assert log.exists(), "gh pr merge não foi chamado"
    assert "merge-called 42" in log.read_text()
    assert "MERGED 42 deadbeef" in proc.stdout


def test_merge_commit_fora_da_main_falha(tmp_path):
    """merge-base responde 1 -> o script recusa com exit 5, nunca imprime MERGED."""
    proc, log = run(tmp_path, "--skip-sanity", extra_env={"FAKE_ANCESTOR_RC": "1"})
    assert proc.returncode == 5
    assert "MERGED" not in proc.stdout
    assert log.exists()  # o merge foi tentado; a verificação é que barrou depois


def test_pr_invalido_nao_roda(tmp_path):
    proc = subprocess.run(
        ["bash", str(SCRIPT), "abc"], capture_output=True, text=True, cwd=REPO
    )
    assert proc.returncode == 64
