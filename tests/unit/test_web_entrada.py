"""Entrada do sistema `/` e front `/app` — cards `t_0c84b91f` e `t_386b791c`.

Cobre, sobre o HTML renderizado de verdade (``TestClient`` + repositório fake,
nenhuma rede/BigQuery):

* A1 — `GET /` responde ``200`` com a **página de entrada** em HTML (o redirect
  ``307`` → `/app/` saiu no card `t_386b791c`), `HEAD /` também responde ``200``,
  a página sai com gzip, ``ETag``/`private, no-cache` com ``304``, gera a linha
  `page_view` (prova em `test_web_observabilidade.py`), não consulta o
  repositório e um erro inesperado nela vira página HTML — e `/v1/*`/`/health`
  continuam intactos;
* A2/A3 — `/app/` sem consulta orienta (o que é, recorte MG, anos de
  `APP_ANOS_DISPONIVEIS`, fonte INEP) e **não** mostra "sem dado" do bloco
  "Recorte da busca", que só aparece depois de uma consulta;
* A5 — o logo do topo é link para a entrada `/`;
* B7 — `aria-current="page"` na tela ativa e breadcrumb com links em escola e
  mercado;
* D3 — `<title>` do mercado traz o nome do município.
"""

from __future__ import annotations

import re

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.core.http_cache import HttpCacheMiddleware
from panorama_api.main import create_app
from panorama_api.web import PREFIXO_WEB
from panorama_api.web import routes as web_routes
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
INICIO = "/"
BUSCA = f"{PREFIXO_WEB}/"
METODOLOGIA = f"{PREFIXO_WEB}/metodologia"
MUNICIPIO = "3106200"
MERCADO = f"{PREFIXO_WEB}/mercados/{MUNICIPIO}"
ESCOLA = f"{PREFIXO_WEB}/escolas/31000001"
TITULO_INICIO = (
    "Panorama Escola — escolas e mercados da educação básica em Minas Gerais"
)


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


# -- A1: a raiz é a página de entrada (landing) ------------------------------


def test_raiz_responde_a_landing_em_html(cliente: TestClient):
    resposta = _get(cliente, INICIO)

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/html")
    # Não é mais redirect: o corpo é a página, não um `Location`.
    assert "location" not in resposta.headers
    html = resposta.text
    assert "<h1>Escolas e mercados da educação básica em Minas Gerais</h1>" in html
    # A busca continua em `/app/`, e é para lá que a landing leva — desde o card
    # `t_e075a6f6` pelo formulário GET do hero, não por um link textual.
    assert re.search(r'<form class="hero__busca" method="get" action="/app/"', html)


def test_raiz_responde_head_com_a_pagina(cliente: TestClient):
    """`curl -I /` (HEAD) recebe 200, não 405.

    O `FastAPI` só deriva `HEAD` de um `GET` que declare `methods` explicitamente;
    a rota da landing declara `GET` e `HEAD` justamente para isso.
    """
    resposta = cliente.request("HEAD", INICIO)

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/html")


def test_raiz_nao_entra_no_openapi(cliente: TestClient):
    """A raiz é entrada do sistema, não parte do contrato `/v1`."""
    schema = cliente.get("/openapi.json").json()

    assert INICIO not in schema["paths"]
    assert not [caminho for caminho in schema["paths"] if caminho.startswith(PREFIXO_WEB)]


def test_raiz_tem_o_titulo_da_landing(cliente: TestClient):
    html = _get(cliente, INICIO).text

    titulo = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    assert titulo is not None
    assert titulo.group(1) == TITULO_INICIO


def test_raiz_usa_o_shell_com_um_unico_h1_e_landmarks(cliente: TestClient):
    html = _get(cliente, INICIO).text

    assert html.count("<h1") == 1
    assert '<header class="topo">' in html
    assert '<main id="conteudo"' in html
    assert '<footer class="rodape">' in html
    # A landing não exibe valor nenhum: a nota de ausência do rodapé sairia como
    # ruído (mesma regra da 1ª visita da busca, achado A3). A copy da seção de
    # fonte (card `t_2c2e564b`) fala de "sem dado" — a asserção é sobre a nota
    # do rodapé, não sobre a expressão em qualquer lugar da página.
    assert "Esta página nunca troca dado ausente por zero" not in html


