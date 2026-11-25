"""Tabelas completas ordenáveis no cliente (card `t_ee9b1eec`; spec §2/§4/§5).

O pytest prova o **contrato do markup** que o JS consome; o comportamento da
ordenação (ordem das linhas, `aria-sort`, alvo de 44 px, teclado, sem JS) é
evidência de navegador anexada ao card, porque o CI é Python (spec §9).

O que fica travado aqui, sobre o HTML renderizado de verdade (``TestClient`` +
repositório fake):

* só **T5** (mercado, composição por etapa), **T3** (ficha, rendimento por ano)
  e **T2** (ficha, oferta e matrícula por etapa) têm `data-ordenavel`;
* as colunas ordenáveis têm `data-tipo="numero"` e cada célula delas carrega
  `data-valor` com o valor **bruto** (ponto decimal), nunca o texto formatado
  (`1.234,5` não é número em JavaScript);
* célula sem dado: `data-valor=""` e continua exibindo "sem dado" — ausência
  nunca vira zero;
* linhas `data-fixa` (cabeçalho de grupo e total oficial) marcadas para o JS
  não as mover;
* nenhum `<button>` no HTML do servidor dentro de `<th>` (o botão nasce no JS,
  que é progressive enhancement) e nenhum `aria-sort` onde a ordem inicial não
  é de coluna (T5/T2); `aria-sort="ascending"` só no Ano de T3.
"""

from __future__ import annotations

import re

import pytest

from panorama_api.web.filters import fmt_bruto
from tests.unit.conftest import (
    competidor_row,
    concentracao_row,
    history_row,
    indicator_row,
    market_row,
    municipio_row,
    school_row,
    share_row,
)

ESCOLA = "31000001"
FICHA = f"/app/escolas/{ESCOLA}"
CONCORRENCIA = f"{FICHA}/concorrencia"
MUNICIPIO = "3106200"
MERCADO = f"/app/mercados/{MUNICIPIO}"
RANKING = f"{MERCADO}/escolas"
BUSCA = "/app/"
ANOS = (2021, 2022, 2023, 2024, 2025)

#: Legendas (`<caption>`) das tabelas do card. A legenda é o que identifica a
#: tabela no HTML — nenhum teste depende da posição dela na página.
LEGENDA_T5 = "Tamanho do mercado por etapa"
LEGENDA_T3 = "Rendimento escolar por ano censitário"
LEGENDA_T2 = "Oferta por etapa e matrícula observada"

#: Tabelas fora da lista do card (rejeitadas na spec §2): não ordenam.
#: A tabela de concorrentes por etapa saiu no card V2 `t_cbd54a92` (a ficha
#: passou a mostrar KPIs, posição e ranking em vez da lista por etapa).
LEGENDAS_SEM_ORDENACAO = (
    "Série de matrículas por ano censitário",  # T1
    "Cobertura de matrícula na etapa",  # T6
    "Movimento de escolas na etapa",  # T7
)

TABELA = re.compile(r"<table\b([^>]*)>(.*?)</table>", re.S)
CAPTION = re.compile(r"<caption>(.*?)</caption>", re.S)
LINHA = re.compile(r"<tr\b([^>]*)>(.*?)</tr>", re.S)
CELULA = re.compile(r"<(t[hd])\b([^>]*)>(.*?)</\1>", re.S)


def _html(resposta, status: int = 200) -> str:
    assert resposta.status_code == status, resposta.text[:600]
    assert resposta.headers["content-type"].startswith("text/html")
    return resposta.text


def _tabelas(html: str) -> list[tuple[str, str]]:
    """Todo `<table>` da página como `(atributos, corpo)`."""
    return [(m.group(1), m.group(2)) for m in TABELA.finditer(html)]


def _tabela(html: str, legenda: str) -> tuple[str, str]:
    """`(atributos, corpo)` da tabela cuja `<caption>` começa com `legenda`."""
    for atributos, corpo in _tabelas(html):
        recorte = CAPTION.search(corpo)
        if recorte is not None and recorte.group(1).strip().startswith(legenda):
            return atributos, corpo
    raise AssertionError(f"tabela não renderizada: {legenda}")


