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
from tests.unit.conftest import history_row, indicator_row, school_row

ESCOLA = "/app/escolas/31000001"
#: Termos proibidos como vocabulário de comparação geográfica (escopo-adiado-v1).
TERMOS_PROIBIDOS = ("raio", "próximos", "proximos", "na região", "na regiao")
#: Chamadas ao repositório que só existem na rota de indicadores.
METODOS_PRIVADAS = ("get_school_indicators", "get_school_competidores", "get_school")
#: Rótulo do item ativo do subnav na Visão geral (âncora interna, card V2).
SUBNAV_VISAO_GERAL = '<a href="#resumo" aria-current="page">Visão geral</a>'

#: Teto de peso da ficha fundida (KPIs + série + oferta/rendimento + posição +
#: ranking): card V2 `t_cbd54a92`. A ficha deixou de ser "só o history".
TETO_HTML_BYTES = 40 * 1024

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


def test_escola_privada_ativa_faz_historico_e_indicadores(client, repository):
    repository.history = _serie(2024, 2025)
    repository.indicators = [indicator_row()]

    html = _html(client.get(ESCOLA))

    # Card V2: a ficha fundiu a Visão geral e os indicadores/concorrência —
    # `history` alimenta série/oferta/rendimento; `indicators` alimenta KPIs,
    # posição e ranking. Nenhuma leitura de identidade (`get_school`).
    leituras = _leituras(repository)
    assert leituras[0] == "get_school_history"
    assert "get_school_indicators" in leituras
    assert "get_school" not in leituras
    # A seção existe para esta escola: o subnav aponta para a âncora.
    assert '<a href="#concorrencia">Indicadores e concorrência</a>' in html
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


def test_html_da_visao_geral_cabe_no_orcamento(client, repository):
    """A ficha fundida (KPIs + série + oferta/rendimento + posição + ranking)
    cabe no orçamento de peso do front."""
    repository.schools = [
        school_row(co_entidade=COTEMIG, no_entidade="COL COTEMIG BARROCA")
    ]
    repository.history = _serie_cotemig()
    repository.indicators = [indicator_row(co_entidade=COTEMIG)]

    resposta = client.get(COTEMIG_URL, headers={"Accept-Encoding": "identity"})
    tamanho = len(resposta.content)
    print(f"Ficha da {COTEMIG}: {tamanho} B")

    assert resposta.status_code == 200
    assert tamanho <= TETO_HTML_BYTES, f"{tamanho} B > {TETO_HTML_BYTES} B"


# -- subnav e âncoras de seção -----------------------------------------------


def test_subnav_marca_a_visao_geral_como_pagina_atual(client, repository):
    repository.history = _serie(2025)

    html = _html(client.get(ESCOLA))

    assert '<nav class="subnav" aria-label="Seções da escola">' in html
    assert SUBNAV_VISAO_GERAL in html
    # Âncoras diretas, como o protótipo (sem `ul/li`); o item ativo é "page" no
    # subnav; `role="tablist"` não existe (sem JS/abas).
    subnav = re.search(r'<nav class="subnav".*?</nav>', html, flags=re.S)
    assert subnav is not None
    assert "<ul>" not in subnav.group(0)
    assert "<li>" not in subnav.group(0)
    assert 'role="tablist"' not in html
    assert '<a href="#concorrencia">Indicadores e concorrência</a>' in html
    assert '<a href="/app/mercados/3106200" class="subnav__saida">Mercado de BELO HORIZONTE →</a>' in html


def test_visao_geral_tem_os_ids_de_contrato_na_ordem_e_ancoras(client, repository):
    html = _cotemig(client, repository)

    # Card V2: o subnav aponta para as âncoras internas, não para rotas.
    for ancora in ("#resumo", "#concorrencia"):
        assert f'href="{ancora}"' in html, ancora
    # A ordem é contrato: resumo → série → oferta → rendimento → concorrência.
    posicoes = [
        html.index(f'id="{secao}"')
        for secao in ("resumo", "serie", "oferta", "rendimento", "concorrencia")
    ]
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
    # Card V2: a tabela da série ganhou a coluna "Variação anual". No primeiro
    # ano observado não há ano anterior → "sem dado".
    for ano, valor, variacao in ((2023, "90", "sem dado"), (2024, "110", "+22,2%"), (2025, "120", "+9,1%")):
        assert f'<th scope="row">{ano}</th>' in tabela
        assert _celulas_da_linha(tabela, str(ano)) == [valor, variacao]


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

    # Lê os grupos de oferta (não o texto explicativo da nota de método).
    assert _oferta_da_etapa(html, "Pré-escola") == "Não"
    assert _oferta_da_etapa(html, "Ensino médio") == "Sim"
    assert _oferta_da_etapa(html, "EJA") == "Desconhecido"
    # E6: a flag interna não aparece como texto; a explicação é em português.
    assert "is_oferta_desconhecida" not in html
    assert "Oferta desconhecida" in html


