"""Tela da escola `/app/escolas/{co_entidade}` (card `t_49960786`).

Cobre o que o card exige como verificável sobre o HTML renderizado:

* escola pública/inativa → repositório fake registra **0** chamadas de
  `get_school_indicators`/`get_school_competidores` (classificação pelo item
  mais recente do `history`);
* 404 residual de universo (`/indicators`, `/competitors`) → seção "não se
  aplica" com a página em 200;
* `gap_mat_bas_para_lider = 0` → "a escola lidera";
* rótulo do proxy de retenção contém "não é taxa de evasão";
* 503 em qualquer consulta → **página inteira 503** (`no-store`,
  `Retry-After`), nunca render parcial;
* série com SVG inline no servidor + tabela equivalente acessível;
* `null` → "sem dado" (com a flag de origem), oferta tri-estado;
* meta obrigatória (ano, etapa, universo, fonte, avisos) e vocabulário proibido.
"""

from __future__ import annotations

import re

import pytest

from panorama_api.core.errors import UpstreamUnavailable
from panorama_api.web.filters import fmt_ano, fmt_gap_lider
from tests.unit.conftest import competidor_row, history_row, indicator_row, school_row

ESCOLA = "/app/escolas/31000001"
#: Termos proibidos como vocabulário de comparação geográfica (escopo-adiado-v1).
TERMOS_PROIBIDOS = ("raio", "próximos", "proximos", "na região", "na regiao")
#: Chamadas ao repositório que só podem existir no universo privadas ativas.
METODOS_PRIVADAS = ("get_school_indicators", "get_school_competidores")
#: Motivo exibido quando a escola está fora do universo de privadas ativas.
MOTIVO_FORA_UNIVERSO = (
    "Indicadores e comparação municipal existem apenas para escolas privadas "
    "ativas (universo privadas_ativas_mg)."
)


def _html(response, status: int = 200) -> str:
    assert response.status_code == status, response.text[:400]
    assert response.headers["content-type"].startswith("text/html")
    return response.text


def _serie(
    *anos: int, overrides: dict[int, dict] | None = None
) -> list[dict]:
    """Série de `history` para os anos pedidos, com overrides por ano."""
    valores_por_ano = overrides or {}
    return [
        history_row(
            nu_ano_censo=ano,
            tp_dependencia="4",
            tp_situacao_funcionamento="1",
            **valores_por_ano.get(ano, {}),
        )
        for ano in anos
    ]


# -- classificador de universo: 0 chamadas para pública/inativa -----------------


def test_escola_publica_nao_consulta_indicadores_nem_competidores(client, repository):
    repository.history = [
        history_row(tp_dependencia="3", tp_situacao_funcionamento="1")
    ]

    html = _html(client.get(ESCOLA))

    chamadas = repository.methods_called()
    assert not [metodo for metodo in METODOS_PRIVADAS if metodo in chamadas], chamadas
    assert "get_school_history" in chamadas
    # A ausência é explicada na tela, não silenciada.
    assert "Não se aplica" in html
    assert MOTIVO_FORA_UNIVERSO in html


def test_escola_inativa_nao_consulta_indicadores_nem_competidores(client, repository):
    repository.history = [
        history_row(tp_dependencia="4", tp_situacao_funcionamento="2")
    ]

    _html(client.get(ESCOLA))

    chamadas = repository.methods_called()
    assert not [metodo for metodo in METODOS_PRIVADAS if metodo in chamadas], chamadas


def test_classificacao_usa_o_item_mais_recente_da_serie(client, repository):
    """Ano antigo privado/ativo não muda a decisão do ano corrente."""
    repository.history = [
        history_row(
            nu_ano_censo=2020, tp_dependencia="4", tp_situacao_funcionamento="1"
        ),
        history_row(
            nu_ano_censo=2025, tp_dependencia="3", tp_situacao_funcionamento="1"
        ),
    ]

    _html(client.get(ESCOLA))

    chamadas = repository.methods_called()
    assert not [metodo for metodo in METODOS_PRIVADAS if metodo in chamadas], chamadas


