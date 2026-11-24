"""Front SSR servido pelo próprio `panorama_api` (decisão D1 = A).

Pacote fechado em si: router, templates Jinja2, assets com hash de conteúdo e
as páginas de erro HTML. As regras de exibição do plano (seção 1) moram em
`filters.py`/`conteudo.py` — fonte única para todas as telas.

Duas superfícies públicas pertencem ao front: a busca sob ``/app`` e a página
de entrada em ``/`` (card `t_386b791c`). Quem precisa decidir "isto é página do
front?" — erro HTML, gzip, linha `page_view` e cache de página — usa
:func:`e_caminho_web`, nunca uma comparação local com o prefixo.
"""

from __future__ import annotations

__all__ = ["CAMINHO_INICIO", "PREFIXO_WEB", "e_caminho_web"]

#: Prefixo público do front. Registrado em `main.create_app` sob este prefixo e
#: usado para decidir se um erro vira página HTML ou `application/problem+json`.
PREFIXO_WEB = "/app"

#: Página de entrada (landing). Fica na raiz, fora do prefixo da busca: `/app/`
#: continua sendo a busca e nenhuma URL existente muda.
CAMINHO_INICIO = "/"


def e_caminho_web(caminho: str) -> bool:
    """Diz se ``caminho`` é página do front (HTML), e não contrato `/v1`.

    São do front a raiz **exata** (``/``) e ``/app`` com seus segmentos
    (``/app`` e ``/app/...``). O casamento é por segmento: ``/apple``,
    ``/app-x`` e ``/appfoo`` não são páginas do front, como já valia antes do
    card `t_386b791c`.

    ``/v1`` e ``/health`` não pertencem ao front: continuam em
    ``application/problem+json``, sem gzip e sem os headers de cache de página.
    """
    if caminho == CAMINHO_INICIO:
        return True
    return caminho == PREFIXO_WEB or caminho.startswith(PREFIXO_WEB + "/")
