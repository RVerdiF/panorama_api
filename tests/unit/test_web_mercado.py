"""Mercado `/app/mercados/{co_municipio}` (cards F5, V2 e D1-E3).

Cobre os critérios de aceite sobre o HTML renderizado de verdade
(``TestClient`` + repositório fake, nenhuma rede/BigQuery):

* abertura consulta `dados.mercado` + `dados.share_mercado` com `limit=10`
  (a mesma etapa do recorte, `offset=0`); a página 2 (`?offset=`) desloca o
  share na própria `section#escolas` — decisão D4, que trocou o handler da
  rota `/escolas` por um **301** (cobertura dele em
  `test_web_mercado_escolas_redirect.py`) e **reescreveu** este teste de
  `offset` (a asserção de validação `0..1000` sobrevive: fora da faixa é
  ``422`` sem consultar o repositório);
* ``ANO_FORA_DO_CONTRATO`` → ``404`` **com** seletor de outro ano;
* composição: `ul.composicao` com as 5 etapas que somam + nota com soma e
  total; movimento: `ul.ranking` de 1 cartão com baseline, `estado-vazio` no
  1º ano; cobertura sem `<table>`; `#escolas` paginada (10 linhas,
  `paginacao__estado`, anterior/próxima com `#escolas`, teto 1000,
  além-do-fim, sem-privadas);
* subnav do protótipo (4 itens literais, `aria-current` em Visão geral);
  seletor de 3 campos com `action` no atalho; atalho 303 repassa `ano`/`etapa`;
* recorte obrigatório, revalidação `If-None-Match` → 304, `null` nunca vira
  `0`, sem HHI/C4 e sem vocabulário geográfico proibido.
"""

from __future__ import annotations

import re
from html import unescape as desescapar

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.main import create_app
from panorama_api.web.conteudo import MOTIVO_ALEM_DO_FIM, MOTIVO_SEM_PRIVADAS
from panorama_api.web.mercado import barra_share
from tests.unit.conftest import (
    FakeRepository,
    market_row,
    municipio_row,
    share_row,
)

