"""Tabelas completas ordenáveis no cliente (card `t_ee9b1eec`; spec §2/§4/§5).

O pytest prova o **contrato do markup** que o JS consome; o comportamento da
ordenação (ordem das linhas, `aria-sort`, alvo de 44 px, teclado, sem JS) é
evidência de navegador anexada ao card, porque o CI é Python (spec §9).

O que fica travado aqui, sobre o HTML renderizado de verdade (``TestClient`` +
repositório fake):

* só **T3** (ficha, rendimento por ano) tem `data-ordenavel` — a composição do
  mercado virou o `ul.composicao` do protótipo no card D1-E3 (barras com
  `data-largura`, sem tabela e sem ordenação) e a oferta por etapa é o
  `div.grupos-oferta` do protótipo (rodada 1 da revisão, item 5);
* as colunas ordenáveis têm `data-tipo="numero"` e cada célula delas carrega
  `data-valor` com o valor **bruto** (ponto decimal), nunca o texto formatado
  (`1.234,5` não é número em JavaScript);
* célula sem dado: `data-valor=""` e continua exibindo "sem dado" — ausência
  nunca vira zero;
* linhas `data-fixa` (cabeçalho de grupo e total oficial) marcadas para o JS
  não as mover;
* nenhum `<button>` no HTML do servidor dentro de `<th>` (o botão nasce no JS,
  que é progressive enhancement) e nenhum `aria-sort` onde a ordem inicial não
  é de coluna (T2); `aria-sort="ascending"` só no Ano de T3.
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
BUSCA = "/app/"
ANOS = (2021, 2022, 2023, 2024, 2025)

#: Legendas (`<caption>`) das tabelas do card. A legenda é o que identifica a
#: tabela no HTML — nenhum teste depende da posição dela na página.
LEGENDA_T3 = "Rendimento escolar por ano censitário"

#: Tabelas fora da lista do card (rejeitadas na spec §2): não ordenam.
#: As tabelas de cobertura (T6) e movimento (T7) do mercado saíram no card
#: D1-E3 (o protótipo usa `nota-metodo`/`definicao` e `ul.ranking`).
LEGENDAS_SEM_ORDENACAO = (
    "Série de matrículas por ano censitário",  # T1
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
        "busca": _html(client.get(f"{BUSCA}?q=modelo")),
    }


# -- composição: lista do protótipo, sem tabela e sem ordenação (D1-E3) -------


def test_composicao_e_lista_com_barras_sem_tabela_ordenavel(
    mercado_html: str,
) -> None:
    """A composição é `ul.composicao` (5 etapas), com `data-largura` (D9).

    A tabela ordenável T5 saiu com o porte para o DOM do protótipo: nada de
    `table`, `data-ordenavel`, `data-tipo`, `data-valor`, `data-fixa` nem
    `aria-sort` nesta seção — a largura das barras vem de `aplicarBarras`.
    """
    secao = mercado_html.split('id="composicao"')[-1].split("</section>")[0]

    assert '<ul class="composicao" id="composicao-etapas">' in secao
    assert secao.count("<li>") == 5
    assert 'data-largura="' in secao
    assert "<table" not in secao
    assert "data-ordenavel" not in secao
    assert "data-tipo" not in secao
    assert "data-valor" not in secao
    assert "data-fixa" not in secao
    assert "aria-sort" not in secao


def test_composicao_valores_formatados_e_sem_dado(mercado_html: str) -> None:
    """Matrícula com milhar + % com 1 casa; etapa sem valor vira `sem dado`.

    A fixture tem creche com 2.000 (13,3% do total `bas`) e med sem matrícula:
    a barra de creche existe, a de med não — ausência nunca vira zero (`bas`
    é o total oficial e fica fora do gráfico, decisão D9).
    """
    secao = mercado_html.split('id="composicao-etapas"')[-1].split("</ul>")[0]

    assert "2.000 <small>13,3%</small>" in secao
    assert '<span class="sem-dado">sem dado</span>' in secao
    assert secao.count("comp-preenche") == 1
    assert "data-ordenavel" not in mercado_html
    assert "data-fixa" not in mercado_html


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


# -- oferta: grupos do protótipo, sem tabela e sem ordenação ------------------


def test_oferta_usa_os_grupos_do_prototipo(ficha: str) -> None:
    """Oferta por etapa é `div.grupos-oferta`, não tabela (revisão, item 5).

    Três grupos (total oficial, etapas que somam, modalidades que não somam);
    o total traz a matrícula e cada etapa traz o estado da oferta em
    `data-estado` — o `celulaOferta` do `app.js` do protótipo, em SSR.
    """
    assert 'class="grupos-oferta"' in ficha
    assert ficha.count("grupo-oferta__titulo") == 3
    # Total oficial do ano de referência, com separador de milhar.
    assert "1.320" in ficha
    secao = ficha.split('id="oferta"')[1].split("</section>")[0]
    # Nada de tabela ordenável na oferta: sem `th`, sem `aria-sort`.
    assert "<table" not in secao
    assert "data-ordenavel" not in secao
    assert "aria-sort" not in secao


def test_oferta_marca_o_estado_tri_estado_por_etapa(ficha: str) -> None:
    """Cada etapa carrega `sim` no `data-estado` (fixture toda ofertada)."""
    secao = ficha.split('id="oferta"')[1].split("</section>")[0]

    assert secao.count('data-estado="sim"') == 8
    assert 'data-estado="nao"' not in secao
    assert 'data-estado="desconhecido"' not in secao


# -- fora da lista: nenhuma tabela paginada ou natural ordena ----------------


def test_tabelas_fora_da_lista_nao_tem_data_ordenavel(paginas: dict[str, str]) -> None:
    for legenda in LEGENDAS_SEM_ORDENACAO:
        atributos, _corpo = _tabela(paginas["ficha"] + paginas["concorrencia"]
                                    + paginas["mercado"], legenda)
        assert "data-ordenavel" not in atributos, legenda

    # Busca e share do mercado são paginados: ordenar no cliente enganaria.
    assert "data-ordenavel" not in paginas["busca"]
    assert "data-ordenavel" not in paginas["mercado"]


def test_so_as_tabelas_do_card_ordenam(paginas: dict[str, str]) -> None:
    assert paginas["mercado"].count("data-ordenavel") == 0
    assert paginas["ficha"].count("data-ordenavel") == 1
    # `/concorrencia` é `301` para a ficha (card V2): o corpo é o mesmo, com a
    # mesma tabela ordenável (rendimento; a oferta virou grupos do protótipo).
    assert paginas["concorrencia"].count("data-ordenavel") == 1
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
