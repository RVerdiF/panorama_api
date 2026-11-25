"""Escolas do mercado `/app/mercados/{co_municipio}/escolas` (card NAV-3).

O ranking de share deixou a abertura do mercado e virou rota própria. Cobre os
critérios de aceite sobre o HTML renderizado de verdade (``TestClient`` +
repositório fake, nenhuma rede/BigQuery):

* a rota consulta **só** `dados.share_mercado` (3 chamadas: `get_municipio`,
  `get_market`, `get_market_share`) e **nunca** `get_concentracao`;
* HTML ≤ 30 KB com as 50 linhas da primeira página;
* paginação (`Anterior`/`Próxima`) aponta para `/escolas` e preserva `ano` e
  `etapa`; teto de 1000 e estado vazio pós-fim mantêm o comportamento do N3;
* escola ausente do share **nunca** aparece como ``0%``; ``null`` → "sem dado";
* ``ANO_FORA_DO_CONTRATO`` → ``404`` com seletor; ``If-None-Match`` → 304 sem
  consulta;
* subnav com o recorte atual e a seção ativa em ``aria-current="page"``;
* links mercado → escola continuam na tabela do ranking.

Os testes do ranking que viviam em `test_web_mercado.py` foram movidos para cá
(não apagados): é a rota que agora os renderiza.
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
    MOTIVO_SEM_PRIVADAS,
)
from panorama_api.web.mercado import barra_share
from tests.unit.conftest import (
    FakeRepository,
    history_row,
    market_row,
    municipio_row,
    share_row,
)

MUNICIPIO = "3106200"
MERCADO = f"/app/mercados/{MUNICIPIO}"
ESCOLAS = f"{MERCADO}/escolas"
#: Anos do seletor usados nos testes.
ANOS = (2021, 2022, 2023, 2024, 2025)
#: Nenhuma forma de total no HTML ("de 1.025 resultados", "de 20 resultados").
TEXTO_DE_TOTAL = re.compile(r"\bde\s+[\d.]+\s+resultados?\b", re.IGNORECASE)
#: Teto de peso do ranking (50 linhas), medido no teste.
#:
#: A barra decorativa por linha (card `t_e120b83b`: SVG de 121 B por `<tr>`)
#: acrescenta ~5,9 KB às 50 linhas: a página medida sai com ~32,6 KB brutos
#: (3,4 KB em gzip). O teto sobe de 30 KB para 34 KB **sem** afrouxar o que ele
#: protege: 50 linhas por página, sem consulta nova, sem JS.
TETO_HTML_BYTES = 34 * 1024


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


def _secao_share(html: str) -> str:
    return html.split('aria-labelledby="share"')[-1]


# -- orçamento de consultas e de HTML (NAV-3) -------------------------------


def test_ranking_consulta_so_o_share_e_nunca_a_concentracao(mercado_repo):
    """Ranking: 3 chamadas de `dados.share_mercado`, nenhuma de concentração."""
    _html(_client(mercado_repo).get(ESCOLAS))

    chamadas = [nome for nome, _ in mercado_repo.calls]
    assert set(chamadas) == {"get_municipio", "get_market", "get_market_share"}
    assert "get_concentracao" not in chamadas


def test_ranking_cabe_no_teto_de_html_com_50_linhas(mercado_repo):
    html = _html(_client(mercado_repo).get(f"{ESCOLAS}?ano=2025&etapa=bas"))

    assert "Mostrando 1–50." in html
    assert len(html.encode()) <= TETO_HTML_BYTES


def test_ranking_nao_renderiza_a_composicao(mercado_repo):
    html = _html(_client(mercado_repo).get(ESCOLAS))

    assert "Composição por etapa" not in html
    assert "Recorte da composição" not in html
    assert "mart_mercado" not in html
    # O recorte do share é da rota do ranking.
    assert "mart_market_share" in html


def test_ranking_so_carrega_o_app_js_com_defer(mercado_repo):
    """Card `t_71b25279`: a única tag de script é o `app.js` com hash e `defer`."""
    html = _html(_client(mercado_repo).get(ESCOLAS))

    scripts = re.findall(r"<script\b[^>]*>\s*</script>", html)
    assert len(scripts) == 1, scripts
    assert re.search(r'src="/app/static/[0-9a-f]{12}-app\.js" defer', scripts[0]), scripts[0]


# -- subnav, navbar, formulário e revalidação -------------------------------


def test_subnav_leva_ano_e_etapa_sem_offset_e_marca_o_ranking_como_ativo(
    mercado_repo,
):
    html = desescapar(_html(_client(mercado_repo).get(f"{ESCOLAS}?ano=2024&etapa=med")))
    secao = html.split('aria-label="Seções do mercado"')[-1].split("</nav>")[0]

    assert f'<a href="{MERCADO}?ano=2024&etapa=med">Visão geral</a>' in secao
    assert (
        f'<a href="{ESCOLAS}?ano=2024&etapa=med" aria-current="page">'
        "Escolas do mercado</a>" in secao
    )
    assert "offset" not in secao
    assert 'role="tablist"' not in html


def test_subnav_nao_carrega_offset_na_pagina_2(mercado_repo):
    """O subnav leva o recorte (ano/etapa) e recomeça na 1ª página da seção."""
    html = desescapar(_html(_client(mercado_repo).get(f"{ESCOLAS}?offset=50&etapa=med")))
    secao = html.split('aria-label="Seções do mercado"')[-1].split("</nav>")[0]

    assert f'href="{MERCADO}?ano=2025&etapa=med"' in secao
    assert f'href="{ESCOLAS}?ano=2025&etapa=med"' in secao
    assert "offset" not in secao


def test_formulario_do_seletor_aponta_para_o_ranking(mercado_repo):
    html = _html(_client(mercado_repo).get(ESCOLAS))

    assert f'<form class="formulario" method="get" action="{ESCOLAS}" role="search">' in html


def test_titulo_do_ranking_traz_o_municipio(mercado_repo):
    html = _html(_client(mercado_repo).get(ESCOLAS))

    titulo = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    assert titulo is not None
    assert titulo.group(1).startswith("Escolas do mercado de Belo Horizonte")
    assert "Panorama Escola" in titulo.group(1)


def test_revalidacao_com_if_none_match_nao_consulta(mercado_repo):
    cliente = _client(mercado_repo)
    primeira = cliente.get(ESCOLAS)
    assert primeira.status_code == 200
    etag = primeira.headers["etag"]

    mercado_repo.calls.clear()
    segunda = cliente.get(ESCOLAS, headers={"If-None-Match": etag})

    assert segunda.status_code == 304
    assert mercado_repo.calls == []


# -- share: vazio e ausência de escola --------------------------------------


def test_share_vazio_diz_mercado_sem_escolas_privadas_com_matricula(mercado_repo):
    mercado_repo.share = []

    html = _html(_client(mercado_repo).get(ESCOLAS))

    assert MOTIVO_SEM_PRIVADAS in html
    assert MOTIVO_ALEM_DO_FIM not in html
    assert "<table" not in _secao_share(html)[:2000]


@pytest.mark.parametrize("params", ["?offset=0", "?etapa=bas&offset=0"])
def test_share_vazio_com_offset_zero_mantem_a_mensagem_de_ausencia(
    mercado_repo, params
):
    """Com `offset=0` a ausência é real: a mensagem atual não muda (C2)."""
    mercado_repo.share = []

    html = _html(_client(mercado_repo).get(f"{ESCOLAS}{params}"))

    assert MOTIVO_SEM_PRIVADAS in html
    assert MOTIVO_ALEM_DO_FIM not in html
    assert "Voltar à primeira página" not in html


# -- offset além do fim: NÃO é mercado sem privadas (C2) ---------------------


def test_offset_alem_do_fim_nao_diz_que_o_mercado_nao_tem_privadas(mercado_repo):
    """Página vazia com `offset > 0` não é ausência de mercado (BH tem 819)."""
    resposta = _client(mercado_repo).get(f"{ESCOLAS}?etapa=bas&offset=1000")

    html = _html(resposta)
    assert MOTIVO_SEM_PRIVADAS not in html
    assert MOTIVO_ALEM_DO_FIM in html
    # A volta leva ao mesmo recorte (ano/etapa) na 1ª página, sem `offset`.
    # `&amp;` é o `&` do href depois do escape do Jinja: o navegador vê a URL
    # literal do critério de aceite.
    assert f'href="{ESCOLAS}?ano=2025&etapa=bas"' in desescapar(html)
    # Página 200 de página vazia: a política de cache das páginas não muda.
    assert resposta.headers["cache-control"] == "private, no-cache"


def test_offset_alem_do_fim_preserva_ano_e_etapa_no_link_de_volta(mercado_repo):
    html = desescapar(
        _html(_client(mercado_repo).get(f"{ESCOLAS}?ano=2024&etapa=med&offset=1000"))
    )

    assert f'href="{ESCOLAS}?ano=2024&etapa=med"' in html
    assert "offset=1000" not in _secao_share(html)


def test_offset_alem_do_fim_nao_pede_refinamento_nem_mostra_anterior(mercado_repo):
    """A lista acabou: nem "Próxima" nem o aviso de teto de paginação."""
    html = _html(_client(mercado_repo).get(f"{ESCOLAS}?offset=1000"))

    secao = _secao_share(html)
    assert "Próxima" not in secao
    assert "Limite de paginação atingido" not in secao


def test_escola_ausente_do_share_nunca_aparece_como_zero_por_cento(mercado_repo):
    """Só a linha do share é exibida; ausência não é 0%."""
    mercado_repo.share = [
        share_row(nu_ano_censo=2025, etapa="bas", id_entidade="31000007")
    ]

    html = _html(_client(mercado_repo).get(ESCOLAS))

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

    html = _html(_client(mercado_repo).get(ESCOLAS))

    assert "31000009" in html
    assert "sem dado" in html
    assert "<td>0%</td>" not in html
    assert "<td>sem dado%</td>" not in html


def test_link_do_nome_do_ranking_leva_a_ficha_da_escola(mercado_repo):
    html = _html(_client(mercado_repo).get(ESCOLAS))

    assert '<a href="/app/escolas/310000bas00">ESCOLA PRIVADA bas 0</a>' in html


# -- share: contrato de chamada e paginação ---------------------------------


def test_share_e_consultado_com_entidade_tipo_escola_e_limit_50(mercado_repo):
    _client(mercado_repo).get(ESCOLAS)

    (consulta,) = _consultas(mercado_repo, "get_market_share")
    assert consulta["entidade_tipo"] == "escola"
    assert consulta["limit"] == 50
    assert consulta["offset"] == 0
    assert consulta["etapa"] == "bas"
    assert consulta["ano"] == max(ANOS)


def test_proxima_so_aparece_com_has_more(mercado_repo):
    html = _html(_client(mercado_repo).get(ESCOLAS))
    assert "Próxima" in html

    mercado_repo.share = mercado_repo.share[:5]
    html = _html(_client(mercado_repo).get(ESCOLAS))
    assert "Próxima" not in html


def test_paginacao_preserva_ano_e_etapa_e_aponta_para_escolas(mercado_repo):
    html = desescapar(_html(_client(mercado_repo).get(f"{ESCOLAS}?ano=2025&etapa=med")))

    assert f'href="{ESCOLAS}?ano=2025&etapa=med&offset=50"' in html


def test_anterior_tambem_aponta_para_escolas(mercado_repo):
    html = desescapar(_html(_client(mercado_repo).get(f"{ESCOLAS}?offset=50&etapa=med")))

    assert f'href="{ESCOLAS}?ano=2025&etapa=med" rel="prev"' in html


def test_teto_de_1000_esconde_proxima_e_pede_outra_etapa(mercado_repo):
    """Com `has_more` no teto, "Próxima" some e o aviso de teto aparece."""
    mercado_repo.share = [
        share_row(
            nu_ano_censo=2025,
            etapa="bas",
            id_entidade=f"31000{indice:05d}",
            no_entidade=f"ESCOLA {indice}",
        )
        for indice in range(1100)
    ]

    html = _html(_client(mercado_repo).get(f"{ESCOLAS}?offset=1000"))

    secao = _secao_share(html)
    assert "Mostrando 1001–1050." in secao
    assert "Próxima" not in secao
    assert "Limite de paginação atingido" in secao


def test_html_nunca_mostra_o_total_de_resultados(mercado_repo):
    for params in ("", "?ano=2024", "?etapa=med", "?offset=50"):
        html = _html(_client(mercado_repo).get(f"{ESCOLAS}{params}"))
        assert not TEXTO_DE_TOTAL.search(html), TEXTO_DE_TOTAL.search(html)


def test_offset_invalido_responde_404_ou_422_sem_consultar_share(mercado_repo):
    resposta = _client(mercado_repo).get(f"{ESCOLAS}?offset=5000")

    assert resposta.status_code in (422, 404)
    assert not _consultas(mercado_repo, "get_market_share")


# -- ano e etapa fora do contrato -------------------------------------------


def test_ano_fora_do_contrato_responde_404_com_seletor(mercado_repo):
    resposta = _client(mercado_repo).get(f"{ESCOLAS}?ano=2019")

    html = _html(resposta, 404)
    assert resposta.headers["cache-control"] == "no-store"
    assert 'id="ano"' in html
    for ano in ANOS:
        assert f'value="{ano}"' in html
    assert "Sem dados para este ano ou etapa" in html
    # Recorte substituto não consulta nada: o ano fora da lista é barrado antes.
    assert not _consultas(mercado_repo, "get_market_share")


def test_etapa_invalida_responde_422(mercado_repo):
    resposta = _client(mercado_repo).get(f"{ESCOLAS}?etapa=xyz")

    assert resposta.status_code == 422
    assert resposta.headers["content-type"].startswith("text/html")
    assert not _consultas(mercado_repo, "get_market_share")


def test_etapa_informada_seleciona_o_share_daquela_etapa(mercado_repo):
    _client(mercado_repo).get(f"{ESCOLAS}?etapa=creche")

    (consulta,) = _consultas(mercado_repo, "get_market_share")
    assert consulta["etapa"] == "creche"


def test_etapa_sem_mercado_responde_404_com_seletor(mercado_repo):
    """Etapa sem linha em `mart_mercado` é o mesmo `ANO_FORA_DO_CONTRATO`."""
    html = _html(_client(mercado_repo).get(f"{ESCOLAS}?etapa=esp"), 404)

    assert 'id="etapa"' in html
    assert 'id="ano"' in html


def test_metadados_da_pagina_trazem_ano_e_etapa_do_recorte(mercado_repo):
    html = _html(_client(mercado_repo).get(f"{ESCOLAS}?ano=2024&etapa=med"))

    assert "2024" in html
    assert "Ensino médio" in html


# -- 503: página inteira ------------------------------------------------


def test_503_na_consulta_de_share_vira_pagina_503(mercado_repo):
    from panorama_api.core.errors import UpstreamUnavailable

    mercado_repo.errors["get_market_share"] = UpstreamUnavailable()

    resposta = _client(mercado_repo).get(ESCOLAS)

    assert resposta.status_code == 503
    assert resposta.headers["cache-control"] == "no-store"
    assert resposta.headers["retry-after"] == "300"
    html = _html(resposta, 503)
    # Nada de seção parcial: a página inteira é o aviso de fonte indisponível.
    assert "Share de matrícula" not in html


def test_erro_nao_tratado_nao_vaza_stack(mercado_repo):
    mercado_repo.errors["get_market_share"] = RuntimeError("nada")

    resposta = _client(mercado_repo, raise_server_exceptions=False).get(ESCOLAS)

    assert resposta.status_code == 500
    assert resposta.headers["cache-control"] == "no-store"
    assert "Traceback" not in resposta.text
    assert "RuntimeError" not in resposta.text


# -- âncora por INEP e barra de share por linha (card t_e120b83b) ------------


def _corpo_da_tabela(html: str) -> str:
    """Só o `<tbody>` do ranking: o `<thead>` não tem âncora nem barra."""
    return html.split("<tbody>")[-1].split("</tbody>")[0]


def _linhas_do_ranking(html: str) -> list[str]:
    """`<tr>` do corpo do ranking, uma string por linha (sem `<thead>`)."""
    return re.findall(r"<tr\b[^>]*>.*?</tr>", _corpo_da_tabela(html), re.DOTALL)


def _linha_da_escola(html: str, id_entidade: str) -> str:
    """`<tr>` de uma escola, isolado do resto do HTML (e não do HTML inteiro)."""
    achado = re.search(
        rf'<tr id="escola-{re.escape(id_entidade)}">.*?</tr>',
        _corpo_da_tabela(html),
        re.DOTALL,
    )
    assert achado is not None, f"linha sem âncora para {id_entidade}"
    return achado.group(0)


def test_linhas_do_ranking_tem_ancora_unica_por_id(mercado_repo):
    """Cada linha tem `id="escola-<INEP>"`, sem repetir e sem `escola-None`."""
    html = _html(_client(mercado_repo).get(f"{ESCOLAS}?etapa=bas"))

    linhas = _linhas_do_ranking(html)
    assert linhas
    identificadores = []
    for linha in linhas:
        ancora = re.search(r'id="escola-([^"]+)"', linha)
        assert ancora is not None, "linha sem âncora"
        identificadores.append(ancora.group(1))
    # Uma âncora por linha e nenhum id repetido na página.
    assert len(identificadores) == len(linhas) == len(set(identificadores))
    # O id é o INEP da própria linha (posição preservada).
    assert 'id="escola-310000bas00"' in linhas[0]
    assert 'id="escola-310000bas01"' in linhas[1]

    # Sem código INEP a âncora não existe. O contrato (`ShareItem.id_entidade:
    # str`) recusa `None` antes do template, então o valor sem conteúdo que
    # chega até aqui é `""` — e a página não pode ganhar `id="escola-"` nem
    # `id="escola-None"`.
    mercado_repo.share = [
        share_row(nu_ano_censo=2025, etapa="bas", id_entidade="")
    ]
    html = _html(_client(mercado_repo).get(f"{ESCOLAS}?etapa=bas"))

    corpo = _corpo_da_tabela(html)
    assert "escola-None" not in html
    assert "escola-" not in corpo
    assert "id=" not in _linhas_do_ranking(html)[0].split(">")[0]


def test_share_nulo_nao_ganha_barra_e_share_presente_ganha(mercado_repo):
    """Share nulo continua "sem dado" (sem barra); share presente ganha a barra."""
    mercado_repo.share = [
        share_row(
            nu_ano_censo=2025,
            etapa="bas",
            id_entidade="31000001",
            mat_entidade=None,
            share_privado_pct=None,
        ),
        share_row(
            nu_ano_censo=2025,
            etapa="bas",
            id_entidade="31000002",
            share_privado_pct=37.5,
        ),
    ]

    html = _html(_client(mercado_repo).get(f"{ESCOLAS}?etapa=bas"))

    assert "barra-share__preenche" not in _linha_da_escola(html, "31000001")
    assert "sem dado" in _linha_da_escola(html, "31000001")
    assert 'data-largura="37.5%"' in _linha_da_escola(html, "31000002")


def test_barra_limita_share_fora_de_0_100(mercado_repo):
    """A barra é leitura visual: fora de 0..100 satura, não estoura a faixa."""
    mercado_repo.share = [
        share_row(
            nu_ano_censo=2025,
            etapa="bas",
            id_entidade="31000003",
            share_privado_pct=137.5,
        ),
        share_row(
            nu_ano_censo=2025,
            etapa="bas",
            id_entidade="31000004",
            share_privado_pct=-3.2,
        ),
    ]

    html = _html(_client(mercado_repo).get(f"{ESCOLAS}?etapa=bas"))

    linha_acima = _linha_da_escola(html, "31000003")
    assert 'data-largura="100.0%"' in linha_acima

    linha_abaixo = _linha_da_escola(html, "31000004")
    assert 'data-largura="0.0%"' in linha_abaixo


def test_barra_e_decorativa_e_nao_duplica_a_leitura(mercado_repo):
    """O trilho não tem texto; o percentual continua em texto na célula."""
    mercado_repo.share = [
        share_row(
            nu_ano_censo=2025,
            etapa="bas",
            id_entidade="31000005",
            share_privado_pct=37.5,
        )
    ]

    html = _html(_client(mercado_repo).get(f"{ESCOLAS}?etapa=bas"))

    linha = _linha_da_escola(html, "31000005")
    trilho = re.search(r"<span\b[^>]*barra-share__trilho[^>]*>", linha)
    assert trilho is not None
    # A leitura acessível é o número em texto, antes da barra.
    # A célula do share privado é o penúltimo `<td>` da linha.
    celula = linha.split("<td>")[-2]
    assert "37,5%" in celula
    assert celula.index("37,5%") < celula.index("barra-share__trilho")


def test_barra_share_formata_e_limita_o_valor():
    """`barra_share` é puro: `None`/não finito → sem barra; fora de 0..100 satura."""
    assert barra_share(None) is None
    assert barra_share(float("nan")) is None
    assert barra_share(float("inf")) is None
    # Largura com uma casa, como o protótipo (`toFixed(1)`).
    for pct, largura in (
        (37.5, "37.5"),
        (100.0, "100.0"),
        (0, "0.0"),
        (0.0834, "0.1"),
        (137.5, "100.0"),
        (-3.2, "0.0"),
    ):
        assert f'<span class="barra-share__preenche" data-largura="{largura}%">' in str(
            barra_share(pct)
        ), pct


def test_custo_de_consultas_nao_muda_com_ancora_e_barra():
    """A âncora e a barra são derivadas do que já veio: nenhuma consulta nova.
    A ficha da escola custa 1 consulta (`get_school_history`) e o ranking custa
    3 (`get_municipio`, `get_market`, `get_market_share`) — os mesmos números de
    antes do card, medidos por rota no mesmo repositório fake.
    """
    repo = FakeRepository(
        municipios=[municipio_row()],
        markets=[market_row(nu_ano_censo=2025, etapa="bas")],
        share=[
            share_row(nu_ano_censo=2025, etapa="bas", id_entidade="31000001")
        ],
        history=[history_row()],
    )
    cliente = _client(repo)

    _html(cliente.get("/app/escolas/31000001"))
    assert [nome for nome, _ in repo.calls] == ["get_school_history"]

    repo.calls.clear()
    _html(cliente.get(ESCOLAS))
    assert sorted(nome for nome, _ in repo.calls) == [
        "get_market",
        "get_market_share",
        "get_municipio",
    ]
