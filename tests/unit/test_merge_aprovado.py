"""Guardas de scripts/merge_aprovado.sh — o merge nunca acontece em estado duvidoso.

Teste hermético: um `gh` falso no PATH devolve o estado do PR; nenhum acesso à
rede nem ao GitHub real. Cobre os quatro veredictos de guarda (exit 1/2/3) e o
caminho feliz em dry-run.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "merge_aprovado.sh"

FAKE_GH = """#!/usr/bin/env bash
# gh falso: responde `pr view --json ...` com o estado do fixture.
if [[ "$1 $2" == "pr view" ]]; then
  echo "{state} {mergeable} {merge_state} wt/fake"
  exit 0
fi
if [[ "$1 $2" == "pr merge" ]]; then
  echo "merge-called" >> "{log}"
  exit 0
fi
exit 1
"""


def run(tmp_path: Path, *args: str, state: str, mergeable: str, merge_state: str):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "merge.log"
    gh = bin_dir / "gh"
    gh.write_text(
        FAKE_GH.format(state=state, mergeable=mergeable, merge_state=merge_state, log=log)
    )
    gh.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    proc = subprocess.run(
        ["bash", str(SCRIPT), "42", *args],
        capture_output=True,
        text=True,
        env=env,
    )
    return proc, log


def test_pr_nao_aberto_recusa(tmp_path):
    proc, log = run(tmp_path, state="MERGED", mergeable="UNKNOWN", merge_state="UNKNOWN")
    assert proc.returncode == 1
    assert not log.exists()


def test_conflito_recusa(tmp_path):
    proc, log = run(tmp_path, state="OPEN", mergeable="CONFLICTING", merge_state="DIRTY")
    assert proc.returncode == 2
    assert "conflito" in proc.stderr
    assert not log.exists()


def test_branch_atras_da_main_recusa(tmp_path):
    proc, log = run(tmp_path, state="OPEN", mergeable="MERGEABLE", merge_state="BEHIND")
    assert proc.returncode == 3
    assert "changes_requested" in proc.stderr
    assert not log.exists()


def test_limpo_mergeia(tmp_path):
    proc, log = run(tmp_path, "--dry-run", state="OPEN", mergeable="MERGEABLE", merge_state="CLEAN")
    assert proc.returncode == 0, proc.stderr
    assert "MERGE_OK 42 wt/fake" in proc.stdout


def test_pr_invalido_nao_roda(tmp_path):
    proc = subprocess.run(
        ["bash", str(SCRIPT), "abc"], capture_output=True, text=True
    )
    assert proc.returncode == 64
