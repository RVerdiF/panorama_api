"""Visão geral do mercado `/app/mercados/{co_municipio}` (cards F5 e NAV-3).

Cobre os critérios de aceite da tela sobre o HTML renderizado de verdade
(``TestClient`` + repositório fake, nenhuma rede/BigQuery):

* a abertura consulta **só** `dados.mercado` (3 chamadas) e **nunca** o share —
  o ranking de share vive em `/app/mercados/{co_municipio}/escolas` (NAV-3);
* ``ANO_FORA_DO_CONTRATO`` → ``404`` **com** seletor de outro ano;
* ``offset`` não é recorte desta rota → ``422`` sem consultar o repositório;
* a composição é consultada sem recorte de etapa; a etapa do seletor vale para
  cobertura, entrada/saída e denominadores;
* ``null`` de entrada/saída no primeiro ano da série → "sem dado";
* sem HHI/C4 (decisão D4) e sem vocabulário geográfico proibido;
* recorte obrigatório: ano, etapa, ``meta.universo``, ``meta.fonte``, avisos;
* subnav do mercado com o recorte atual, sem ``offset``, e a seção ativa em
  ``aria-current="page"``; revalidação ``If-None-Match`` → 304 sem consulta.

Os testes do ranking de share que viviam aqui foram **movidos** para
`tests/unit/test_web_mercado_escolas.py` (não apagados): é a rota que agora os
renderiza.
"""

from __future__ import annotations

import re
from html import unescape as desescapar

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.main import create_app
from panorama_api.web.conteudo import MOTIVO_ENTRADA_SAIDA
from tests.unit.conftest import (
    FakeRepository,
    concentracao_row,
    market_row,
    municipio_row,
    share_row,
)

MUNICIPIO = "3106200"
MERCADO = f"/app/mercados/{MUNICIPIO}"
ESCOLAS = f"{MERCADO}/escolas"
#: Anos do seletor usados nos testes.
ANOS = (2021, 2022, 2023, 2024, 2025)
#: Termos proibidos como vocabulário de comparação geográfica (escopo-adiado-v1).
TERMOS_PROIBIDOS = ("raio", "próximos", "proximos", "na região", "na regiao")
#: Nenhuma forma de total no HTML ("de 1.025 resultados", "de 20 resultados").
TEXTO_DE_TOTAL = re.compile(r"\bde\s+[\d.]+\s+resultados?\b", re.IGNORECASE)
#: Teto de peso pedido pelo card para a abertura (sem o ranking).
TETO_HTML_BYTES = 25 * 1024


def _settings(*, anos: str = ",".join(str(ano) for ano in ANOS)) -> Settings:
    return Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        max_bytes_billed=256 * 1024 * 1024,
        validate_schema_on_startup=False,
        contract_version="mvp-1",
        app_anos_disponiveis=anos,
    )


@pytest.fixture
def mercado_repo() -> FakeRepository:
    """Repositório com mercado (todas as etapas) e 60 escolas no share.

    O share existe aqui para provar que a Visão geral **não** o consulta; o
    ranking usa o mesmo cenário em `test_web_mercado_escolas.py`.
    """
    return FakeRepository(
        municipios=[municipio_row()],
        markets=[
            market_row(nu_ano_censo=ano, etapa=etapa)
            for ano in ANOS
            for etapa in ("bas", "creche", "med")
        ],
        concentracao=[concentracao_row(nu_ano_censo=2025)],
        share=[
            share_row(
                nu_ano_censo=2025,
                etapa=etapa,
                id_entidade=f"310000{etapa}{indice:02d}",
                no_entidade=f"ESCOLA PRIVADA {etapa} {indice}",
                mat_entidade=float(200 - indice),
            )
            for etapa in ("bas", "med")
            for indice in range(60)
        ],
    )


