"""Visão geral da ficha `/app/escolas/{co_entidade}` (cards F4/F11; NAV-2).

A ficha passou a ser a **Visão geral**: cabeçalho, identificação, oferta do ano
recente, série (SVG + tabela) e rendimento — tudo da resposta de
`get_school_history`, **uma** consulta. Indicadores e comparação municipal
vivem em `/app/escolas/{id}/concorrencia` (`test_web_concorrencia.py`).

Cobre o que o card exige como verificável sobre o HTML renderizado:

* privada ativa e pública/inativa → exatamente 1 chamada ao repositório;
* subnav sem JS: `<a>` + `aria-current="page"`, seção de concorrência só para
  escola privada ativa, link de saída para o mercado;
* nota "não se aplica" para pública/inativa, sem consultar as marts privadas;
* HTML ≤ 25 KB **e** menor que o baseline medido na `main` (13.732 B);
* `id`s `serie`, `oferta` e `rendimento` na ordem do contrato, com a linha
  "Nesta página:" apontando para eles;
* 503 em qualquer consulta → **página inteira 503** (`no-store`, `Retry-After`);
* série com SVG inline no servidor + tabela equivalente acessível;
* `null` → "sem dado" (com a flag de origem), oferta tri-estado;
* meta obrigatória (ano, etapa, universo, fonte, avisos) e vocabulário proibido;
* revalidação com `If-None-Match` → 304 sem consultar o repositório.
"""

from __future__ import annotations

import re

import pytest

from panorama_api.contract import OFERTA_ETAPAS
from panorama_api.core.errors import UpstreamUnavailable
from panorama_api.web.filters import fmt_ano
from tests.unit.conftest import history_row, school_row

ESCOLA = "/app/escolas/31000001"
#: Termos proibidos como vocabulário de comparação geográfica (escopo-adiado-v1).
TERMOS_PROIBIDOS = ("raio", "próximos", "proximos", "na região", "na regiao")
#: Chamadas ao repositório que só existem na rota de indicadores.
METODOS_PRIVADAS = ("get_school_indicators", "get_school_competidores", "get_school")
#: Rótulo do item ativo do subnav na Visão geral.
SUBNAV_VISAO_GERAL = '<a href="/app/escolas/31000001" aria-current="page">Visão geral</a>'

#: Teto de peso pedido pelo card (25 KB) e o baseline da ficha na `main` antes
#: desta entrega (medido com a fixture 31005371, `Accept-Encoding: identity`).
TETO_HTML_BYTES = 25 * 1024
BASELINE_FICHA_BYTES = 13_732

#: Escola real do card F11 (COL COTEMIG BARROCA, BH): `qt_mat_creche = 0`.
COTEMIG = "31005371"
COTEMIG_URL = f"/app/escolas/{COTEMIG}"


def _html(response, status: int = 200) -> str:
    assert response.status_code == status, response.text[:400]
    assert response.headers["content-type"].startswith("text/html")
    return response.text


def _leituras(repository) -> list[str]:
    """Leituras de dado da requisição (o `get_table_columns` é do boot)."""
    return [
        nome
        for nome in repository.methods_called()
        if nome != "get_table_columns"
    ]


def _serie(*anos: int, overrides: dict[int, dict] | None = None) -> list[dict]:
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


def _serie_cotemig() -> list[dict]:
    """Matrícula da 31005371 em 2025: 680 na básica, todo o médio em técnico."""
    return [
        history_row(
            co_entidade=COTEMIG,
            nu_ano_censo=2025,
            tp_dependencia="4",
            tp_situacao_funcionamento="1",
            qt_mat_bas=680,
            qt_mat_creche=0,
            qt_mat_pre=0,
            qt_mat_fund_ai=0,
            qt_mat_fund_af=0,
            qt_mat_med=680,
            qt_mat_prof=680,
            qt_mat_eja=0,
            qt_mat_esp=21,
            of_creche=0,
            of_pre=0,
            of_fund_ai=0,
            of_fund_af=0,
            of_med=1,
            of_prof=1,
            of_eja=0,
        )
    ]


def _cotemig(client, repository) -> str:
    """HTML da Visão geral da 31005371 (privada ativa, só o `history`)."""
    repository.schools = [
        school_row(co_entidade=COTEMIG, no_entidade="COL COTEMIG BARROCA")
    ]
    repository.history = _serie_cotemig()
    return _html(client.get(COTEMIG_URL))


# -- 1 consulta: a ficha não paga indicadores ao abrir ------------------------


def test_escola_privada_ativa_faz_uma_unica_consulta(client, repository):
    repository.history = _serie(2024, 2025)

    html = _html(client.get(ESCOLA))

    assert _leituras(repository) == ["get_school_history"]
    for metodo in METODOS_PRIVADAS:
        assert metodo not in _leituras(repository), metodo
    # A seção existe para esta escola: o subnav aponta para ela.
    assert '<a href="/app/escolas/31000001/concorrencia">Indicadores e concorrência</a>' in html
    assert "Série de matrículas" in html