def _corpo_tabela(corpo: str) -> str:
    """Só o `<tbody>` (as linhas de dado, sem o cabeçalho)."""
    return corpo[corpo.index("<tbody") :]


def _linhas(corpo: str) -> list[tuple[str, list[tuple[str, str, str]]]]:
    """Linhas do corpo como `(atributos do <tr>, [(tag, atributos, texto)])`."""
    linhas = []
    for achado in LINHA.finditer(_corpo_tabela(corpo)):
        celulas = [
            (c.group(1), c.group(2), c.group(3).strip())
            for c in CELULA.finditer(achado.group(2))
        ]
        linhas.append((achado.group(1), celulas))
    return linhas


def _valores(celulas: list[tuple[str, str, str]]) -> list[str | None]:
    """`data-valor` de cada célula da linha (`None` onde não há o atributo).

    Devolver `None` — e não `""` — deixa o teste distinguir "célula fora da
    ordenação" de "célula ordenável sem dado" (`data-valor=""`).
    """
    valores = []
    for _tag, attrs, _ in celulas:
        achado = re.search(r'data-valor="([^"]*)"', attrs)
        valores.append(achado.group(1) if achado else None)
    return valores


def _linha_de(linhas, rotulo: str):
    for atributos, celulas in linhas:
        if celulas and rotulo in celulas[0][2]:
            return atributos, celulas
    raise AssertionError(f"linha não renderizada: {rotulo}")


# -- fixtures: as três tabelas do card e as páginas com tabela sem ordenação ---


def _ficha_do_mesmo_ano() -> list[dict]:
    """Ficha de uma privada ativa; uma etapa sem dado e uma taxa sem dado."""
    return [
        history_row(
            nu_ano_censo=2024,
            tp_dependencia="4",
            tp_situacao_funcionamento="1",
            qt_mat_bas=1_200,
            qt_mat_creche=None,
            is_qt_mat_creche_missing=True,
            tx_aprov_fund_t=87.5,
            tx_aprov_fund_ai=None,
            is_tx_aprov_fund_ai_missing=True,
        ),
        history_row(
            nu_ano_censo=2025,
            tp_dependencia="4",
            tp_situacao_funcionamento="1",
            qt_mat_bas=1_320,
            qt_mat_creche=40,
            tx_aprov_fund_t=91.25,
            tx_aprov_fund_ai=88.0,
        ),
    ]


def _mercado() -> list[dict]:
    """Composição com uma etapa sem matrícula privada e uma sem total."""
    return [
        market_row(nu_ano_censo=2025, etapa="bas"),
        market_row(
            nu_ano_censo=2025,
            etapa="med",
            qt_mat_total=None,
            qt_mat_privada=None,
            pct_privada_no_total_pct=None,
        ),
        market_row(
            nu_ano_censo=2025,
            etapa="creche",
            qt_mat_total=8000.0,
            qt_mat_privada=2000.0,
            pct_privada_no_total_pct=25.0,
        ),
    ]


@pytest.fixture
def ficha(client, repository) -> str:
    repository.schools = [school_row(co_entidade=ESCOLA)]
    repository.history = _ficha_do_mesmo_ano()
    return _html(client.get(FICHA))


@pytest.fixture
def mercado_html(client, repository) -> str:
    repository.municipios = [municipio_row()]
    repository.markets = _mercado()
    repository.concentracao = [concentracao_row(nu_ano_censo=2025)]
    return _html(client.get(MERCADO))


@pytest.fixture
def paginas(client, repository) -> dict[str, str]:
    """Uma página por tabela: as do card e as que não podem ordenar."""
    repository.schools = [school_row(co_entidade=ESCOLA, no_entidade="ESCOLA MODELO")]
    repository.history = _ficha_do_mesmo_ano()
    repository.indicators = [indicator_row()]
    repository.competidores = [competidor_row()]
    repository.municipios = [municipio_row()]
    repository.markets = _mercado()
    repository.concentracao = [concentracao_row(nu_ano_censo=2025)]
    repository.share = [
        share_row(nu_ano_censo=2025, etapa="bas", id_entidade="31000001"),
    ]
    return {
        "ficha": _html(client.get(FICHA)),
        "concorrencia": _html(client.get(CONCORRENCIA)),
        "mercado": _html(client.get(MERCADO)),
        "ranking": _html(client.get(RANKING)),
        "busca": _html(client.get(f"{BUSCA}?q=modelo")),
    }