def _oferta_da_etapa(html: str, rotulo: str) -> str:
    """Texto do `<dd>` da etapa nos `div.grupos-oferta` (sem a marcação)."""
    trecho = re.search(
        rf"<dt>{re.escape(rotulo)}</dt><dd>(.*?)</dd>", html, flags=re.S
    )
    assert trecho is not None, f"etapa ausente nos grupos: {rotulo!r}"
    return re.sub(r"<[^>]+>", "", trecho.group(1)).strip()


def _tabela(html: str, prefixo_caption: str) -> str:
    """`<table>` cuja `<caption>` contém `prefixo_caption`.

    A abertura aceita atributos: a tabela de oferta passou a declarar
    `data-ordenavel` (card `t_ee9b1eec`) e o recorte por `<table>` exato
    deixaria de encontrá-la.
    """
    for tabela in re.findall(r"<table\b[^>]*>.*?</table>", html, flags=re.S):
        if prefixo_caption in tabela:
            return tabela
    raise AssertionError(f"tabela ausente: {prefixo_caption!r}")


def _celulas_da_linha(tabela: str, rotulo: str) -> list[str]:
    """Texto de cada `<td>` da linha cujo `<th scope="row">` é `rotulo`.

    O `<td>` pode carregar atributos — `data-valor` nas colunas ordenáveis
    (card `t_ee9b1eec`) —, por isso o recorte aceita o que vier na abertura.
    """
    linha = re.search(
        rf'<th scope="row">{re.escape(rotulo)}</th>(.*?)</tr>', tabela, flags=re.S
    )
    assert linha is not None, f"linha ausente na tabela: {rotulo!r}"
    return [
        re.sub(r"<[^>]+>", "", celula).strip()
        for celula in re.findall(r"<td\b[^>]*>(.*?)</td>", linha.group(1), flags=re.S)
    ]


# -- grupos de oferta: total, etapas e modalidades (F11) ----------------------

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
    """(título do grupo, corpo do `<dl>`) dos `div.grupos-oferta`, em ordem."""
    secao = html.split('id="oferta"')[1].split("</section>")[0]
    grupos: list[tuple[str, str]] = []
    for bloco in re.findall(
        r'<div class="grupo-oferta[^"]*">(.*?)</div>\s*(?=<div class="grupo-oferta|</div>\s*</section>|<div class="nota-metodo)',
        secao,
        flags=re.S,
    ):
        titulo = re.search(
            r'<p class="grupo-oferta__titulo">\s*(.*?)\s*<small>(.*?)</small>',
            bloco,
            flags=re.S,
        )
        assert titulo is not None, "grupo sem título na oferta"
        corpo = re.search(r"<dl[^>]*>(.*?)</dl>", bloco, flags=re.S)
        assert corpo is not None, "grupo sem lista na oferta"
        grupos.append(
            (
                re.sub(r"<[^>]+>", "", titulo.group(1)).strip()
                + " — "
                + re.sub(r"<[^>]+>", "", titulo.group(2)).strip(),
                corpo.group(1),
            )
        )
    return grupos


def _rotulos_do_grupo(corpo: str) -> list[str]:
    """Rótulos das etapas de um `<dl>` de grupo."""
    return [
        re.sub(r"<[^>]+>", "", rotulo).strip()
        for rotulo in re.findall(r"<dt>(.*?)</dt>", corpo, flags=re.S)
    ]


def _valor_do_total(corpo: str, rotulo: str) -> str:
    """Texto do `<dd>` do total oficial (matrícula, sem marcação)."""
    trecho = re.search(
        rf"<dt>{re.escape(rotulo)}</dt><dd[^>]*>(.*?)</dd>", corpo, flags=re.S
    )
    assert trecho is not None, f"total ausente nos grupos: {rotulo!r}"
    return re.sub(r"<[^>]+>", "", trecho.group(1)).strip()


def test_grupos_de_oferta_separam_total_etapas_e_modalidades(client, repository):
    """31005371: o total oficial (680) aparece uma vez; etapas e modalidades
    trazem só o estado da oferta — a soma ingênua das nove linhas (2.061)
    não tem mais onde acontecer."""
    html = _cotemig(client, repository)

    grupos = _grupos_da_oferta(html)
    assert [cabecalho.split(" — ")[0] for cabecalho, _ in grupos] == [
        titulo for titulo, _ in GRUPOS_ESPERADOS
    ]
    for (titulo, linhas), (_cabecalho, corpo) in zip(GRUPOS_ESPERADOS, grupos):
        assert _rotulos_do_grupo(corpo) == linhas, titulo

    # O total oficial (680) está sozinho no grupo do total.
    assert _valor_do_total(grupos[0][1], "Educação básica (total)") == "680"
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
