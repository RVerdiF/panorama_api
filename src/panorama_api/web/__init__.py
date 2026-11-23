"""Front SSR (`/app`) servido pelo próprio `panorama_api` (decisão D1 = A).

Pacote fechado em si: router, templates Jinja2, assets com hash de conteúdo e
as páginas de erro HTML. As regras de exibição do plano (seção 1) moram em
`filters.py`/`conteudo.py` — fonte única para todas as telas.
"""

from __future__ import annotations

__all__ = ["PREFIXO_WEB"]

#: Prefixo público do front. Registrado em `main.create_app` sob este prefixo e
#: usado para decidir se um erro vira página HTML ou `application/problem+json`.
PREFIXO_WEB = "/app"
