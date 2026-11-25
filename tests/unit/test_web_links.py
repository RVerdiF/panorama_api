"""Hiperlinks entre telas do front `/app` (card `t_f1a156a0`).

Cobre os critérios de aceite sobre o HTML renderizado de verdade
(``TestClient`` + repositório fake, sem rede/BigQuery):

* busca → ficha da escola (nome é o link) e busca → mercado municipal
  (nome do município é o link);
* mercado → ficha da escola no ranking de share e mercado → busca filtrada
  pelo próprio município (`/app/?co_municipio=...`);
* escola → mercado municipal;
* **todos** os `href` internos das três telas respondem ``200`` — o teste
  percorre os links de verdade em vez de conferir um por um à mão;
* nome/município nulos continuam aparecendo como ``sem dado``, com link quando
  há chave para linkar.

O líder da comparação municipal **não** recebe link: `Competicao` expõe apenas
`lider_no_entidade`, não o `co_entidade` do líder (o card manda registrar isso).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import pytest

from tests.unit.conftest import (
    competidor_row,
    history_row,
    indicator_row,
    market_row,
    municipio_row,
    school_row,
    share_row,
)

BUSCA = "/app/"
MUNICIPIO = "3106200"
MERCADO = f"/app/mercados/{MUNICIPIO}"
ESCOLAS = f"{MERCADO}/escolas"
ESCOLA = "/app/escolas/31000001"
#: Qualquer `href` interno (o front nunca gera URL absoluta com host).
HREF_INTERNO = re.compile(r'href="(/app[^"]*)"')


def _html(response, status: int = 200) -> str:
    assert response.status_code == status, response.text[:600]
    assert response.headers["content-type"].startswith("text/html")
    return response.text


def _links_internos(html: str) -> list[str]:
    return HREF_INTERNO.findall(html)


def _hrefs_das_linhas_de_busca(html: str) -> dict[str, str]:
    """`{co_entidade: href}` a partir das células de código INEP da busca."""
    return {
        codigo: href
        for href, codigo in re.findall(
            r'<a href="(/app/escolas/[^"]+)">[^<]*</a>\s*</td>\s*<td><code>(\d+)</code>',
            html,
        )
    }


@pytest.fixture
def repo_links():
    """Repositório com uma escola em BH, mercado e share — tudo linkável.

    A série precisa declarar privada **ativa** (`tp_dependencia=4`,
    `tp_situacao_funcionamento=1`): é o que faz a tela consultar a comparação
    municipal — sem ela a seção do líder nem é renderizada.
    """
    from tests.unit.conftest import FakeRepository

    serie = [
        history_row(
            nu_ano_censo=2025, tp_dependencia="4", tp_situacao_funcionamento="1"
        )
    ]
    return FakeRepository(
        schools=[school_row()],
        history=serie,
        indicators=[indicator_row()],
        competidores=[competidor_row()],
        municipios=[municipio_row()],
        markets=[market_row()],
        share=[share_row()],
    )


@pytest.fixture
def client_links(repo_links, settings):
    from fastapi.testclient import TestClient

    from panorama_api.main import create_app

    with TestClient(create_app(settings=settings, repository=repo_links)) as test_client:
        yield test_client


# -- busca → escola / busca → mercado ----------------------------------------


def test_busca_linka_o_nome_da_escola_para_a_ficha(client_links):
    html = _html(client_links.get(BUSCA, params={"q": "modelo"}))

    assert f'<a href="{ESCOLA}">ESCOLA MODELO</a>' in html


def test_busca_mantem_o_codigo_inep_em_code_sem_link(client_links):
    html = _html(client_links.get(BUSCA, params={"q": "modelo"}))

    # O código INEP continua texto (não é o link): o nome é que é clicável.
    # Card V2: a tabela de 7 colunas não tem mais coluna própria de código — ele
    # acompanha o nome na célula da escola, ainda em `<code>`.
    assert "<code>31000001</code>" in html
    assert f'<a href="{ESCOLA}"><code>' not in html


def test_busca_linka_o_municipio_para_o_mercado(client_links):
    html = _html(client_links.get(BUSCA, params={"q": "modelo"}))

    assert f'<a href="{MERCADO}">BELO HORIZONTE</a>' in html
    # O código IBGE do município segue visível ao lado do link.
    assert f'<code>{MUNICIPIO}</code>' in html


def test_busca_com_nome_nulo_mostra_sem_dado_dentro_do_link(client_links, repo_links):
    repo_links.schools = [school_row(no_entidade=None)]

    # Filtra por município: `q` casaria com o nome, que aqui é nulo.
    html = _html(client_links.get(BUSCA, params={"co_municipio": MUNICIPIO}))

    assert f'<a href="{ESCOLA}">sem dado</a>' in html


def test_busca_com_municipio_nulo_mostra_sem_dado_sem_link_de_mercado(
    client_links, repo_links
):
    repo_links.schools = [school_row(co_municipio=None, no_municipio=None)]

    html = _html(client_links.get(BUSCA, params={"q": "modelo"}))

    # Sem `co_municipio` não existe destino: nada de link inventado.
    assert f"{MERCADO}" not in html
    assert "sem dado" in html


# -- mercado → escola / mercado → busca filtrada ------------------------------


def test_mercado_linka_o_nome_no_ranking_de_share(client_links):
    html = _html(client_links.get(ESCOLAS))

    assert f'<a href="{ESCOLA}">ESCOLA MODELO</a>' in html


def test_mercado_tem_link_para_a_busca_filtrada_do_municipio(client_links):
    html = _html(client_links.get(MERCADO))

    assert f'<a href="{BUSCA}?co_municipio={MUNICIPIO}">Ver escolas deste município</a>' in html


def test_mercado_com_nome_nulo_no_share_mostra_sem_dado_dentro_do_link(
    client_links, repo_links
):
    repo_links.share = [share_row(no_entidade=None)]

    html = _html(client_links.get(ESCOLAS))

    assert f'<a href="{ESCOLA}">sem dado</a>' in html


def test_mercado_sem_share_nao_inventa_linha_nem_link(client_links, repo_links):
    repo_links.share = []

    html = _html(client_links.get(ESCOLAS))

    assert f'href="{ESCOLA}"' not in html
    # O atalho de busca filtrada continua: é do município, não do share.
    assert f'href="{BUSCA}?co_municipio={MUNICIPIO}"' in html


# -- escola → mercado --------------------------------------------------------


def test_escola_linka_o_municipio_para_o_mercado(client_links):
    html = _html(client_links.get(ESCOLA))

    assert f'<a href="{MERCADO}">BELO HORIZONTE</a>' in html
    assert f"código IBGE <code>{MUNICIPIO}</code>" in html


def test_escola_sem_municipio_nao_gera_link_quebrado(client_links, repo_links):
    repo_links.history = [history_row(co_municipio=None, no_municipio=None)]

    html = _html(client_links.get(ESCOLA))

    assert f'href="{MERCADO}"' not in html
    assert "sem dado" in html


def test_lider_da_comparacao_municipal_continua_texto(client_links):
    """Sem `co_entidade` do líder no payload, linkar seria adivinhar por nome.

    Card V2: o líder do município aparece citado no KPI "Gap para o líder" —
    como texto, nunca como link (o `co_entidade` do líder não é publicado).
    """
    html = _html(client_links.get(f"{ESCOLA}/concorrencia"))

    achado = re.search(
        r'<p class="kpi__nota">(matrículas atrás de [^<]*)</p>', html, flags=re.S
    )
    assert achado is not None, "KPI de gap sem o líder citado"
    assert "ESCOLA LIDER" in achado.group(1)
    assert "href=" not in achado.group(1)


# -- crawl: todo `href` interno das telas responde 200 ----------------------


def _crawl(client, origem: str) -> list[tuple[str, int, str]]:
    """`(origem, status, destino)` para cada link interno — falhas primeiro."""
    html = _html(client.get(origem))
    resultados = []
    for destino in dict.fromkeys(_links_internos(html)):
        caminho = urlsplit(destino)
        url = caminho.path + (f"?{caminho.query}" if caminho.query else "")
        resposta = client.get(url)
        resultados.append((origem, resposta.status_code, destino))
    return resultados


def test_todos_os_links_internos_das_telas_respondem_200(client_links):
    falhas = [
        (origem, status, destino)
        for origem in (BUSCA + "?q=modelo", MERCADO, ESCOLAS, ESCOLA)
        for origem, status, destino in _crawl(client_links, origem)
        if status != 200
    ]

    assert falhas == [], f"links internos quebrados: {falhas}"


def test_a_busca_gera_link_de_escola_e_de_mercado_que_existem(client_links):
    """Sanidade do crawl: ele precisa ter percorrido os dois tipos de destino."""
    destinos = {
        destino
        for _, _, destino in _crawl(client_links, BUSCA + "?q=modelo")
    }

    assert ESCOLA in destinos
    assert MERCADO in destinos
