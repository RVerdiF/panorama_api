#!/usr/bin/env bash
# Bootstrap do ambiente do repo (AGENTS.md §3.1). Idempotente.
set -euo pipefail

WORKSPACE="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$WORKSPACE"

if [ ! -x .venv/bin/python ]; then
    if command -v uv >/dev/null 2>&1; then
        uv venv .venv --python 3.11
    else
        python3 -m venv .venv
    fi
fi

if command -v uv >/dev/null 2>&1; then
    uv pip install --python .venv/bin/python -e ".[dev]"
else
    .venv/bin/python -m pip install --upgrade pip >/dev/null
    .venv/bin/python -m pip install -e ".[dev]"
fi

printf 'ambiente pronto: %s/.venv\n' "$WORKSPACE"
