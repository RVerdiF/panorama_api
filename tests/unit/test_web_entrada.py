"""Entrada do sistema `/app` — card `t_0c84b91f`.

Cobre, sobre o HTML renderizado de verdade (``TestClient`` + repositório fake,
nenhuma rede/BigQuery), os achados do relatório `avaliacao-ui.md` que este card
fecha:

* A1 — `GET /` responde `307` para `/app/` (antes era 404 em
  ``application/problem+json``), e `/v1/*`/`/health` continuam intactos;
* A2/A3 — `/app/` sem consulta orienta (o que é, recorte MG, anos de
  `APP_ANOS_DISPONIVEIS`, fonte INEP) e **não** mostra "sem dado" do bloco
  "Recorte da busca", que só aparece depois de uma consulta;
* A5 — o logo do topo é link para `/app/`;
* B7 — `aria-current="page"` na tela ativa e breadcrumb com links em escola e
  mercado;
* D3 — `<title>` do mercado traz o nome do município.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.core.http_cache import HttpCacheMiddleware
from panorama_api.main import create_app
from panorama_api.web import PREFIXO_WEB
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

ANOS = (2021, 2022, 2023, 2024, 2025)
BUSCA = f"{PREFIXO_WEB}/"
METODOLOGIA = f"{PREFIXO_WEB}/metodologia"
MUNICIPIO = "3106200"
MERCADO = f"{PREFIXO_WEB}/mercados/{MUNICIPIO}"
ESCOLA = f"{PREFIXO_WEB}/escolas/31000001"


def _settings(*, anos: str = ",".join(str(ano) for ano in ANOS)) -> Settings:
    return Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        max_bytes_billed=256 * 1024 * 1024,
        validate_schema_on_startup=False,
        contract_version="mvp-1",
        data_version="dev",
        app_anos_disponiveis=anos,
    )


@pytest.fixture
def entrada_repo() -> FakeRepository:
    """Repositório fake com uma escola, uma série e um mercado completo."""
    return FakeRepository(
        municipios=[municipio_row()],
        schools=[school_row()],
        history=[history_row(nu_ano_censo=ano) for ano in ANOS],
        indicators=[indicator_row(nu_ano_censo=2025)],
        competidores=[competidor_row(nu_ano_censo=2025)],
        markets=[market_row(nu_ano_censo=ano, etapa="bas") for ano in ANOS],
        share=[share_row(nu_ano_censo=ano) for ano in ANOS],
    )


@pytest.fixture
def cliente(entrada_repo: FakeRepository) -> TestClient:
    app = create_app(settings=_settings(), repository=entrada_repo)
    with TestClient(app) as test_client:
        yield test_client


def _limpar_cache_de_paginas(cliente: TestClient) -> None:
    """Esvazia o LRU das páginas `/app` (a chave não inclui o repositório)."""
    pilha = cliente.app.middleware_stack
    while pilha is not None:
        if isinstance(pilha, HttpCacheMiddleware) and pilha.prefix == PREFIXO_WEB and pilha.pagina:
            pilha.cache.clear()
            return
        pilha = getattr(pilha, "app", None)
    raise AssertionError("cache de páginas /app não encontrado no stack")


def _get(cliente: TestClient, caminho: str, **kwargs):
    _limpar_cache_de_paginas(cliente)
    return cliente.request("GET", caminho, **kwargs)


# -- A1: raiz do serviço ------------------------------------------------------


def test_raiz_redireciona_para_o_front_com_307(cliente: TestClient):
    # `follow_redirects=False`: o `TestClient` segue redirect por padrão e o
    # teste precisa ver a resposta 307, não a página final.
    resposta = _get(cliente, "/", follow_redirects=False)

    assert resposta.status_code == 307
    assert resposta.headers["location"] == BUSCA
    # Redirect não carrega corpo: quem chega em `/` não vê JSON de erro nenhum.
    assert resposta.content == b""


def test_raiz_responde_head_com_o_mesmo_redirect(cliente: TestClient):
    """`curl -I /` (HEAD) recebe o redirect, não 405.

    O `FastAPI` não deriva `HEAD` do `GET`: sem a rota explícita, o critério de
    aceite (`curl -sI /`) via 405 com `application/problem+json`.
    """
    resposta = cliente.request("HEAD", "/", follow_redirects=False)

    assert resposta.status_code == 307
    assert resposta.headers["location"] == BUSCA


def test_raiz_nao_entra_no_openapi(cliente: TestClient):
    """A raiz é conveniência de entrada, não parte do contrato `/v1`."""
    schema = cliente.get("/openapi.json").json()

    assert "/" not in schema["paths"]
    assert not [caminho for caminho in schema["paths"] if caminho.startswith(PREFIXO_WEB)]


def test_health_continua_json_intacto(cliente: TestClient):
    resposta = cliente.get("/health")

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("application/json")


# -- A2/A3: bloco de orientação e "Recorte da busca" -------------------------


def test_busca_sem_consulta_orienta_sobre_o_produto(cliente: TestClient):
    html = _get(cliente, BUSCA).text

    assert "Minas Gerais" in html
    assert "INEP" in html
    # Os anos publicados vêm de APP_ANOS_DISPONIVEIS, nunca de literal no template.
    for ano in ANOS:
        assert str(ano) in html
    assert f'href="{METODOLOGIA}"' in html
    # Atalhos do bloco de orientação: âncora para o formulário, âncora para o
    # campo de município e a metodologia.
    assert 'href="#formulario-busca"' in html
    assert 'id="formulario-busca"' in html
    assert 'href="#co_municipio"' in html
    assert 'id="co_municipio"' in html


def test_busca_sem_consulta_nao_mostra_sem_dado(cliente: TestClient):
    html = _get(cliente, BUSCA).text

    assert "sem dado" not in html.lower()
    # O bloco de recorte só faz sentido depois de uma consulta.
    assert "Recorte da busca" not in html


def test_busca_com_consulta_volta_a_mostrar_o_recorte(cliente: TestClient):
    html = _get(cliente, BUSCA, params={"co_municipio": MUNICIPIO}).text

    assert "Recorte da busca" in html
    assert "Ano de referência" in html


def test_busca_usa_os_anos_do_setting_nao_um_literal(entrada_repo: FakeRepository):
    """Dois settings diferentes → cada página anuncia o próprio recorte."""
    app = create_app(settings=_settings(anos="2024,2025"), repository=entrada_repo)
    with TestClient(app) as cliente:
        html = _get(cliente, BUSCA).text

    assert "2024" in html and "2025" in html
    assert "2021" not in html


# -- A5: logo e B7: aria-current --------------------------------------------


def test_logo_do_topo_e_link_para_o_front(cliente: TestClient):
    html = _get(cliente, BUSCA).text

    assert re.search(r'<a class="topo__marca" href="/app/">Panorama Escola</a>', html)


def test_aria_current_marca_a_tela_ativa(cliente: TestClient):
    busca = _get(cliente, BUSCA).text
    metodologia = _get(cliente, METODOLOGIA).text

    assert 'aria-current="page"' in busca
    assert 'aria-current="page"' in metodologia
    # Uma única tela ativa por página: o link de busca não se marca na metodologia.
    assert busca.count('aria-current="page"') == 1
    assert metodologia.count('aria-current="page"') == 1
    assert 'aria-current="page" href="/app/metodologia"' not in busca
    assert 'aria-current="page" href="/app/"' not in metodologia


# -- B7: breadcrumb com links ------------------------------------------------


def test_escola_tem_breadcrumb_com_link_para_o_mercado(cliente: TestClient):
    html = _get(cliente, ESCOLA).text

    assert 'aria-label="breadcrumb"' in html
    assert f'href="{MERCADO}"' in html
    assert f'href="{BUSCA}"' in html


def test_mercado_tem_breadcrumb_para_a_busca(cliente: TestClient):
    html = _get(cliente, MERCADO).text

    assert 'aria-label="breadcrumb"' in html
    assert f'href="{BUSCA}"' in html


# -- D3: título do mercado ---------------------------------------------------


def test_titulo_do_mercado_traz_o_municipio(cliente: TestClient):
    html = _get(cliente, MERCADO).text

    titulo = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    assert titulo is not None
    # O nome vem da resposta (`Market.no_municipio`), com a caixa que a base
    # usar — o fixture devolve `BELO HORIZONTE`, o BigQuery real devolve
    # `Belo Horizonte`. O contrato é o nome estar no título, não a caixa.
    assert "belo horizonte" in titulo.group(1).lower()


def test_titulo_do_mercado_sem_nome_cai_no_codigo(cliente: TestClient, entrada_repo):
    # `no_municipio` vem da `dim_geografia`; sem nome publicado, o código IBGE
    # é a única identificação disponível para a aba.
    entrada_repo.municipios = [municipio_row(no_municipio=None)]

    html = _get(cliente, MERCADO).text

    titulo = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    assert titulo is not None
    assert MUNICIPIO in titulo.group(1)