def test_escola_sem_dependencia_declarada_nao_consulta_privadas(client, repository):
    """Campo nulo não vira "privada": o front falha fechado e não gasta cota."""
    repository.history = [
        history_row(tp_dependencia=None, tp_situacao_funcionamento="1")
    ]

    _html(client.get(ESCOLA))

    chamadas = repository.methods_called()
    assert not [metodo for metodo in METODOS_PRIVADAS if metodo in chamadas], chamadas


def test_escola_privada_ativa_consulta_indicadores_e_competidores(client, repository):
    repository.history = _serie(2024, 2025, overrides={2024: {"qt_mat_bas": 110}})
    repository.indicators = [indicator_row()]
    repository.competidores = [competidor_row()]

    html = _html(client.get(ESCOLA))

    chamadas = repository.methods_called()
    assert all(metodo in chamadas for metodo in METODOS_PRIVADAS), chamadas
    assert "Proxy de retenção líquida (não é taxa de evasão)" in html


# -- 404 residual de universo: seção "não se aplica" na página 200 -------------


def test_404_de_indicators_vira_secao_nao_se_aplica_com_pagina_200(
    client, repository
):
    """Privada ativa sem linha nas marts: 404 do `/v1` é estado legítimo da seção."""
    repository.schools = [school_row()]
    repository.history = _serie(2025)
    repository.indicators = []
    repository.competidores = [competidor_row()]

    html = _html(client.get(ESCOLA), status=200)

    blocos = re.findall(r'<p class="nao-se-aplica">(.*?)</p>', html, flags=re.S)
    assert len(blocos) == 1
    assert "Não se aplica" in blocos[0]
    # O motivo é a copy da tela, nunca o detail de diagnóstico da API.
    assert "não pertence ao universo de indicadores" not in html
    assert "matrícula da educação básica observada" in blocos[0]
    # A escola É privada ativa: o texto não pode afirmar o contrário.
    assert MOTIVO_FORA_UNIVERSO not in html
    # A série continua visível: não é erro de página, é ausência de seção.
    assert "Série de matrículas" in html
    # E a comparação municipal, que existe, segue renderizada.
    assert "Posição por matrícula da educação básica no município" in html
    assert _gap_no_html(html)


def test_404_de_competidores_nao_derruba_a_secao_de_indicadores(
    client, repository
):
    repository.schools = [school_row()]
    repository.history = _serie(2025)
    repository.indicators = [indicator_row()]
    repository.competidores = []

    html = _html(client.get(ESCOLA), status=200)

    assert "Não se aplica" in html
    # Privada ativa sem linha na mart de competidores: a explicação correta é a
    # de ausência de matrícula observada, não "fora do universo privado".
    assert "comparação municipal só existe" in html
    assert MOTIVO_FORA_UNIVERSO not in html
    assert "Proxy de retenção líquida (não é taxa de evasão)" in html


# -- posição municipal ---------------------------------------------------------


def test_gap_zero_mostra_que_a_escola_lidera(client, repository):
    repository.schools = [school_row()]
    repository.history = _serie(2025)
    repository.indicators = [indicator_row()]
    repository.competidores = [
        competidor_row(
            lider_no_entidade="ESCOLA MODELO",
            lider_qt_mat_bas=120,
            gap_mat_bas_para_lider=0,
        )
    ]

    html = _html(client.get(ESCOLA))

    # Gap zero é medição válida: a própria escola é a líder, não ausência.
    assert _gap_no_html(html) == "a escola lidera"


def test_gap_positivo_e_exibido_como_numero(client, repository):
    repository.schools = [school_row()]
    repository.history = _serie(2025)
    repository.indicators = [indicator_row()]
    repository.competidores = [
        competidor_row(lider_qt_mat_bas=300, gap_mat_bas_para_lider=180)
    ]

    html = _html(client.get(ESCOLA))

    assert _gap_no_html(html) == "180"


def _gap_no_html(html: str) -> str:
    """Conteúdo da célula do saldo para o líder (uma única, sempre renderizada)."""
    achado = re.search(r'<dd class="gap-lider">([^<]*)</dd>', html)
    assert achado is not None, "saldo para o líder ausente na comparação municipal"
    return achado.group(1).strip()


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [(0, "a escola lidera"), (180, "180"), (None, "sem dado")],
)
def test_filtro_de_gap_para_lider(valor, esperado):
    assert fmt_gap_lider(valor) == esperado