# -- T5: mercado, composição por etapa ---------------------------------------


def test_t5_declara_as_tres_colunas_ordenaveis(mercado_html: str) -> None:
    atributos, corpo = _tabela(mercado_html, LEGENDA_T5)

    assert "data-ordenavel" in atributos
    for rotulo in ("Matrícula total", "Matrícula privada", "Privada no total"):
        assert f'<th scope="col" data-tipo="numero">{rotulo}</th>' in corpo, rotulo
    # A coluna de etapa não ordena: ordem canônica do servidor.
    assert '<th scope="col">Etapa</th>' in corpo
    # T5 não tem ordem de coluna inicial: nada de `aria-sort` no HTML.
    assert "aria-sort" not in corpo


def test_t5_guarda_o_valor_bruto_nao_o_texto_formatado(mercado_html: str) -> None:
    _atributos, corpo = _tabela(mercado_html, LEGENDA_T5)
    linhas = _linhas(corpo)

    # `mart_mercado` devolve float integral: 50.000 na tela, 50000.0 no dado.
    _tr, celulas = _linha_de(linhas, "Educação básica")
    assert _valores(celulas) == [None, "50000.0", "15000.0", "30.0"]
    assert celulas[1][2] == "50.000"
    assert celulas[3][2] == "30,0%"
    assert "50.000" not in celulas[1][1], "o texto formatado não pode ir em data-valor"

    # Etapa sem dado: `data-valor=""` e o texto continua "sem dado".
    _tr, celulas = _linha_de(linhas, "Ensino médio")
    assert _valores(celulas) == [None, "", "", ""]
    assert all("sem dado" in celula[2] for celula in celulas[1:])


def test_t5_marca_so_o_total_oficial_como_data_fixa(mercado_html: str) -> None:
    """O total oficial (`bas`) não é etapa do mercado: não se move na ordenação.

    A marcação vem da chave da etapa no dado (`ETAPA_PADRAO_MERCADO`), não do
    rótulo renderizado — trocar o texto de "Educação básica (total)" não pode
    tirar a linha da posição original.
    """
    _atributos, corpo = _tabela(mercado_html, LEGENDA_T5)
    linhas = _linhas(corpo)

    atributos_fixa, _celulas = _linha_de(linhas, "Educação básica (total)")
    assert "data-fixa" in atributos_fixa

    # Nenhuma outra linha da composição é fixa: só o total oficial.
    fixas = [celulas[0][2] for atributos, celulas in linhas if "data-fixa" in atributos]
    assert fixas == ["Educação básica (total)"]


# -- T3: ficha, rendimento por ano -------------------------------------------


def test_t3_ordena_ano_e_cada_taxa_e_declara_a_ordem_inicial(ficha: str) -> None:
    atributos, corpo = _tabela(ficha, LEGENDA_T3)

    assert "data-ordenavel" in atributos
    # Ordem inicial cronológica: o servidor já diz isso (verdade sem JS).
    assert '<th scope="col" data-tipo="numero" aria-sort="ascending">Ano</th>' in corpo
    for rotulo in (
        "Aprovação — fundamental (total)",
        "Aprovação — anos iniciais",
        "Reprovação — fundamental (total)",
        "Abandono — fundamental (total)",
    ):
        assert f'<th scope="col" data-tipo="numero">{rotulo}</th>' in corpo, rotulo


