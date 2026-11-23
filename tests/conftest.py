"""Bootstrap do ambiente dos testes (vale para toda a suíte).

`panorama_api.main` monta o app no import (`app = create_app()`), então um
setting obrigatório sem valor no ambiente quebraria a **coleta** de todos os
testes antes de qualquer fixture rodar. `APP_ANOS_DISPONIVEIS` (card F5) é
obrigatório por decisão de contrato: um deploy sem ele falha no boot, e
`tests/unit/test_infra_config.py` verifica exatamente isso.

Aqui só há um valor padrão de ambiente, igual ao do manifesto
(`infra/cloud-run/service.yaml`); testes que precisam de outro recorte passam
o valor explicitamente em `Settings(...)` ou com `monkeypatch.setenv`.
"""

from __future__ import annotations

import os

#: Valor padrão de ambiente para os testes herméticos (`setdefault`: um valor
#: já exportado pelo processo tem precedência).
os.environ.setdefault("APP_ANOS_DISPONIVEIS", "2021,2022,2023,2024,2025")