def test_comparacao_municipal_mostra_a_definicao(client, repository):
    repository.schools = [school_row()]
    repository.history = _serie(2025)
    repository.indicators = [indicator_row()]
    repository.competidores = [competidor_row()]

    html = _html(client.get(ESCOLA))

    assert "Escolas privadas ativas no mesmo município e ano censitário (MG)" in html
    # A posição no município é exibida junto do líder.
    assert "ESCOLA LIDER" in html


# -- 503: página inteira, nunca parcial ---------------------------------------


def test_503_na_serie_derruba_a_pagina_inteira(client, repository):
    repository.history = _serie(2025)
    repository.errors["get_school_history"] = UpstreamUnavailable()

    resposta = client.get(ESCOLA)

    assert resposta.status_code == 503
    assert resposta.headers["cache-control"] == "no-store"
    assert resposta.headers["retry-after"] == "300"
    html = _html(resposta, status=503)
    # Nenhuma seção de dados é renderizada parcialmente.
    assert "Série de matrículas" not in html
    assert "não é taxa de evasão" not in html


def test_503_nos_indicadores_derruba_a_pagina_inteira(client, repository):
    repository.history = _serie(2025)
    repository.errors["get_school_indicators"] = UpstreamUnavailable()

    resposta = client.get(ESCOLA)

    assert resposta.status_code == 503
    assert resposta.headers["cache-control"] == "no-store"
    assert resposta.headers["retry-after"] == "300"
    html = _html(resposta, status=503)
    assert "Série de matrículas" not in html


def test_503_nos_competidores_derruba_a_pagina_inteira(client, repository):
    repository.history = _serie(2025)
    repository.indicators = [indicator_row()]
    repository.errors["get_school_competidores"] = UpstreamUnavailable()

    resposta = client.get(ESCOLA)

    assert resposta.status_code == 503
    assert "não se aplica" not in _html(resposta, status=503).lower()


# -- série: SVG no servidor + tabela equivalente acessível --------------------


def test_serie_tem_svg_inline_e_tabela_equivalente(client, repository):
    repository.history = _serie(
        2023,
        2024,
        2025,
        overrides={2023: {"qt_mat_bas": 90}, 2024: {"qt_mat_bas": 110}},
    )

    html = _html(client.get(ESCOLA))

    svg = re.search(r"<svg[^>]*>.*?</svg>", html, flags=re.S)
    assert svg is not None, "gráfico SVG inline ausente"
    # O SVG não duplica a leitura: a tabela é o equivalente acessível.
    assert 'aria-hidden="true"' in svg.group(0)
    # Uma barra por ano com matrícula observada (2025 usa o default do fixture).
    assert svg.group(0).count("<rect") == 3
    assert "serie__ausente" not in svg.group(0)

    tabela = _tabela(html, "Série de matrículas por ano")
    assert "<caption>Série de matrículas por ano censitário</caption>" in tabela
    for ano, valor in ((2023, "90"), (2024, "110"), (2025, "120")):
        assert f'<th scope="row">{ano}</th>' in tabela
        assert _celulas_da_linha(tabela, str(ano)) == [valor]


def test_svg_marca_ano_sem_dado_como_lacuna(client, repository):
    repository.history = _serie(
        2024,
        2025,
        overrides={
            2024: {"qt_mat_bas": None, "is_qt_mat_bas_missing": True},
            2025: {"qt_mat_bas": 120},
        },
    )

    html = _html(client.get(ESCOLA))

    svg = re.search(r"<svg[^>]*>.*?</svg>", html, flags=re.S)
    assert svg is not None
    # A lacuna não é uma barra de altura zero: é um traço próprio.
    assert svg.group(0).count("<rect") == 1
    assert svg.group(0).count('class="serie__ausente"') == 1


def test_serie_sem_nenhum_valor_nao_vira_zero(client, repository):
    repository.history = [
        history_row(
            nu_ano_censo=2025,
            tp_dependencia="3",
            qt_mat_bas=None,
            is_qt_mat_bas_missing=True,
        )
    ]

    html = _html(client.get(ESCOLA))

    assert "sem dado (is_qt_mat_bas_missing)" in html
    assert ">0<" not in html


