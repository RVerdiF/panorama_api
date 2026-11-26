"""Indicadores e concorrência na ficha — âncora ``#concorrencia`` (card V2).

A rota antiga ``/app/escolas/{id}/concorrencia`` virou um ``301`` para a âncora
``#concorrencia`` da própria ficha: indicadores e comparação municipal passaram
a viver na **mesma** página dos KPIs, da série, da oferta/rendimento e do
ranking. Este arquivo cobre o que é verificável sobre o HTML renderizado de
verdade (``TestClient`` + repositório fake, sem rede/BigQuery):

* a rota legada responde ``301`` **sem** consultar o repositório; ``?ano=`` é
  ``422`` e um id fora do formato é ``422``;
* a ficha (privada ativa) mostra os rótulos do F11 ("posição por crescimento"
  com a direção), a definição da concorrência e o líder do município;
* `rank_crec_*` é posição de **crescimento**, nunca de creche (31005371);
* ausência (`rank` nulo, `competicao` nula) vira "sem dado" — nunca ``0``;
* escola pública/inativa → "não se aplica" com o motivo, sem a seção;
* 503 nos indicadores derruba a página **inteira**;
* revalidação com `If-None-Match` → ``304`` com `calls == []`.
"""

from __future__ import annotations

import re

import pytest

from panorama_api.core.errors import UpstreamUnavailable
from tests.unit.conftest import competidor_row, history_row, indicator_row, school_row

ESCOLA = "31000001"
VISAO_GERAL_URL = f"/app/escolas/{ESCOLA}"
CONCORRENCIA = f"{VISAO_GERAL_URL}/concorrencia"

#: Escola real do card F11 (COL COTEMIG BARROCA, BH): `qt_mat_creche = 0` e
#: posição nos rankings de **crescimento** (`rank_crec_municipio = 487`).
COTEMIG = "31005371"
COTEMIG_URL = f"/app/escolas/{COTEMIG}"

#: Rótulos exigidos pelo card: crescimento anual + direção da posição.
POSICAO_MUNICIPIO = (
    "Posição por crescimento anual da matrícula no município "
    "(1.º = maior crescimento ano a ano)"
)
POSICAO_MG = (
    "Posição por crescimento anual da matrícula em Minas Gerais "
    "(1.º = maior crescimento ano a ano)"
)
#: Definição da concorrência (mesma unidade geográfica e mesmo ano).
DEFINICAO = "no mesmo município e ano censitário"
#: Motivo quando a escola É privada ativa mas a mart não tem a linha do ano.
MOTIVO_SECAO_INDICADORES = (
    "Os indicadores só existem para escolas privadas ativas com matrícula da "
    "educação básica observada no ano de referência."
)
#: Motivo de quem está **fora** do universo de privadas ativas.
MOTIVO_FORA_UNIVERSO = (
    "Indicadores e comparação municipal existem apenas para escolas privadas "
    "ativas (universo privadas_ativas_mg)."
)


def _html(response, status: int = 200) -> str:
    assert response.status_code == status, response.text[:400]
    assert response.headers["content-type"].startswith("text/html")
    return response.text


def _leituras(repository) -> list[str]:
    """Leituras de dado da requisição (o `get_table_columns` é do boot)."""
    return [nome for nome in repository.methods_called() if nome != "get_table_columns"]


def _indicador_cotemig(**overrides) -> dict:
    valores = {
        "co_entidade": COTEMIG,
        "qt_mat_bas": 680,
        "qt_mat_creche": 0,
        "qt_mat_med": 680,
        "qt_mat_prof": 680,
        "qt_mat_esp": 21,
        "crescimento_yoy_pct": 12.4,
        "rank_crec_municipio": 487,
        "rank_crec_mg": 2134,
    }
    valores.update(overrides)
    return indicator_row(**valores)


# -- rota legada: 301 para a âncora -------------------------------------------