def _client(
    repository: FakeRepository,
    *,
    anos: str | None = None,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = create_app(
        settings=_settings() if anos is None else _settings(anos=anos),
        repository=repository,
    )
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _html(response, status: int = 200) -> str:
    assert response.status_code == status, response.text[:600]
    assert response.headers["content-type"].startswith("text/html")
    return response.text


def _consultas(repository: FakeRepository, metodo: str) -> list[dict]:
    return [kwargs for nome, kwargs in repository.calls if nome == metodo]


# -- orçamento de consultas e de HTML (NAV-3) -------------------------------


def test_visao_geral_consulta_so_a_composicao_e_nunca_o_share(mercado_repo):
    """Abertura: 3 chamadas de `dados.mercado`, nenhuma de `share_mercado`."""
    _html(_client(mercado_repo).get(MERCADO))

    chamadas = [nome for nome, _ in mercado_repo.calls]
    assert set(chamadas) == {"get_municipio", "get_market", "get_concentracao"}
    assert "get_market_share" not in chamadas


def test_visao_geral_cabe_no_teto_de_html(mercado_repo):
    resposta = _client(mercado_repo).get(MERCADO)

    assert len(resposta.content) <= TETO_HTML_BYTES


def test_visao_geral_nao_renderiza_o_ranking_de_share(mercado_repo):
    html = desescapar(_html(_client(mercado_repo).get(MERCADO)))

    # O ranking é a outra seção: só o link do subnav aparece aqui.
    assert "Share de matrícula —" not in html
    assert "Recorte do share" not in html
    assert f'href="{ESCOLAS}' in html
    # Links mercado → escola são do ranking, não da abertura.
    assert "/app/escolas/310000" not in html


def test_offset_na_visao_geral_responde_422_sem_consultar(mercado_repo):
    resposta = _client(mercado_repo).get(f"{MERCADO}?offset=50")

    html = _html(resposta, 422)
    assert resposta.headers["cache-control"] == "no-store"
    assert "offset" in html
    assert mercado_repo.calls == []


# -- subnav, navbar e revalidação -------------------------------------------


def test_subnav_leva_ano_e_etapa_sem_offset_e_marca_a_secao_ativa(mercado_repo):
    html = desescapar(_html(_client(mercado_repo).get(f"{MERCADO}?ano=2024&etapa=med")))
    secao = html.split('aria-label="Seções do mercado"')[-1].split("</nav>")[0]

    assert (
        f'<a href="{MERCADO}?ano=2024&etapa=med" aria-current="page">Visão geral</a>'
        in secao
    )
    assert f'<a href="{ESCOLAS}?ano=2024&etapa=med">Escolas do mercado</a>' in secao
    assert "offset" not in secao
    # São links que trocam de URL, não abas na mesma página.
    assert 'role="tablist"' not in html


def test_navbar_marca_municipios_como_area_nas_duas_rotas(mercado_repo):
    cliente = _client(mercado_repo)

    for url in (MERCADO, ESCOLAS):
        html = cliente.get(url).text
        assert '<a href="/app/mercados/" aria-current="true">Municípios</a>' in html


def test_revalidacao_com_if_none_match_nao_consulta(mercado_repo):
    cliente = _client(mercado_repo)
    primeira = cliente.get(MERCADO)
    assert primeira.status_code == 200
    etag = primeira.headers["etag"]

    mercado_repo.calls.clear()
    segunda = cliente.get(MERCADO, headers={"If-None-Match": etag})

    assert segunda.status_code == 304
    assert mercado_repo.calls == []


def test_formulario_do_seletor_aponta_para_a_propria_visao_geral(mercado_repo):
    html = _html(_client(mercado_repo).get(MERCADO))

    assert f'<form class="formulario" method="get" action="{MERCADO}" role="search">' in html


# -- ano fora do contrato: 404 com seletor -----------------------------------


def test_ano_fora_do_contrato_responde_404_com_seletor(mercado_repo):
    resposta = _client(mercado_repo).get(f"{MERCADO}?ano=2019")

    html = _html(resposta, 404)
    assert resposta.headers["cache-control"] == "no-store"
    # O seletor de outro ano está na própria 404.
    assert 'id="ano"' in html
    for ano in ANOS:
        assert f'value="{ano}"' in html
    assert "Sem dados para este ano ou etapa" in html


def test_ano_fora_do_contrato_nao_consulta_mart(mercado_repo):
    _client(mercado_repo).get(f"{MERCADO}?ano=2019")

    assert not _consultas(mercado_repo, "get_market")
    assert not _consultas(mercado_repo, "get_market_share")


def test_ano_na_lista_sem_linha_no_mart_responde_404_com_seletor(
    mercado_repo: FakeRepository,
):
    """Ano do seletor sem publicação: o `/v1` responde ANO_FORA_DO_CONTRATO."""
    mercado_repo.markets = [
        row for row in mercado_repo.markets if row["nu_ano_censo"] == 2025
    ]

    html = _html(_client(mercado_repo).get(f"{MERCADO}?ano=2024"), 404)

    assert 'id="ano"' in html
    assert "<table" not in html.split('aria-labelledby="composicao"')[-1][:2000]


def test_sem_ano_usa_o_maior_ano_disponivel(mercado_repo):
    _client(mercado_repo).get(MERCADO)

    consultas = _consultas(mercado_repo, "get_market")
    assert consultas and all(item["ano"] == max(ANOS) for item in consultas)


def test_maior_ano_do_seletor_e_o_padrao_mesmo_com_lista_nao_ordenada():
    """A ordem do CSV não decide o padrão: o maior ano é o padrão."""
    repositorio = FakeRepository(
        municipios=[municipio_row()],
        markets=[market_row(nu_ano_censo=2023, etapa="bas")],
        share=[share_row(nu_ano_censo=2023)],
    )
    html = _html(_client(repositorio, anos="2023,2021").get(MERCADO))

    assert "2023" in html
    assert 'value="2023" selected' in html


# -- composição: contrato de chamada ---------------------------------------


def test_composicao_e_a_unica_consulta_de_mercado_e_sem_recorte_de_etapa(
    mercado_repo,
):
    _client(mercado_repo).get(MERCADO)

    consultas = _consultas(mercado_repo, "get_market")
    assert len(consultas) == 1
    assert consultas[0]["etapa"] is None


def test_etapa_informada_vale_para_cobertura_e_movimento(mercado_repo):
    html = _html(_client(mercado_repo).get(f"{MERCADO}?etapa=med"))

    assert "Cobertura da matrícula — Ensino médio" in html
    assert "Entrada e saída de escolas — Ensino médio" in html
    # A composição continua cobrindo todas as etapas publicadas.
    assert "Tamanho do mercado por etapa" in html


def test_denominadores_vem_da_linha_da_etapa_sem_consultar_share(mercado_repo):
    html = _html(_client(mercado_repo).get(f"{MERCADO}?etapa=med"))

    assert "Escolas privadas ativas no município e ano" in html
    assert ">30<" in html
    assert ">100<" in html
    assert not _consultas(mercado_repo, "get_market_share")


# -- ausência no primeiro ano da série --------------------------------------


def test_entrada_e_saida_nulas_do_primeiro_ano_saem_como_sem_dado(mercado_repo):
    mercado_repo.markets = [
        market_row(
            nu_ano_censo=max(ANOS),
            etapa="bas",
            n_escolas_entraram=None,
            n_escolas_ativas_com_baseline=None,
            n_escolas_sairam=None,
        )
    ]

    html = _html(_client(mercado_repo).get(MERCADO))

    assert MOTIVO_ENTRADA_SAIDA in html
    assert "Escolas que entraram" in html
    # A célula da linha existe e não é zero: a tabela traz "sem dado".
    secao = html.split('aria-labelledby="movimento"')[-1]
    assert "sem dado" in secao


# -- sem concentração (D4) e vocabulário -----------------------------------


def test_nao_exibe_hhi_nem_c4_e_nao_consulta_concentracao_a_parte(mercado_repo):
    html = _html(_client(mercado_repo).get(MERCADO))

    assert "hhi" not in html.lower()
    assert "C4" not in html
    assert "HHI" not in html
    # `get_concentracao` só é chamado pelo serviço de `market` (não pela tela).
    assert len(_consultas(mercado_repo, "get_concentracao")) == 1


def test_mercado_nao_usa_termos_geograficos_proibidos(mercado_repo):
    html = _html(_client(mercado_repo).get(MERCADO)).lower()

    for termo in TERMOS_PROIBIDOS:
        assert termo not in html, termo


def test_definicao_de_concorrencia_esta_na_tela(mercado_repo):
    html = _html(_client(mercado_repo).get(MERCADO))

    assert "no mesmo município e ano" in html


# -- recorte obrigatório ----------------------------------------------------


def test_recorte_obrigatorio_ano_etapa_universo_fonte_e_avisos(mercado_repo):
    html = _html(_client(mercado_repo).get(MERCADO))

    assert "Ano de referência" in html
    assert "2025" in html
    assert "Universo (meta.universo)" in html
    assert "escolas_ativas_mg" in html
    assert "Fonte (meta.fonte)" in html
    assert "mart_mercado" in html
    # O recorte do share só existe na rota do ranking.
    assert "mart_market_share" not in html
    assert "Avisos (meta.avisos)" in html


# -- seletor de ano e etapa -------------------------------------------------


def test_seletor_de_ano_lista_apenas_anos_disponiveis(mercado_repo):
    html = _html(_client(mercado_repo).get(MERCADO))

    for ano in ANOS:
        assert f'value="{ano}"' in html


def test_etapa_invalida_responde_422(mercado_repo):
    resposta = _client(mercado_repo).get(f"{MERCADO}?etapa=xyz")

    assert resposta.status_code == 422
    assert resposta.headers["content-type"].startswith("text/html")
    assert mercado_repo.calls == []


def test_etapa_sem_mercado_responde_404_com_seletor(mercado_repo):
    """Etapa sem linha em `mart_mercado` é o mesmo `ANO_FORA_DO_CONTRATO`."""
    html = _html(_client(mercado_repo).get(f"{MERCADO}?etapa=esp"), 404)

    assert 'id="etapa"' in html
    assert 'id="ano"' in html


def test_metadados_da_pagina_trazem_ano_e_etapa_do_recorte(mercado_repo):
    html = _html(_client(mercado_repo).get(f"{MERCADO}?ano=2024&etapa=med"))

    assert "2024" in html
    assert "Ensino médio" in html


def test_html_nunca_mostra_o_total_de_resultados(mercado_repo):
    for params in ("", "?ano=2024", "?etapa=med"):
        html = _html(_client(mercado_repo).get(f"{MERCADO}{params}"))
        assert not TEXTO_DE_TOTAL.search(html), TEXTO_DE_TOTAL.search(html)


# -- 503: página inteira ------------------------------------------------


def test_503_em_qualquer_consulta_vira_pagina_503(mercado_repo):
    from panorama_api.core.errors import UpstreamUnavailable

    mercado_repo.errors["get_market"] = UpstreamUnavailable()

    resposta = _client(mercado_repo).get(MERCADO)

    assert resposta.status_code == 503
    assert resposta.headers["cache-control"] == "no-store"
    assert resposta.headers["retry-after"] == "300"
    html = _html(resposta, 503)
    # Nada de seção parcial: a página inteira é o aviso de fonte indisponível.
    assert "Share de matrícula" not in html
    assert "Composição por etapa" not in html


def test_erro_nao_tratado_nao_vaza_stack(mercado_repo):
    mercado_repo.errors["get_market"] = RuntimeError("nada")

    resposta = _client(mercado_repo, raise_server_exceptions=False).get(MERCADO)

    assert resposta.status_code == 500
    assert resposta.headers["cache-control"] == "no-store"
    assert "Traceback" not in resposta.text
    assert "RuntimeError" not in resposta.text


# -- atalho do hero da landing: GET /app/mercados?co_municipio= ---------------
#
# Card `t_e075a6f6` (spec §6): o segundo botão da barra de busca do hero envia
# o mesmo formulário `GET /app/` com `formaction="/app/mercados"`, então a rota
# recebe `q` junto. Ela só redireciona: com município válido, 303 para a tela
# de mercado; sem município, 422 em HTML que manda escolher um. Nenhum caminho
# consulta o repositório.

ATALHO = "/app/mercados"


def test_atalho_com_municipio_valido_redireciona_303_sem_consultar_o_repositorio(
    mercado_repo,
):
    resposta = _client(mercado_repo).get(
        ATALHO,
        params={"co_municipio": "3106200", "q": "x"},
        follow_redirects=False,
    )

    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/app/mercados/3106200"
    # O `q` do formulário é descartado: a tela de destino não é busca.
    assert "q=" not in resposta.headers["location"]
    # O cache de páginas só trata 200: redirect não ganha ETag nem cache.
    assert "etag" not in resposta.headers
    assert "cache-control" not in resposta.headers
    assert mercado_repo.calls == []


def test_atalho_ignora_parametros_extras_e_usa_so_o_municipio(mercado_repo):
    resposta = _client(mercado_repo).get(
        ATALHO,
        params={"q": "qualquer coisa", "ano": "2019", "offset": "2000"},
        # `follow_redirects` desligado: só o cabeçalho do atalho interessa.
        follow_redirects=False,
    )

    # Sem município, os outros parâmetros não salvam a navegação: 422.
    assert resposta.status_code == 422

    com_municipio = _client(mercado_repo).get(
        ATALHO,
        params={"co_municipio": "3106200", "offset": "2000"},
        follow_redirects=False,
    )

    assert com_municipio.status_code == 303
    assert com_municipio.headers["location"] == "/app/mercados/3106200"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"co_municipio": ""},
        {"co_municipio": "   "},
        {"co_municipio": "9999999"},
        # Fora de MG: o atalho usa a mesma validação do `/v1`.
        {"co_municipio": "3500000"},
        {"co_municipio": "31062000"},
    ],
)
def test_atalho_sem_municipio_valido_responde_422_html(mercado_repo, params):
    resposta = _client(mercado_repo).get(ATALHO, params=params)

    html = _html(resposta, 422)
    assert "<h1>Escolha um município</h1>" in html
    assert "Para ver o mercado, selecione um município no formulário." in html
    assert '<a class="paginacao__link" href="/">Voltar ao início</a>' in html
    assert resposta.headers["cache-control"] == "no-store"
    assert "etag" not in resposta.headers
    assert mercado_repo.calls == []


def test_atalho_nao_entra_no_contrato_openapi(mercado_repo):
    cliente = _client(mercado_repo)

    paths = cliente.get("/openapi.json").json()["paths"]

    assert ATALHO not in paths
    assert "/" not in paths
    # As rotas do mercado continuam fora do contrato de `/v1`.
    assert "/app/mercados/{co_municipio}" not in paths
    assert "/app/mercados/{co_municipio}/escolas" not in paths