def test_matricula_nula_nao_vira_zero_no_meio_da_serie(client, repository):
    repository.history = _serie(
        2024,
        2025,
        overrides={
            2024: {"qt_mat_bas": None, "is_qt_mat_bas_missing": True},
            2025: {"qt_mat_bas": 120},
        },
    )

    html = _html(client.get(ESCOLA))

    assert "sem dado (is_qt_mat_bas_missing)" in html
    assert ">0<" not in html


# -- oferta tri-estado ---------------------------------------------------------


def test_oferta_tri_estado_na_pagina(client, repository):
    repository.history = [
        history_row(
            tp_dependencia="3",
            of_pre=0,
            of_med=1,
            of_eja=None,
            is_oferta_desconhecida=True,
        )
    ]

    html = _html(client.get(ESCOLA))

    # Lê as células da tabela de oferta (não o texto explicativo do subtítulo).
    tabela = _tabela(html, "Oferta por etapa")
    assert _celulas_da_linha(tabela, "Pré-escola")[0] == "Não"
    assert _celulas_da_linha(tabela, "Ensino médio")[0] == "Sim"
    assert _celulas_da_linha(tabela, "EJA")[0] == "Desconhecido"
    # E6: a flag interna não aparece como texto; a explicação é em português.
    assert "is_oferta_desconhecida" not in html
    assert "Oferta desconhecida" in html


def _tabela(html: str, prefixo_caption: str) -> str:
    """`<table>` cuja `<caption>` contém `prefixo_caption`."""
    for tabela in re.findall(r"<table>.*?</table>", html, flags=re.S):
        if prefixo_caption in tabela:
            return tabela
    raise AssertionError(f"tabela ausente: {prefixo_caption!r}")


def _celulas_da_linha(tabela: str, rotulo: str) -> list[str]:
    """Texto de cada `<td>` da linha cujo `<th scope="row">` é `rotulo`."""
    linha = re.search(
        rf'<th scope="row">{re.escape(rotulo)}</th>(.*?)</tr>', tabela, flags=re.S
    )
    assert linha is not None, f"linha ausente na tabela: {rotulo!r}"
    return [
        re.sub(r"<[^>]+>", "", celula).strip()
        for celula in re.findall(r"<td>(.*?)</td>", linha.group(1), flags=re.S)
    ]


# -- meta obrigatória e vocabulário -------------------------------------------


def test_meta_mostra_ano_etapa_universo_fonte_e_avisos(client, repository):
    repository.history = [
        history_row(
            nu_ano_censo=2025,
            tp_dependencia="4",
            tp_situacao_funcionamento="1",
            n_etapas_metodologia_incomparavel=2,
        )
    ]

    html = _html(client.get(ESCOLA))

    # Ano censitário sai como ano (sem separador de milhar).
    assert re.search(r"<dt>Ano de referência</dt>\s*<dd>2025</dd>", html)
    assert "2.025" not in html
    assert "Educação básica (total)" in html
    assert "escolas_mg" in html
    assert "INEP" in html and "Censo Escolar" in html
    assert "mart_escola" in html
    assert "METODOLOGIA_INCOMPARAVEL_2025" in html


@pytest.mark.parametrize(
    ("valor", "esperado"), [(2025, "2025"), ("2025", "2025"), (None, "sem dado")]
)
def test_filtro_de_ano(valor, esperado):
    # Ano nunca sai com separador de milhar (2.025); ausência continua "sem dado".
    assert fmt_ano(valor) == esperado


def test_pagina_nao_usa_vocabulario_proibido(client, repository):
    repository.schools = [school_row()]
    repository.history = _serie(2025)
    repository.indicators = [indicator_row()]
    repository.competidores = [competidor_row()]

    html = _html(client.get(ESCOLA))

    for termo in TERMOS_PROIBIDOS:
        assert termo not in html.lower(), f"termo proibido no HTML: {termo!r}"

    # "evasão" só pode aparecer na negação exigida pelo rótulo do proxy:
    # nenhuma métrica é rotulada como taxa de evasão.
    assert html.count("evasão") == html.count("não é taxa de evasão") > 0


# -- erro de escola inexistente ------------------------------------------------


def test_escola_inexistente_vira_404_html(client, repository):
    resposta = client.get(ESCOLA)

    assert resposta.status_code == 404
    assert resposta.headers["cache-control"] == "no-store"
    assert "não encontrado" in _html(resposta, status=404).lower()