def test_rota_legada_redireciona_301_sem_consultar(client, repository):
    resposta = client.get(CONCORRENCIA, follow_redirects=False)

    assert resposta.status_code == 301
    assert resposta.headers["location"] == f"{VISAO_GERAL_URL}#concorrencia"
    # Nenhuma leitura de dado: o redirecionamento é só sintaxe de URL.
    assert _leituras(repository) == []


@pytest.mark.parametrize("ano", ["2020", "2025", "1999"])
def test_ano_na_rota_legada_responde_422_sem_consultar(client, repository, ano):
    resposta = client.get(f"{CONCORRENCIA}?ano={ano}")

    assert resposta.status_code == 422
    assert "Parâmetro inválido" in _html(resposta, status=422)
    assert _leituras(repository) == []


def test_id_invalido_na_rota_legada_responde_422(client, repository):
    resposta = client.get("/app/escolas/abc/concorrencia")

    assert resposta.status_code == 422
    assert _leituras(repository) == []


# -- ficha consolidada: rótulos do F11 ---------------------------------------


def _ficha_privada(client, repository, **competidor) -> str:
    repository.history = [
        history_row(nu_ano_censo=2025, tp_dependencia="4", tp_situacao_funcionamento="1")
    ]
    repository.indicators = [indicator_row()]
    repository.competidores = [competidor_row(**competidor)]
    return _html(client.get(VISAO_GERAL_URL))


def test_ficha_mostra_crescimento_definicao_e_rank(client, repository):
    html = _ficha_privada(client, repository)

    assert POSICAO_MUNICIPIO in html
    assert POSICAO_MG in html
    assert DEFINICAO in html
    assert "ESCOLA LIDER" in html
    # Posição municipal por matrícula (KPI) = rank 3 de 11 privadas ativas.
    assert "3.º" in html
    assert "de 11 escolas privadas ativas" in html
    # Sem share no indicador: a barra não existe e o valor é "sem dado".
    assert "barra-share__preenche" not in html
    # Ilha JSON da série para hidratação no cliente (`app.js` lê por textContent).
    assert '<script type="application/json" id="dados-serie">' in html
    assert '"anos": [2025]' in html


def test_ficha_com_share_mostra_barra_com_data_largura(client, repository):
    """Ranking em CSS do protótipo: trilho + preenche com o share real.

    Sem `style=`: a CSP `style-src 'self'` descartava o atributo e a barra
    nunca ganhava largura (rodada 1 da revisão, item 1). O SSR emite
    `data-largura` e o `app.js` (`aplicarBarras`) aplica via CSSOM.
    """
    repository.history = [
        history_row(nu_ano_censo=2025, tp_dependencia="4", tp_situacao_funcionamento="1")
    ]
    repository.indicators = [indicator_row(share_privado_pct=12.5)]
    repository.competidores = [competidor_row()]

    html = _html(client.get(VISAO_GERAL_URL))

    assert '<span class="barra-share__preenche" data-largura="12.5%">' in html
    assert "style=" not in html


def test_posicao_por_crescimento_nao_e_rotulada_de_creche(client, repository):
    repository.history = [
        history_row(
            co_entidade=COTEMIG,
            nu_ano_censo=2025,
            tp_dependencia="4",
            tp_situacao_funcionamento="1",
        )
    ]
    repository.indicators = [_indicador_cotemig()]
    repository.competidores = [competidor_row(co_entidade=COTEMIG)]

    html = _html(client.get(COTEMIG_URL))

    bloco = re.search(r'<div id="posicao-crescimento">.*?</div>', html, flags=re.S)
    assert bloco is not None, "bloco de posição ausente"
    assert "creche" not in bloco.group(0).lower()
    assert "487.º" in html


def test_posicao_sem_dado_nao_vira_zero(client, repository):
    repository.history = [
        history_row(nu_ano_censo=2025, tp_dependencia="4", tp_situacao_funcionamento="1")
    ]
    repository.indicators = [indicator_row(rank_crec_municipio=None, rank_crec_mg=None)]
    repository.competidores = [competidor_row()]

    html = _html(client.get(VISAO_GERAL_URL))

    assert "0.º" not in html
    assert "sem dado" in html


