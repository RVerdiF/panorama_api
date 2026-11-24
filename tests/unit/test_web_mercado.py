"""Tela de mercado `/app/mercados/{co_municipio}` (card `t_c06ff921`).

Cobre os critérios de aceite do card sobre o HTML renderizado de verdade
(``TestClient`` + repositório fake, nenhuma rede/BigQuery):

* ``ANO_FORA_DO_CONTRATO`` → ``404`` **com** seletor de outro ano;
* ``data.items: []`` do share → "mercado sem escolas privadas com matrícula";
* escola ausente do share **nunca** aparece como ``0%``;
* ``null`` de entrada/saída no primeiro ano da série → "sem dado";
* sem HHI/C4 (decisão D4) e sem vocabulário geográfico proibido;
* share sempre com ``entidade_tipo=escola``, ``limit=50`` e paginação por
  ``has_more`` (nunca "de N resultados");
* recorte obrigatório: ano, etapa, ``meta.universo``, ``meta.fonte``, avisos.
"""

from __future__ import annotations

import re
from html import unescape as desescapar

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.main import create_app
from panorama_api.web.conteudo import (
    MOTIVO_ALEM_DO_FIM,
    MOTIVO_ENTRADA_SAIDA,
    MOTIVO_SEM_PRIVADAS,
)
from tests.unit.conftest import (
    FakeRepository,
    concentracao_row,
    market_row,
    municipio_row,
    share_row,
)

MUNICIPIO = "3106200"
MERCADO = f"/app/mercados/{MUNICIPIO}"
#: Anos do seletor usados nos testes.
ANOS = (2021, 2022, 2023, 2024, 2025)
#: Termos proibidos como vocabulário de comparação geográfica (escopo-adiado-v1).
TERMOS_PROIBIDOS = ("raio", "próximos", "proximos", "na região", "na regiao")
#: Nenhuma forma de total no HTML ("de 1.025 resultados", "de 20 resultados").
TEXTO_DE_TOTAL = re.compile(r"\bde\s+[\d.]+\s+resultados?\b", re.IGNORECASE)


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

    ``LIMITE_SHARE_PADRAO`` é 50, então a primeira página tem 50 linhas e
    ``has_more`` — a segunda página serve para a paginação ser exercitada. Há
    share em duas etapas (``bas`` e ``med``) para os testes de seletor.
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
    repository: FakeRepository, *, anos: str | None = None, raise_server_exceptions: bool = True
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
    mercado_repo.markets = [row for row in mercado_repo.markets if row["nu_ano_censo"] == 2025]

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


# -- share: vazio e ausência de escola --------------------------------------


def test_share_vazio_diz_mercado_sem_escolas_privadas_com_matricula(mercado_repo):
    mercado_repo.share = []

    html = _html(_client(mercado_repo).get(MERCADO))

    assert MOTIVO_SEM_PRIVADAS in html
    assert MOTIVO_ALEM_DO_FIM not in html
    assert "<table" not in html.split('aria-labelledby="share"')[-1][:1200]


@pytest.mark.parametrize("params", ["?offset=0", "?etapa=bas&offset=0"])
def test_share_vazio_com_offset_zero_mantem_a_mensagem_de_ausencia(
    mercado_repo, params
):
    """Com `offset=0` a ausência é real: a mensagem atual não muda (C2)."""
    mercado_repo.share = []

    html = _html(_client(mercado_repo).get(f"{MERCADO}{params}"))

    assert MOTIVO_SEM_PRIVADAS in html
    assert MOTIVO_ALEM_DO_FIM not in html
    assert "Voltar à primeira página" not in html


# -- offset além do fim: NÃO é mercado sem privadas (C2) ---------------------


def test_offset_alem_do_fim_nao_diz_que_o_mercado_nao_tem_privadas(mercado_repo):
    """Página vazia com `offset > 0` não é ausência de mercado (BH tem 819)."""
    resposta = _client(mercado_repo).get(f"{MERCADO}?etapa=bas&offset=1000")

    html = _html(resposta)
    assert MOTIVO_SEM_PRIVADAS not in html
    assert MOTIVO_ALEM_DO_FIM in html
    # A volta leva ao mesmo recorte (ano/etapa) na 1ª página, sem `offset`.
    # `&amp;` é o `&` do href depois do escape do Jinja: o navegador vê a URL
    # literal do critério de aceite.
    assert (
        f'href="{MERCADO}?ano=2025&etapa=bas"'
        in desescapar(html)
    )
    # Página 200 de página vazia: a política de cache das páginas não muda.
    assert resposta.headers["cache-control"] == "private, no-cache"


def test_offset_alem_do_fim_preserva_ano_e_etapa_no_link_de_volta(mercado_repo):
    html = desescapar(
        _html(_client(mercado_repo).get(f"{MERCADO}?ano=2024&etapa=med&offset=1000"))
    )

    assert f'href="{MERCADO}?ano=2024&etapa=med"' in html
    assert "offset=1000" not in html.split('aria-labelledby="share"')[-1]


def test_offset_alem_do_fim_nao_pede_refinamento_nem_mostra_anterior(mercado_repo):
    """A lista acabou: nem "Próxima" nem o aviso de teto de paginação."""
    html = _html(_client(mercado_repo).get(f"{MERCADO}?offset=1000"))

    secao = html.split('aria-labelledby="share"')[-1]
    assert "Próxima" not in secao
    assert "Limite de paginação atingido" not in secao