MUNICIPIO = "3106200"
MERCADO = f"/app/mercados/{MUNICIPIO}"
ATALHO = "/app/mercados"
#: Anos do seletor usados nos testes.
ANOS = (2021, 2022, 2023, 2024, 2025)
#: Nenhuma forma de total no HTML ("de 1.025 resultados", "de 20 resultados").
TEXTO_DE_TOTAL = re.compile(r"\bde\s+[\d.]+\s+resultados?\b", re.IGNORECASE)
#: Teto de peso da página com o ranking (10 linhas) e o seletor de município.
#:
#: O seletor de município do DOM do protótipo (card D1-E3) lista as 853 opções
#: de `municipios_mg` com o atual selecionado: ~45 KB a mais que a página do
#: V2. O teto sobe de 25 KB para 62 KB **sem** afrouxar o que ele protege —
#: 10 linhas por página, sem consulta nova, sem JS.
TETO_HTML_BYTES = 62 * 1024


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
    """Repositório com mercado, movimento em 2025 e 60 escolas no share.

    O share existe em duas etapas (``bas`` e ``med``) para os testes de
    seletor; 2025 carrega movimento (baseline) e composição diferenciada
    (creche 3.000 + med 9.000 ≠ total `bas` 15.000); 2021 tem movimento nulo
    (1º ano da série → `estado-vazio`).
    """
    mercados = [
        market_row(nu_ano_censo=ano, etapa=etapa)
        for ano in ANOS
        for etapa in ("bas", "creche", "med")
    ]
    for linha in mercados:
        if linha["nu_ano_censo"] == 2025 and linha["etapa"] == "bas":
            linha.update(
                n_escolas_entraram=4,
                n_escolas_ativas_com_baseline=26,
                n_escolas_sairam=2,
            )
        if linha["nu_ano_censo"] == 2025 and linha["etapa"] == "creche":
            linha.update(qt_mat_privada=3000.0)
        if linha["nu_ano_censo"] == 2025 and linha["etapa"] == "med":
            linha.update(qt_mat_privada=9000.0)
    return FakeRepository(
        municipios=[municipio_row()],
        markets=mercados,
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


# -- orçamento de consultas e de HTML --------------------------------------


def test_abertura_consulta_mercado_e_share_limit_10(mercado_repo):
    """Abertura: `dados.mercado` + `dados.share_mercado` (etapa do recorte).

    Decisão D4: o ranking de share mora na `section#escolas` da própria página
    (`limit=10`, primeira página) — a rota `/escolas` virou 301.
    """
    _html(_client(mercado_repo).get(MERCADO))

    chamadas = [nome for nome, _ in mercado_repo.calls]
    assert set(chamadas) == {
        "get_municipio",
        "get_market",
        "get_concentracao",
        "get_market_share",
    }
    (consulta,) = _consultas(mercado_repo, "get_market_share")
    assert consulta["etapa"] == "bas"
    assert consulta["entidade_tipo"] == "escola"
    assert consulta["limit"] == 10
    assert consulta["offset"] == 0


def test_pagina_2_desloca_o_share_na_propria_pagina(mercado_repo):
    """`?offset=10` refaz mercado + share e mostra as linhas 11–20 (crit. 7)."""
    _html(_client(mercado_repo).get(f"{MERCADO}?offset=10"))

    consultas = _consultas(mercado_repo, "get_market_share")
    assert len(consultas) == 1
    assert consultas[0]["offset"] == 10
    assert consultas[0]["limit"] == 10
    assert _consultas(mercado_repo, "get_market")


def test_mercado_cabe_no_teto_de_html(mercado_repo):
    resposta = _client(mercado_repo).get(MERCADO)

    assert len(resposta.content) <= TETO_HTML_BYTES


# -- offset na própria página: 200 pagina, fora da faixa 422 (D1-g) ---------


def test_offset_10_mostra_as_linhas_11_a_20(mercado_repo):
    html = desescapar(_html(_client(mercado_repo).get(f"{MERCADO}?offset=10")))

    assert html.count('id="escola-310000bas') == 10
    assert 'id="escola-310000bas10"' in html
    assert 'id="escola-310000bas19"' in html
    assert 'id="escola-310000bas09"' not in html
    assert 'id="escola-310000bas20"' not in html
    assert "<td class=\"num\">11.</td>" in html
    assert "<td class=\"num\">20.</td>" in html
    assert "<p class=\"paginacao__estado\">Mostrando 11–20</p>" in html


@pytest.mark.parametrize("params", ["?offset=5000", "?offset=-1"])
def test_offset_fora_da_faixa_responde_422_sem_consultar(mercado_repo, params):
    """D1-g: `offset` fora de `0..1000` é `422` sem consultar o repositório."""
    resposta = _client(mercado_repo).get(f"{MERCADO}{params}")

    html = _html(resposta, 422)
    assert resposta.headers["cache-control"] == "no-store"
    assert "offset" in html
    assert mercado_repo.calls == []


def test_etapa_informada_seleciona_o_share_daquela_etapa(mercado_repo):
    _client(mercado_repo).get(f"{MERCADO}?etapa=med")

    (consulta,) = _consultas(mercado_repo, "get_market_share")
    assert consulta["etapa"] == "med"


# -- subnav, seletor, navbar e revalidação ----------------------------------


def test_subnav_do_prototipo_com_aria_current_na_visao_geral(mercado_repo):
    html = desescapar(_html(_client(mercado_repo).get(MERCADO)))
    secao = html.split('aria-label="Seções do mercado"')[-1].split("</nav>")[0]

    assert '<a href="#composicao" aria-current="page">Visão geral</a>' in secao
    assert '<a href="#escolas">Escolas do mercado</a>' in secao
    assert '<a href="/app/mercados/">← Índice de municípios</a>' in secao
    assert '<a href="/app/">Buscar escolas</a>' in secao
    # São âncoras e links de saída, não abas na mesma página.
    assert 'role="tablist"' not in html


def test_seletor_tem_3_campos_e_posta_no_atalho(mercado_repo):
    html = desescapar(_html(_client(mercado_repo).get(f"{MERCADO}?ano=2024&etapa=med")))

    assert f'<form method="get" action="{ATALHO}">' in html
    assert '<div class="filtros filtros--3">' in html
    assert '<select id="ano" name="ano">' in html
    assert '<select id="etapa" name="etapa">' in html
    assert '<select id="municipio" name="co_municipio">' in html
    assert '<button type="submit" class="botao botao--primario">Ver mercado</button>' in html
    # O recorte atual vem selecionado; a etapa lista as 9 do contrato.
    assert '<option value="2024" selected>' in html
    assert '<option value="med" selected>' in html
    assert '<option value="3106200" selected>' in html
    for etapa in ("bas", "creche", "pre", "fund_ai", "fund_af", "med", "prof", "eja", "esp"):
        assert f'<option value="{etapa}"' in html


def test_navbar_marca_municipios_como_area(mercado_repo):
    html = _client(mercado_repo).get(MERCADO).text

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


# -- composição: 5 etapas que somam -----------------------------------------


def test_composicao_tem_5_etapas_que_somam_nesta_ordem(mercado_repo):
    html = _html(_client(mercado_repo).get(MERCADO))
    bloco = html.split('id="composicao-etapas"')[-1].split("</ul>")[0]

    assert bloco.count("<li>") == 5
    rotulos = re.findall(r'<span class="comp-nome">(.*?)</span>', bloco)
    assert rotulos == [
        "Creche",
        "Pré-escola",
        "Ensino fundamental — anos iniciais",
        "Ensino fundamental — anos finais",
        "Ensino médio",
    ]


def test_composicao_nota_traz_soma_e_total_reais(mercado_repo):
    """Soma das 5 (12.000) e total privado de `bas` (15.000), mesmo diferentes."""
    html = _html(_client(mercado_repo).get(MERCADO))

    assert "Soma das etapas: 12.000 · total privado do ano: 15.000" in html


def test_composicao_percentual_com_uma_casa_e_largura_para_barras(mercado_repo):
    html = _html(_client(mercado_repo).get(MERCADO))

    assert "3.000 <small>20,0%</small>" in html
    assert "9.000 <small>60,0%</small>" in html
    # Largura via `data-largura` (o `aplicarBarras` aplica; nunca `style=`).
    assert 'data-largura="33.3%"' in html
    assert 'data-largura="100.0%"' in html
    assert "style=" not in html


def test_composicao_etapa_sem_valor_mostra_sem_dado_sem_barra(mercado_repo):
    html = _html(_client(mercado_repo).get(MERCADO))
    bloco = html.split('id="composicao-etapas"')[-1].split("</ul>")[0]

    # Pré-escola, anos iniciais e anos finais não têm linha em `mart_mercado`.
    assert bloco.count('<span class="sem-dado">sem dado</span>') == 3
    # Só as 2 etapas com valor ganham barra.
    assert bloco.count("comp-preenche") == 2


# -- movimento: ranking com baseline, vazio no 1º ano ------------------------


def test_movimento_com_baseline_mostra_ranking_de_1_cartao(mercado_repo):
    html = _html(_client(mercado_repo).get(MERCADO))
    bloco = html.split('id="movimento-conteudo"')[-1].split("</section>")[0]

    assert '<ul class="ranking">' in bloco
    assert '<p class="ranking__nome">Escolas privadas ativas</p>' in bloco
    assert '<p class="ranking__meta">2024 → 2025</p>' in bloco
    assert ">30 <small>4 entraram · 2 saíram</small>" in bloco


def test_movimento_no_primeiro_ano_mostra_estado_vazio(mercado_repo):
    html = _html(_client(mercado_repo).get(f"{MERCADO}?ano=2021"))
    bloco = html.split('id="movimento-conteudo"')[-1].split("</section>")[0]

    assert '<ul class="ranking">' not in bloco
    assert "Sem dado no primeiro ano do recorte" in bloco
    assert "Em 2021 não há ano anterior" in bloco


# -- cobertura e limites: só nota + definição --------------------------------


def test_cobertura_sem_tabela_com_nota_e_definicao(mercado_repo):
    html = _html(_client(mercado_repo).get(MERCADO))
    bloco = html.split('id="titulo-cobertura"')[-1].split("</section>")[0]

    assert "<table" not in bloco
    assert "Sem indicador de concentração." in bloco
    assert "nunca como 0%." in bloco


# -- #escolas: ranking paginado na própria página ----------------------------


def test_escolas_primeira_pagina_tem_10_linhas(mercado_repo):
    """O painel mostra 10 linhas da etapa do recorte, com link para a ficha."""
    html = desescapar(_html(_client(mercado_repo).get(MERCADO)))

    assert html.count('id="escola-310000bas') == 10
    assert "<td class=\"num\">1.</td>" in html
    assert "<td class=\"num\">10.</td>" in html
    assert "<td class=\"num\">11.</td>" not in html
    assert '<a class="nome-escola" href="/app/escolas/310000bas00">' in html
    # Share privado com 2 casas.
    assert "0,80%" in html
    assert "<p class=\"paginacao__estado\">Mostrando 1–10</p>" in html


def test_escolas_paginacao_tem_anterior_e_proxima_com_ancora(mercado_repo):
    html = desescapar(_html(_client(mercado_repo).get(f"{MERCADO}?offset=10")))

    assert (
        f'<a class="botao botao--secundario" href="{MERCADO}?ano=2025&etapa=bas#escolas"'
        ' rel="prev">Anterior</a>' in html
    )
    assert 'href="/app/mercados/3106200?ano=2025&etapa=bas&offset=20#escolas"' in html
    assert 'rel="next">Próxima</a>' in html


def test_escolas_primeira_pagina_tem_anterior_indisponivel(mercado_repo):
    html = _html(_client(mercado_repo).get(MERCADO))
    nav = html.split('id="paginacao-share"')[-1].split("</nav>")[0]

    assert '<span class="botao botao--secundario" aria-disabled="true">Anterior</span>' in nav
    assert 'offset=10' in nav


def test_escolas_teto_de_1000_esconde_proxima_e_pede_outra_etapa(mercado_repo):
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
    html = _html(_client(mercado_repo).get(f"{MERCADO}?offset=1000"))

    secao = html.split('id="titulo-escolas"')[-1]
    assert "Mostrando 1001–1010" in secao
    # Sem link de próxima (só o botão desabilitado) + aviso de teto.
    assert 'rel="next"' not in secao
    assert '<span class="botao botao--secundario" aria-disabled="true">Próxima</span>' in secao
    assert "Limite de paginação atingido" in secao


def test_escolas_offset_alem_do_fim_nao_diz_que_o_mercado_nao_tem_privadas(
    mercado_repo,
):
    """Página vazia com `offset > 0` não é ausência de mercado (achado C2)."""
    resposta = _client(mercado_repo).get(f"{MERCADO}?etapa=bas&offset=1000")

    html = _html(resposta)
    assert MOTIVO_SEM_PRIVADAS not in html
    assert MOTIVO_ALEM_DO_FIM in html
    # A volta leva ao mesmo recorte (ano/etapa) na 1ª página, sem `offset`.
    assert f'href="{MERCADO}?ano=2025&etapa=bas#escolas">Voltar à primeira página</a>' in desescapar(html)
    assert resposta.headers["cache-control"] == "private, no-cache"


def test_escolas_offset_alem_do_fim_preserva_ano_e_etapa_no_link_de_volta(
    mercado_repo,
):
    html = desescapar(_html(_client(mercado_repo).get(f"{MERCADO}?ano=2024&etapa=med&offset=1000")))

    assert f'href="{MERCADO}?ano=2024&etapa=med#escolas"' in html


def test_escolas_share_vazio_diz_mercado_sem_privadas(mercado_repo):
    mercado_repo.share = []

    html = _html(_client(mercado_repo).get(MERCADO))

    assert MOTIVO_SEM_PRIVADAS in html
    assert MOTIVO_ALEM_DO_FIM not in html
    assert "Voltar à primeira página" not in html


def test_escolas_linhas_tem_ancora_unica_por_inep(mercado_repo):
    """Cada linha tem `id="escola-<INEP>"`, sem repetir e sem `escola-None`."""
    html = _html(_client(mercado_repo).get(f"{MERCADO}?etapa=bas"))

    corpo = html.split("<tbody>")[-1].split("</tbody>")[0]
    linhas = re.findall(r"<tr\b[^>]*>.*?</tr>", corpo, re.DOTALL)
    assert len(linhas) == 10
    identificadores = []
    for linha in linhas:
        ancora = re.search(r'id="escola-([^"]+)"', linha)
        assert ancora is not None, "linha sem âncora"
        identificadores.append(ancora.group(1))
    assert len(identificadores) == len(set(identificadores))
    assert identificadores[0] == "310000bas00"


def test_escolas_escola_ausente_do_share_nunca_aparece_como_zero(mercado_repo):
    """Só a linha do share é exibida; ausência não é 0%."""
    mercado_repo.share = [
        share_row(nu_ano_censo=2025, etapa="bas", id_entidade="31000007")
    ]

    html = _html(_client(mercado_repo).get(MERCADO))

    assert "31000007" in html
    assert "31000008" not in html
    assert ">0%<" not in html
    assert ">0,00%<" not in html


def test_escolas_share_nulo_sai_como_sem_dado_e_nao_como_zero(mercado_repo):
    mercado_repo.share = [
        share_row(
            nu_ano_censo=2025,
            etapa="bas",
            id_entidade="31000009",
            mat_entidade=None,
            share_privado_pct=None,
        )
    ]

    html = _html(_client(mercado_repo).get(MERCADO))

    assert "31000009" in html
    assert "sem dado" in html
    assert "sem dado%" not in html


# -- ano/etapa fora do contrato ----------------------------------------------


def test_ano_fora_do_contrato_responde_404_com_seletor(mercado_repo):
    resposta = _client(mercado_repo).get(f"{MERCADO}?ano=2019")

    html = _html(resposta, 404)
    assert resposta.headers["cache-control"] == "no-store"
    # O seletor de outro ano está na própria 404 (com o estado vazio).
    assert 'id="ano"' in html
    for ano in ANOS:
        assert f'value="{ano}"' in html
    assert "Sem dados para este ano ou etapa" in html
    assert 'id="sem-dados-ano"' in html
    assert '<ul class="composicao"' not in html


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
    assert '<ul class="composicao"' not in html


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


def test_composicao_continua_sem_recorte_de_etapa(mercado_repo):
    """`get_market` cobre todas as etapas; o share leva a etapa do recorte."""
    _client(mercado_repo).get(MERCADO)

    consultas = _consultas(mercado_repo, "get_market")
    assert {consulta["etapa"] for consulta in consultas} == {None, "bas"}


def test_etapa_informada_vale_para_movimento_e_denominadores(mercado_repo):
    html = _html(_client(mercado_repo).get(f"{MERCADO}?etapa=med"))

    assert "Entrada e saída de escolas — Ensino médio" in html
    assert ">30<" in html
    assert ">9.000<" in html
    # Os denominadores saem da linha da etapa em `mart_mercado`; o share do
    # ranking leva a mesma etapa do recorte.
    (consulta,) = _consultas(mercado_repo, "get_market_share")
    assert consulta["etapa"] == "med"


def test_metadados_da_pagina_trazem_ano_e_etapa_do_recorte(mercado_repo):
    html = _html(_client(mercado_repo).get(f"{MERCADO}?ano=2024&etapa=med"))

    assert "2024" in html
    assert "Ensino médio" in html


def test_titulo_traz_o_municipio(mercado_repo):
    html = _html(_client(mercado_repo).get(MERCADO))

    titulo = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    assert titulo is not None
    assert titulo.group(1).startswith("Mercado municipal de BELO HORIZONTE")
    assert "Panorama Escola" in titulo.group(1)


# -- sem concentração (D4), vocabulário e recorte -----------------------------


def test_nao_exibe_hhi_nem_c4_e_nao_consulta_concentracao_a_parte(mercado_repo):
    html = _html(_client(mercado_repo).get(MERCADO))

    assert "hhi" not in html.lower()
    assert "C4" not in html
    assert "HHI" not in html
    # `get_concentracao` só é chamado pelo serviço de `market` (não pela tela).
    assert len(_consultas(mercado_repo, "get_concentracao")) == 1


def test_mercado_nao_usa_termos_geograficos_proibidos(mercado_repo):
    html = _html(_client(mercado_repo).get(MERCADO)).lower()

    for termo in ("raio", "próximos", "proximos", "na região", "na regiao"):
        assert termo not in html, termo


def test_recorte_obrigatorio_ano_etapa_universo_fonte_e_avisos(mercado_repo):
    html = _html(_client(mercado_repo).get(MERCADO))

    assert "Ano de referência" in html
    assert "2025" in html
    # Rótulo do dado, não o caminho no contrato (`meta.universo`): card V1.
    assert "<dt>Universo</dt>" in html
    assert "escolas_ativas_mg" in html
    assert "<dt>Fonte</dt>" in html
    assert "mart_mercado" in html
    assert "<dt>Avisos</dt>" in html


def test_html_nunca_mostra_o_total_de_resultados(mercado_repo):
    for params in ("", "?ano=2024", "?etapa=med", "?offset=10"):
        html = _html(_client(mercado_repo).get(f"{MERCADO}{params}"))
        assert not TEXTO_DE_TOTAL.search(html), TEXTO_DE_TOTAL.search(html)


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
    assert "Tamanho e composição por etapa" not in html
    assert "Escolas do mercado por share" not in html


def test_erro_nao_tratado_nao_vaza_stack(mercado_repo):
    mercado_repo.errors["get_market"] = RuntimeError("nada")

    resposta = _client(mercado_repo, raise_server_exceptions=False).get(MERCADO)

    assert resposta.status_code == 500
    assert resposta.headers["cache-control"] == "no-store"
    assert "Traceback" not in resposta.text
    assert "RuntimeError" not in resposta.text


# -- `barra_share` continua puro (a barra vive no ranking da ficha) -----------


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


def test_custo_de_consultas_nao_muda_com_ancora_e_paginacao():
    """A âncora e a paginação derivam do que já veio: nenhuma consulta nova."""
    from tests.unit.conftest import history_row

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
    _html(cliente.get(MERCADO))
    # O share reconfirma município + mercado no serviço: 2 chamadas cada.
    assert sorted(nome for nome, _ in repo.calls) == [
        "get_concentracao",
        "get_market",
        "get_market",
        "get_market_share",
        "get_municipio",
        "get_municipio",
    ]


# -- atalho do hero: GET /app/mercados?co_municipio= -------------------------
#
# Card `t_e075a6f6` (spec §6) + D4 (card D1-E3): o segundo botão da barra de
# busca do hero envia o mesmo formulário `GET /app/` com
# `formaction="/app/mercados"`. A rota só redireciona: com município válido,
# 303 para a tela de mercado repassando `ano`/`etapa` quando presentes (a
# validação deles continua no destino); sem município, 422 em HTML. Nenhum
# caminho consulta o repositório.


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


def test_atalho_repasse_ano_e_etapa_no_303(mercado_repo):
    """D4: o seletor do mercado posta aqui; o recorte segue no `Location`."""
    resposta = _client(mercado_repo).get(
        ATALHO,
        params={"co_municipio": "3106200", "ano": "2024", "etapa": "med"},
        follow_redirects=False,
    )

    assert resposta.status_code == 303
    assert (
        resposta.headers["location"] == "/app/mercados/3106200?ano=2024&etapa=med"
    )
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
    # A rota do mercado continua fora do contrato de `/v1`.
    assert "/app/mercados/{co_municipio}" not in paths