def test_aviso_de_porte_minimo_aparece_na_ficha(client, repository):
    repository.history = [
        history_row(nu_ano_censo=2025, tp_dependencia="4", tp_situacao_funcionamento="1")
    ]
    repository.indicators = [indicator_row(is_abaixo_porte=True)]
    repository.competidores = [competidor_row()]

    html = _html(client.get(VISAO_GERAL_URL))

    assert "abaixo do porte mínimo de comparabilidade" in html
    # E6: o código interno não aparece como texto.
    assert "IS_ABAIXO_PORTE" not in html


def test_gap_zero_mostra_que_a_escola_lidera(client, repository):
    html = _ficha_privada(client, repository, gap_mat_bas_para_lider=0)

    assert "lidera" in html


def test_gap_positivo_e_exibido_como_numero(client, repository):
    html = _ficha_privada(client, repository, gap_mat_bas_para_lider=180)

    assert "180" in html


# -- fora do universo: "não se aplica" ---------------------------------------


def test_escola_publica_vira_nao_se_aplica(client, repository):
    repository.history = [history_row(tp_dependencia="3", tp_situacao_funcionamento="1")]

    html = _html(client.get(VISAO_GERAL_URL))

    assert "Não se aplica" in html
    assert "Indicadores e concorrência: não se aplica a escola pública." in html
    # Sem a seção: não há âncora nem link para a rota antiga.
    assert '<a href="#concorrencia">' not in html
    assert "/concorrencia" not in html
    # Nenhuma consulta às marts privadas.
    assert _leituras(repository) == ["get_school_history"]


def test_escola_inativa_vira_nao_se_aplica(client, repository):
    repository.history = [history_row(tp_dependencia="4", tp_situacao_funcionamento="2")]

    html = _html(client.get(VISAO_GERAL_URL))

    assert "Indicadores e concorrência: não se aplica a escola inativa." in html
    assert _leituras(repository) == ["get_school_history"]


def test_privada_ativa_sem_linha_na_mart_explica_a_ausencia_da_secao(
    client, repository
):
    repository.history = [
        history_row(nu_ano_censo=2025, tp_dependencia="4", tp_situacao_funcionamento="1")
    ]
    repository.indicators = []

    html = _html(client.get(VISAO_GERAL_URL))

    assert "Não se aplica" in html
    assert MOTIVO_SECAO_INDICADORES in html
    assert "não pertence ao universo de indicadores" not in html
    assert MOTIVO_FORA_UNIVERSO not in html


# -- 503 e revalidação --------------------------------------------------------


def test_503_nos_indicadores_derruba_a_pagina_inteira(client, repository):
    repository.history = [
        history_row(nu_ano_censo=2025, tp_dependencia="4", tp_situacao_funcionamento="1")
    ]
    repository.errors["get_school_indicators"] = UpstreamUnavailable()

    resposta = client.get(VISAO_GERAL_URL)

    assert resposta.status_code == 503
    assert resposta.headers["cache-control"] == "no-store"
    assert resposta.headers["retry-after"] == "300"
    html = _html(resposta, status=503)
    assert "Posição no município" not in html


def test_revalidacao_com_if_none_match_nao_consulta(client, repository):
    repository.history = [
        history_row(nu_ano_censo=2025, tp_dependencia="4", tp_situacao_funcionamento="1")
    ]
    repository.indicators = [indicator_row()]
    repository.competidores = [competidor_row()]
    primeira = client.get(VISAO_GERAL_URL)
    assert primeira.status_code == 200
    etag = primeira.headers["etag"]

    repository.calls.clear()
    segunda = client.get(VISAO_GERAL_URL, headers={"If-None-Match": etag})

    assert segunda.status_code == 304
    assert repository.calls == []
