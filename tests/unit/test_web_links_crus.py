"""Trava de links sem estilo (card V4-L, plano `v4-delta.md` §3).

`panorama.css` não tem regra para `a` solto — só `.menu a`, `.trilha a`,
`.subnav a`, `.ranking__nome a` (mais `table.tabela .nome-escola`,
`.acao-tabela` e `.botao`, que exigem classe no próprio link). Link sem
classe fora desses contêineres cai no azul/roxo padrão do browser.

A trava renderiza as rotas da varredura do plano e falha se algum `<a>`
aparecer **sem** `class` e **sem** ancestral estilizado. A allowlist começa
com `comparar.html` (P7, sem protótipo) e `inicio.html` (do D2-E3) e segue a
mesma regra de `PENDENTES` em `test_classes_prototipo.py`: **só encolhe**.
"""

from __future__ import annotations

from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.main import create_app
from tests.unit.conftest import (
    FakeRepository,
    competidor_row,
    history_row,
    indicator_row,
    market_row,
    municipio_row,
    school_row,
    share_row,
)

#: Páginas cuja exceção é decidida no plano (não neste teste): `inicio.html`
#: é do D2-E3 e `comparar.html` está fora do escopo (P7). Só encolhe.
ALLOWLIST = frozenset({"inicio", "comparar"})

#: Contêineres cujo seletor `X a` existe em `panorama.css` (plano §3): o link
#: sem classe herda estilo dali e não é cru.
ANCESTRAIS_ESTILIZADOS = frozenset({"menu", "trilha", "subnav", "ranking__nome"})


class _LeitorDeLinks(HTMLParser):
    """Coleta os `<a>` sem `class` fora de ancestral estilizado."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._pilha: list[set[str]] = []
        self.crus: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        atributos = dict(attrs)
        if tag == "a":
            tem_classe = bool((atributos.get("class") or "").strip())
            sob_estilo = any(
                classes & ANCESTRAIS_ESTILIZADOS for classes in self._pilha
            )
            if not tem_classe and not sob_estilo:
                self.crus.append(
                    f"<a href={atributos.get('href')!r}> na linha {self.getpos()}"
                )
        self._pilha.append(set((atributos.get("class") or "").split()))

    def handle_endtag(self, tag: str) -> None:
        if self._pilha:
            self._pilha.pop()


def links_crus(html: str) -> list[str]:
    """`<a>` sem `class` e sem ancestral estilizado no HTML renderizado."""
    leitor = _LeitorDeLinks()
    leitor.feed(html)
    leitor.close()
    return leitor.crus


def _settings() -> Settings:
    return Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        max_bytes_billed=256 * 1024 * 1024,
        validate_schema_on_startup=False,
        contract_version="mvp-1",
        data_version="dev",
        app_anos_disponiveis="2021,2022,2023,2024,2025",
    )


@pytest.fixture
def client_lint():
    serie = [
        history_row(
            nu_ano_censo=2025, tp_dependencia="4", tp_situacao_funcionamento="1"
        )
    ]
    repo = FakeRepository(
        schools=[school_row()],
        history=serie,
        indicators=[indicator_row()],
        competidores=[competidor_row()],
        municipios=[municipio_row()],
        markets=[market_row()],
        share=[share_row()],
    )
    with TestClient(create_app(settings=_settings(), repository=repo)) as cliente:
        yield cliente


#: `(nome lógico, caminho, params, status)`. `inicio` e `comparar` estão na
#: allowlist: renderizam para provar 200, mas a varredura não vale para elas.
PAGINAS = [
    ("inicio", "/", None, 200),
    ("busca-inicial", "/app/", None, 200),
    ("busca-com-resultado", "/app/", {"q": "modelo"}, 200),
    ("busca-sem-resultado", "/app/", {"q": "zzzqqqww"}, 200),
    ("ficha", "/app/escolas/31000001", None, 200),
    ("concorrencia", "/app/escolas/31000001/concorrencia", None, 200),
    ("mercado", "/app/mercados/3106200", None, 200),
    ("indice", "/app/mercados/", None, 200),
    ("metodologia", "/app/metodologia", None, 200),
    ("erro-404", "/app/escolas/99999999", None, 404),
    ("erro-422", "/app/escolas/abc", None, 422),
    ("comparar", "/app/comparar", {"escolas": "31000001"}, 200),
]


def _html(cliente: TestClient, caminho: str, params: dict | None, status: int) -> str:
    resposta = cliente.get(caminho, params=params)
    assert resposta.status_code == status, resposta.text[:600]
    assert resposta.headers["content-type"].startswith("text/html")
    return resposta.text


def test_nenhum_link_cru_fora_da_allowlist(client_lint):
    crus_por_pagina = {}
    for nome, caminho, params, status in PAGINAS:
        if nome in ALLOWLIST:
            _html(client_lint, caminho, params, status)
            continue
        crus = links_crus(_html(client_lint, caminho, params, status))
        if crus:
            crus_por_pagina[nome] = crus

    assert crus_por_pagina == {}, f"links sem estilo: {crus_por_pagina}"


def test_detector_acusa_link_sem_classe_fora_de_ancestral():
    """Prova viva da trava (critério 3): `<a>` cru é reportado; com classe
    ou dentro de `.trilha`, não."""
    html = (
        '<p class="trilha"><a href="/app/mercados/3106200">BH</a></p>'
        '<p><a href="/app/comparar?escolas=1">Comparar</a></p>'
        '<p><a class="botao" href="/x">Ok</a></p>'
    )

    crus = links_crus(html)

    assert len(crus) == 1
    assert "comparar" in crus[0]
