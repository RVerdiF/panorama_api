"""O script de estrutura roda dentro do gate hermético (critério 1, V2).

`scripts/comparar_paineis.py` extrai os `<h2>` das 3 telas e compara com o
cânone do protótipo. Sem este teste, nada no `pytest` o executava — o script
existia, mas o gate não o cobria (rodada 1 da revisão, item 6).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _carregar_script():
    raiz = Path(__file__).resolve().parents[2]
    caminho = raiz / "scripts" / "comparar_paineis.py"
    spec = importlib.util.spec_from_file_location("comparar_paineis", caminho)
    assert spec is not None and spec.loader is not None, caminho
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_comparar_paineis_passa_no_modo_hermetico() -> None:
    """O cânone V2 (h2 em ordem + `div.kpis` com 4 filhos) vale no hermético."""

    comparar_paineis = _carregar_script()

    assert comparar_paineis.main([]) == 0