def test_raiz_sai_comprimida_com_gzip(cliente: TestClient):
    """`/` entra no gzip do front; o `/v1` continua sem compressão."""
    resposta = _get(cliente, INICIO, headers={"Accept-Encoding": "gzip"})

    assert resposta.status_code == 200
    # `TestClient` descomprime o corpo; o header prova que houve compressão.
    assert resposta.headers.get("content-encoding") == "gzip"


def test_raiz_tem_etag_e_cache_privado_com_304(cliente: TestClient):
    primeira = _get(cliente, INICIO)

    assert primeira.status_code == 200
    assert primeira.headers["cache-control"] == "private, no-cache"
    etag = primeira.headers["etag"]

    # Revalidação responde 304 antes do handler (sem re-renderizar a página).
    segunda = cliente.get(INICIO, headers={"If-None-Match": etag})

    assert segunda.status_code == 304
    assert segunda.headers["etag"] == etag


def test_erro_inesperado_na_raiz_vira_pagina_html(
    entrada_repo: FakeRepository, monkeypatch: pytest.MonkeyPatch
):
    """Erro em `/` é página HTML do front, nunca `application/problem+json`."""
    app = create_app(settings=_settings(), repository=entrada_repo)
    ambiente = web_routes.templates()
    render_original = ambiente.TemplateResponse

    def _render_quebrado(request: Request, nome: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        # A landing estoura ao renderizar; `erro.html` continua funcionando — é
        # isso que prova a conversão do erro inesperado em página HTML.
        if nome == "inicio.html":
            raise RuntimeError("boom na landing")
        return render_original(request, nome, *args, **kwargs)

    monkeypatch.setattr(ambiente, "TemplateResponse", _render_quebrado)

    with TestClient(app, raise_server_exceptions=False) as test_client:
        resposta = test_client.request(
            "GET", INICIO, headers={"Accept-Encoding": "identity"}
        )

    assert resposta.status_code == 500
    assert resposta.headers["content-type"].startswith("text/html")
    assert "application/problem+json" not in resposta.headers["content-type"]
    assert "erro interno" in resposta.text.lower()
    assert "boom na landing" not in resposta.text


def test_raiz_nao_consulta_o_repositorio(entrada_repo: FakeRepository):
    app = create_app(settings=_settings(), repository=entrada_repo)
    with TestClient(app) as test_client:
        entrada_repo.calls.clear()
        test_client.request("GET", INICIO)
        test_client.request("HEAD", INICIO)

    assert entrada_repo.calls == []


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
    # O bloco de orientação encolheu no card `t_2c2e564b`: fica o parágrafo e o
    # link para a landing. Os três atalhos de uso moraram para `/`, que agora
    # apresenta o produto; `/app/` segue como porta de entrada por deep-link.
    assert '<a href="/">Sobre o Panorama Escola</a>' in html
    assert "orientacao__atalhos" not in html
    assert 'href="#formulario-busca"' not in html
    assert 'href="#co_municipio"' not in html
    # Os alvos continuam no formulário, para os fluxos que os usam.
    assert 'id="formulario-busca"' in html
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


def test_logo_do_topo_e_link_para_a_entrada(cliente: TestClient):
    """O logo volta para a landing `/`, não direto para a busca (A5)."""
    for caminho in (INICIO, BUSCA, METODOLOGIA):
        html = _get(cliente, caminho).text

        assert re.search(r'<a class="topo__marca" href="/">Panorama Escola</a>', html)


def test_aria_current_marca_a_tela_ativa(cliente: TestClient):
    """Um item — e só um — recebe `aria-current` em cada página (spec §2.1)."""
    busca = _get(cliente, BUSCA).text
    metodologia = _get(cliente, METODOLOGIA).text

    # A busca é a tela de nível 1 "Escolas": `page` no link da área.
    assert '<a href="/app/" aria-current="page">Escolas</a>' in busca
    assert busca.count('aria-current="page"') == 1
    # Metodologia é disclosure: o item ativo é o `<summary>` do submenu.
    assert '<summary aria-current="page">Metodologia</summary>' in metodologia
    assert metodologia.count('aria-current="page"') == 1
    # Os itens não ativos não marcam nada (nem `page`, nem `true`).
    assert '<a href="/app/mercados/" aria-current' not in busca
    assert '<summary aria-current' not in busca
    assert '<a href="/app/" aria-current' not in metodologia
    assert '<a href="/app/mercados/" aria-current' not in metodologia
    assert 'aria-current="true"' not in busca
    assert 'aria-current="true"' not in metodologia


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