def test_t3_cada_celula_tem_o_valor_bruto_e_ausencia_vazia(ficha: str) -> None:
    _atributos, corpo = _tabela(ficha, LEGENDA_T3)
    linhas = _linhas(corpo)

    _atributos_2024, celulas = _linha_de(linhas, "2024")
    assert _valores(celulas) == ["2024", "87.5", "", "", "", "", ""]
    assert 'data-valor="2024"' in celulas[0][1]
    assert celulas[1][2] == "87,5%"
    assert celulas[2][2].startswith("sem dado")

    _atributos_2025, celulas = _linha_de(linhas, "2025")
    assert _valores(celulas)[:3] == ["2025", "91.25", "88.0"]
    assert celulas[2][2] == "88,0%"


# -- T2: ficha, oferta e matrícula por etapa ---------------------------------


def test_t2_ordena_so_a_matricula_e_respeita_os_grupos(ficha: str) -> None:
    atributos, corpo = _tabela(ficha, LEGENDA_T2)

    assert "data-ordenavel" in atributos
    assert '<th scope="col" data-tipo="numero">Matrícula</th>' in corpo
    # Oferta é tri-estado: não ordena.
    assert '<th scope="col">Oferta</th>' in corpo
    assert "aria-sort" not in corpo

    # Ordem canônica de etapa: nenhum `aria-sort` inicial, mas toda linha de
    # grupo é `data-fixa`, assim como a linha do total oficial.
    assert corpo.count('class="grupo-etapas" data-fixa') == 3
    _tr_total, celulas = _linha_de(_linhas(corpo), "Educação básica (total)")
    assert celulas[2][2] == "1.320"
    assert re.search(r'<tr data-fixa>\s*<th scope="row">Educação básica', corpo)


def test_t2_guarda_o_valor_bruto_e_a_ausencia_vazia(ficha: str) -> None:
    _atributos, corpo = _tabela(ficha, LEGENDA_T2)
    linhas = _linhas(corpo)

    _tr, celulas = _linha_de(linhas, "Creche")
    assert celulas[2][2] == "40"
    assert 'data-valor="40"' in celulas[2][1]

    # 2024 tem creche sem dado (flag de origem), 2025 tem 40: o último item da
    # série é o que a tabela de oferta mostra — a ausência não virou zero.
    assert "sem dado" not in celulas[2][2]


# -- fora da lista: nenhuma tabela paginada ou natural ordena ----------------


def test_tabelas_fora_da_lista_nao_tem_data_ordenavel(paginas: dict[str, str]) -> None:
    for legenda in LEGENDAS_SEM_ORDENACAO:
        atributos, _corpo = _tabela(paginas["ficha"] + paginas["concorrencia"]
                                    + paginas["mercado"], legenda)
        assert "data-ordenavel" not in atributos, legenda

    # Busca e ranking de share são paginados: ordenar no cliente enganaria.
    for pagina in ("ranking", "busca"):
        assert "data-ordenavel" not in paginas[pagina], pagina


def test_so_as_tres_tabelas_do_card_ordenam(paginas: dict[str, str]) -> None:
    assert paginas["mercado"].count("data-ordenavel") == 1
    assert paginas["ficha"].count("data-ordenavel") == 2
    # `/concorrencia` é `301` para a ficha (card V2): o corpo é o mesmo, com as
    # mesmas duas tabelas ordenáveis.
    assert paginas["concorrencia"].count("data-ordenavel") == 2
    assert paginas["ranking"].count("data-ordenavel") == 0
    assert paginas["busca"].count("data-ordenavel") == 0


# -- progressive enhancement: o botão e o `aria-sort` são do JS --------------


def test_servidor_nao_renderiza_botao_dentro_de_th(paginas: dict[str, str]) -> None:
    for nome, html in paginas.items():
        for celula in re.finditer(r"<th\b[^>]*>(.*?)</th>", html, re.S):
            assert "<button" not in celula.group(1), f"{nome}: botão no <th> do servidor"


# -- filtro do valor bruto ---------------------------------------------------


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (None, ""),
        (True, ""),
        (False, ""),
        (0, "0"),
        (1_200, "1200"),
        (87.5, "87.5"),
        (30.0, "30.0"),
        (" 2024 ", "2024"),
    ],
)
def test_fmt_bruto_leva_o_numero_cru_e_ausencia_como_string_vazia(
    valor, esperado: str
) -> None:
    assert fmt_bruto(valor) == esperado