def test_escola_publica_faz_uma_consulta_e_nao_linka_concorrencia(client, repository):
    repository.history = [
        history_row(tp_dependencia="3", tp_situacao_funcionamento="1")
    ]

    html = _html(client.get(ESCOLA))

    assert _leituras(repository) == ["get_school_history"]
    # A seção não existe para escola pública: nenhum link para a rota nova.
    assert "/concorrencia" not in html
    # A ausência é explicada na tela, não silenciada, e sem consulta extra.
    assert "Indicadores e concorrência: não se aplica a escola pública." in html


def test_escola_inativa_faz_uma_consulta_e_explica_a_ausencia(client, repository):
    repository.history = [
        history_row(tp_dependencia="4", tp_situacao_funcionamento="2")
    ]

    html = _html(client.get(ESCOLA))

    assert _leituras(repository) == ["get_school_history"]
    assert "/concorrencia" not in html
    assert "Indicadores e concorrência: não se aplica a escola inativa." in html


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

    html = _html(client.get(ESCOLA))

    assert _leituras(repository) == ["get_school_history"]
    assert "/concorrencia" not in html
    assert "não se aplica a escola pública" in html


def test_escola_sem_dependencia_declarada_nao_linka_nem_classifica(client, repository):
    """Campo nulo não vira "pública" nem "privada": a nota é a genérica."""
    repository.history = [
        history_row(tp_dependencia=None, tp_situacao_funcionamento="1")
    ]

    html = _html(client.get(ESCOLA))

    assert _leituras(repository) == ["get_school_history"]
    assert "/concorrencia" not in html
    # Nem "pública" nem "inativa" seriam verdadeiras: a nota genérica aparece.
    assert "Indicadores e comparação municipal existem apenas para escolas privadas ativas" in html
    assert "não se aplica a escola pública" not in html
    assert "não se aplica a escola inativa" not in html


# -- peso: 25 KB e menor que o baseline --------------------------------------


def test_html_da_visao_geral_cabe_no_orcamento_e_encolhe_contra_o_baseline(
    client, repository
):
    """Tirar indicadores e comparação da abertura encolhe a página de verdade."""
    repository.schools = [
        school_row(co_entidade=COTEMIG, no_entidade="COL COTEMIG BARROCA")
    ]
    repository.history = _serie_cotemig()

    resposta = client.get(COTEMIG_URL, headers={"Accept-Encoding": "identity"})
    tamanho = len(resposta.content)
    print(f"Visão geral da {COTEMIG}: {tamanho} B (baseline {BASELINE_FICHA_BYTES} B)")

    assert resposta.status_code == 200
    assert tamanho <= TETO_HTML_BYTES, f"{tamanho} B > {TETO_HTML_BYTES} B"
    assert tamanho < BASELINE_FICHA_BYTES, (
        f"{tamanho} B não encolheu contra o baseline de {BASELINE_FICHA_BYTES} B"
    )


# -- subnav e âncoras de seção -----------------------------------------------


def test_subnav_marca_a_visao_geral_como_pagina_atual(client, repository):
    repository.history = _serie(2025)

    html = _html(client.get(ESCOLA))

    assert '<nav class="subnav" aria-label="Seções da escola">' in html
    assert SUBNAV_VISAO_GERAL in html
    # O item ativo é "page" no subnav; `role="tablist"` não existe (sem JS/abas).
    assert 'role="tablist"' not in html
    assert '<a href="/app/mercados/3106200">Mercado de BELO HORIZONTE →</a>' in html


def test_visao_geral_tem_os_ids_de_contrato_na_ordem_e_ancoras(client, repository):
    html = _cotemig(client, repository)

    for ancora in ("#oferta", "#serie", "#rendimento"):
        assert f'href="{ancora}"' in html, ancora
    assert "Nesta página:" in html
    # A ordem é contrato: resumo → oferta → série → rendimento.
    posicoes = [html.index(f'id="{secao}"') for secao in ("oferta", "serie", "rendimento")]
    assert posicoes == sorted(posicoes), posicoes


def test_ids_de_contrato_sobrevivem_a_uma_serie_sem_oferta_nem_rendimento(
    client, repository
):
    """Com 200, as três âncoras de "Nesta página" sempre têm destino.

    ``#oferta`` só é renderizado quando há etapas a listar; a série sem oferta
    e sem rendimento é o caso extremo — o `id` continua lá (tabela com "sem
    dado"), então a âncora nunca aponta para o nada. Série **vazia** nem chega
    aqui: a rota responde 404 (não há ficha sem ano de referência).
    """
    repository.history = [
        history_row(
            nu_ano_censo=2025,
            tp_dependencia="4",
            tp_situacao_funcionamento="1",
            **{f"of_{etapa}": None for etapa in OFERTA_ETAPAS},
        )
    ]

    html = _html(client.get(ESCOLA))

    for secao in ("oferta", "serie", "rendimento"):
        assert f'id="{secao}"' in html, secao