def test_escola_ausente_do_share_nunca_aparece_como_zero_por_cento(mercado_repo):
    """Só a linha do share é exibida; ausência não é 0%."""
    mercado_repo.share = [
        share_row(nu_ano_censo=2025, etapa="bas", id_entidade="31000007")
    ]

    html = _html(_client(mercado_repo).get(MERCADO))

    assert "31000007" in html
    assert "31000008" not in html
    # Nenhuma célula de percentual sai como zero.
    assert "<td>0%</td>" not in html
    assert "<td>0,0%</td>" not in html


def test_share_nulo_sai_como_sem_dado_e_nao_como_zero(mercado_repo):
    mercado_repo.share = [
        share_row(
            nu_ano_censo=2025,
            etapa="bas",
            id_entidade="31000009",
            mat_entidade=None,
            share_privado_pct=None,
            share_total_pct=None,
        )
    ]

    html = _html(_client(mercado_repo).get(MERCADO))

    assert "31000009" in html
    assert "sem dado" in html
    assert "<td>0%</td>" not in html
    assert "<td>sem dado%</td>" not in html


# -- share: contrato de chamada e paginação ---------------------------------


def test_share_e_consultado_com_entidade_tipo_escola_e_limit_50(mercado_repo):
    _client(mercado_repo).get(MERCADO)

    (consulta,) = _consultas(mercado_repo, "get_market_share")
    assert consulta["entidade_tipo"] == "escola"
    assert consulta["limit"] == 50
    assert consulta["offset"] == 0
    assert consulta["etapa"] == "bas"
    assert consulta["ano"] == max(ANOS)


def test_composicao_e_consultada_sem_recorte_de_etapa(mercado_repo):
    _client(mercado_repo).get(MERCADO)

    consultas = _consultas(mercado_repo, "get_market")
    assert consultas
    # A primeira é a da composição (a tela); a segunda é do serviço de share,
    # que confirma a existência do mercado da etapa antes de paginar.
    assert consultas[0]["etapa"] is None


def test_proxima_so_aparece_com_has_more(mercado_repo):
    html = _html(_client(mercado_repo).get(MERCADO))
    assert "Próxima" in html

    mercado_repo.share = mercado_repo.share[:5]
    html = _html(_client(mercado_repo).get(MERCADO))
    assert "Próxima" not in html


def test_paginacao_preserva_ano_e_etapa(mercado_repo):
    html = _html(_client(mercado_repo).get(f"{MERCADO}?ano=2025&etapa=med"))

    assert f"ano=2025" in html
    assert "etapa=med" in html
    assert "offset=50" in html


def test_html_nunca_mostra_o_total_de_resultados(mercado_repo):
    for params in ("", "?ano=2024", "?etapa=med", "?offset=50"):
        html = _html(_client(mercado_repo).get(f"{MERCADO}{params}"))
        assert not TEXTO_DE_TOTAL.search(html), TEXTO_DE_TOTAL.search(html)


def test_offset_invalido_responde_404_ou_422_sem_consultar_share(mercado_repo):
    resposta = _client(mercado_repo).get(f"{MERCADO}?offset=5000")

    assert resposta.status_code in (422, 404)
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
    assert len(_consultas(mercado_repo, "get_concentracao")) <= 1


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
    assert "mart_market_share" in html
    assert "mart_mercado" in html
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


def test_etapa_informada_seleciona_o_share_daquela_etapa(mercado_repo):
    _client(mercado_repo).get(f"{MERCADO}?etapa=creche")

    (consulta,) = _consultas(mercado_repo, "get_market_share")
    assert consulta["etapa"] == "creche"


def test_etapa_sem_mercado_responde_404_com_seletor(mercado_repo):
    """Etapa sem linha em `mart_mercado` é o mesmo `ANO_FORA_DO_CONTRATO`."""
    html = _html(_client(mercado_repo).get(f"{MERCADO}?etapa=esp"), 404)

    assert 'id="etapa"' in html
    assert 'id="ano"' in html


def test_metadados_da_pagina_trazem_ano_e_etapa_do_recorte(mercado_repo):
    html = _html(_client(mercado_repo).get(f"{MERCADO}?ano=2024&etapa=med"))

    assert "2024" in html
    assert "Ensino médio" in html


# -- 503: página inteira ------------------------------------------------


def test_503_em_qualquer_consulta_vira_pagina_503(mercado_repo):
    from panorama_api.core.errors import UpstreamUnavailable

    mercado_repo.errors["get_market_share"] = UpstreamUnavailable()

    resposta = _client(mercado_repo).get(MERCADO)

    assert resposta.status_code == 503
    assert resposta.headers["cache-control"] == "no-store"
    assert resposta.headers["retry-after"] == "300"
    html = _html(resposta, 503)
    # Nada de seção parcial: a página inteira é o aviso de fonte indisponível.
    assert "Share de matrícula" not in html
    assert "Composição por etapa" not in html


def test_erro_nao_tratado_nao_vaza_stack(mercado_repo):
    mercado_repo.errors["get_market_share"] = RuntimeError("nada")

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
    # A tela de mercado continua no contrato como estava.
    assert "/app/mercados/{co_municipio}" not in paths