# -- revalidação condicional: 304 sem consultar o repositório ----------------


def test_revalidacao_com_if_none_match_nao_consulta(client, repository):
    repository.history = _serie(2025)
    primeira = client.get(ESCOLA)
    assert primeira.status_code == 200
    etag = primeira.headers["etag"]

    repository.calls.clear()
    segunda = client.get(ESCOLA, headers={"If-None-Match": etag})

    assert segunda.status_code == 304
    assert repository.calls == []


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


# -- oferta tri-estado --------------------------------------------------------


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


# -- tabela de oferta: total, etapas e modalidades (F11) ---------------------

#: Grupos exigidos pelo card, na ordem, com as linhas de cada um.
GRUPOS_ESPERADOS = (
    ("Total oficial", ["Educação básica (total)"]),
    (
        "Etapas que somam ao total",
        [
            "Creche",
            "Pré-escola",
            "Ensino fundamental — anos iniciais",
            "Ensino fundamental — anos finais",
            "Ensino médio",
            "EJA",
        ],
    ),
    (
        "Modalidades e subconjuntos que não somam ao total",
        ["Educação profissional", "Educação especial"],
    ),
)


def _grupos_da_oferta(html: str) -> list[tuple[str, str]]:
    """(cabeçalho do grupo, corpo do `<tbody>`) da tabela de oferta, em ordem."""
    tabela = _tabela(html, "Oferta por etapa")
    grupos: list[tuple[str, str]] = []
    for corpo in re.findall(r"<tbody>(.*?)</tbody>", tabela, flags=re.S):
        cabecalho = re.search(r'scope="rowgroup">(.*?)</th>', corpo, flags=re.S)
        assert cabecalho is not None, "grupo sem cabeçalho na tabela de oferta"
        grupos.append((re.sub(r"<[^>]+>", "", cabecalho.group(1)).strip(), corpo))
    return grupos


def _rotulos_do_grupo(corpo: str) -> list[str]:
    """Rótulos das linhas de etapa de um `<tbody>` (exclui o cabeçalho)."""
    return [
        re.sub(r"<[^>]+>", "", rotulo).strip()
        for rotulo in re.findall(r'<th scope="row">(.*?)</th>', corpo, flags=re.S)
    ]


def test_tabela_de_oferta_separa_total_etapas_e_modalidades(client, repository):
    """31005371: as linhas somavam 2.061 alunos numa escola de 680."""
    html = _cotemig(client, repository)

    grupos = _grupos_da_oferta(html)
    assert [cabecalho.split(" — ")[0] for cabecalho, _ in grupos] == [
        titulo for titulo, _ in GRUPOS_ESPERADOS
    ]
    for (titulo, linhas), (_cabecalho, corpo) in zip(GRUPOS_ESPERADOS, grupos):
        assert _rotulos_do_grupo(corpo) == linhas, titulo

    # O total oficial (680) está sozinho: a soma ingênua das nove linhas é
    # exatamente os 2.061 do diagnóstico, e só o grupo de etapas é aditivo.
    soma_ingenua = sum(
        int(_celulas_da_linha(corpo, rotulo)[1])
        for _, corpo in grupos
        for rotulo in _rotulos_do_grupo(corpo)
    )
    assert soma_ingenua == 2061
    assert _celulas_da_linha(grupos[0][1], "Educação básica (total)") == ["Sim", "680"]
    assert "não é a soma" in grupos[0][0]
    assert "não somam ao total" in grupos[2][0]


def test_prof_e_esp_nao_sao_apresentados_como_etapa_aditiva(client, repository):
    """`prof`/`esp` ficam só nas modalidades: fora do grupo que soma ao total."""
    html = _cotemig(client, repository)

    grupos = {
        cabecalho.split(" — ")[0]: corpo for cabecalho, corpo in _grupos_da_oferta(html)
    }
    etapas = _rotulos_do_grupo(grupos["Etapas que somam ao total"])
    modalidades = _rotulos_do_grupo(
        grupos["Modalidades e subconjuntos que não somam ao total"]
    )

    for rotulo in ("Educação profissional", "Educação especial"):
        assert rotulo not in etapas, f"{rotulo} voltou a ser etapa aditiva"
        assert rotulo in modalidades


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
    repository.history = _serie(2025)

    html = _html(client.get(ESCOLA))

    for termo in TERMOS_PROIBIDOS:
        assert termo not in html.lower(), f"termo proibido no HTML: {termo!r}"


# -- erro de escola inexistente ------------------------------------------------


def test_escola_inexistente_vira_404_html(client, repository):
    resposta = client.get(ESCOLA)

    assert resposta.status_code == 404
    assert resposta.headers["cache-control"] == "no-store"
    assert "não encontrado" in _html(resposta, status=404).lower()
