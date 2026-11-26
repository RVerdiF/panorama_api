"""Fidelidade dos dados na tela (card `t_ae1f7c43`, itens E2–E8).

Cobre cada item sobre o HTML renderizado de verdade (``TestClient`` + repositório
fake, sem rede/BigQuery):

* E2 — contagem nunca sai com ``,0`` (float integral vira inteiro);
* E3 — todo ano do intervalo da série aparece; ano sem registro na fonte é
  ``sem dado (ano ausente na fonte)``, nunca ausente da tabela e nunca ``0``;
* E4 — as contagens de escolas (município/ano) não se repetem por etapa;
* E5 — rótulos INEP completos (dependência 1–4, situação 1–4);
* E6 — nenhuma tela exibe `is_oferta_desconhecida` nem `IS_ABAIXO_PORTE` como
  texto; o leitor vê português;
* E7 — a metodologia lista e explica ``METODOLOGIA_INCOMPARAVEL_2025``;
* E8 — ``?ano=`` na ficha da escola é ``422``, não silêncio.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.main import create_app
from panorama_api.web.filters import fmt_contagem
from tests.unit.conftest import (
    FakeRepository,
    competidor_row,
    history_row,
    indicator_row,
    market_row,
    municipio_row,
    school_row,
    share_row,
)

ESCOLA = "/app/escolas/31000001"
MERCADO = "/app/mercados/3106200"
METODOLOGIA = "/app/metodologia"
BUSCA = "/app/"
ANOS = (2021, 2022, 2023, 2024, 2025)

#: Célula de contagem com ",0" no fim (``43,0``, ``172.322,0``) — o achado E2.
#: ``,0%`` é percentual (permitido): só a contagem é proibida de mostrar decimal.
CONTAGEM_COM_DECIMAL = re.compile(r"\d,0\b(?!%)")
#: Placeholder de serialização que nunca pode chegar ao HTML.
VAZAMENTO_PYTHON = re.compile(r"\bNone\b|\bnan\b")
#: Jargão interno que não pode aparecer como texto (achado E6).
JARGAO_INTERNO = ("is_oferta_desconhecida", "IS_ABAIXO_PORTE")


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


def _client(repository: FakeRepository) -> TestClient:
    return TestClient(create_app(settings=_settings(), repository=repository))


def _repo(**kwargs) -> FakeRepository:
    return FakeRepository(municipios=[municipio_row()], **kwargs)


def _html(response, status: int = 200) -> str:
    assert response.status_code == status, response.text[:600]
    assert response.headers["content-type"].startswith("text/html")
    return response.text


def _tabela(html: str, prefixo_caption: str) -> str:
    """`<table>` cuja `<caption>` contém `prefixo_caption`."""
    for tabela in re.findall(r"<table[^>]*>.*?</table>", html, flags=re.S):
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
        for celula in re.findall(r"<td[^>]*>(.*?)</td>", linha.group(1), flags=re.S)
    ]


def _serie(*anos: int, overrides: dict[int, dict] | None = None) -> list[dict]:
    valores = overrides or {}
    linhas = []
    for ano in anos:
        base = {
            "nu_ano_censo": ano,
            "tp_dependencia": "4",
            "tp_situacao_funcionamento": "1",
        }
        base.update(valores.get(ano, {}))
        linhas.append(history_row(**base))
    return linhas


# -- E2: contagem sem ",0" ----------------------------------------------------


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (43.0, "43"),
        (172322.0, "172.322"),
        (0.0, "0"),
        (43, "43"),
        (43.5, "43,5"),
        (None, "sem dado"),
        (True, "Sim"),
    ],
)
def test_filtro_de_contagem_nao_mostra_decimal_de_float_integral(valor, esperado):
    assert fmt_contagem(valor) == esperado


def test_filtro_de_contagem_preserva_o_motivo_da_ausencia():
    assert fmt_contagem(None, "is_qt_mat_bas_missing") == (
        "sem dado (is_qt_mat_bas_missing)"
    )


def test_percentual_continua_com_uma_casa():
    """`fmt_contagem` é só para contagem; percentual segue em `fmt_nulo`."""
    from panorama_api.web.filters import fmt_nulo

    assert fmt_nulo(30.0) == "30,0"


def test_mercado_nao_mostra_contagem_com_decimal_nas_celulas_de_contagem():
    """Fluxo anualizado devolve float; a célula de contagem não pode dizer ",0"."""
    repo = _repo(
        markets=[
            market_row(
                nu_ano_censo=2025,
                etapa="bas",
                n_escolas_entraram=43.0,
                n_escolas_ativas_com_baseline=172322.0,
                n_escolas_sairam=7.0,
                qt_mat_total=172322.0,
                qt_mat_privada=15000.0,
            ),
            market_row(nu_ano_censo=2025, etapa="creche"),
        ],
        share=[
            share_row(
                nu_ano_censo=2025,
                etapa="bas",
                mat_entidade=172322.0,
                share_privado_pct=8.7,
            )
        ],
    )
    cliente = _client(repo)

    html = _html(cliente.get(MERCADO))

    assert not CONTAGEM_COM_DECIMAL.search(html), CONTAGEM_COM_DECIMAL.search(html)
    # As contagens aparecem como inteiros; o percentual mantém a casa.
    assert ">172.322<" in html
    assert ">43<" in html
    # O percentual do share está no ranking da própria página (2 casas, D1-E3).
    assert "8,70%" in html


def test_mercado_formatos_de_contagem_em_todas_as_secoes_sem_decimal():
    repo = _repo(
        markets=[
            market_row(nu_ano_censo=ano, etapa=etapa)
            for ano in ANOS
            for etapa in ("bas", "med")
        ],
        share=[
            share_row(nu_ano_censo=2025, etapa="bas", mat_entidade=120.0)
            for _ in range(3)
        ],
    )

    html = _html(_client(repo).get(MERCADO))

    for tabela in re.findall(r"<table[^>]*>.*?</table>", html, flags=re.S):
        # Só as células: o texto do `<caption>`/`<th>` não é contagem.
        for celula in re.findall(r"<td[^>]*>(.*?)</td>", tabela, flags=re.S):
            texto = re.sub(r"<[^>]+>", "", celula).strip()
            if texto.endswith("%"):
                continue
            assert not CONTAGEM_COM_DECIMAL.search(texto), texto


# -- E3: ano ausente no meio da série ----------------------------------------


def test_ano_ausente_na_fonte_aparece_como_linha_sem_dado():
    repo = _repo(
        history=_serie(
            2020,
            2022,
            2023,
            overrides={
                2020: {"qt_mat_bas": 100},
                2022: {"qt_mat_bas": 120},
                2023: {"qt_mat_bas": 130},
            },
        )
    )

    html = _html(_client(repo).get(ESCOLA))

    tabela = _tabela(html, "Série de matrículas por ano")
    # O ano que existe no intervalo mas não na fonte continua visível.
    assert _celulas_da_linha(tabela, "2021") == ["sem dado (ano ausente na fonte)", "sem dado"]
    # E os anos observados mantêm seu valor — a lacuna não desalinha a série.
    assert _celulas_da_linha(tabela, "2020")[0] == "100"
    assert _celulas_da_linha(tabela, "2022")[0] == "120"
    assert _celulas_da_linha(tabela, "2023")[0] == "130"
    # Todos os anos do intervalo, em ordem (5 anos de 2020 a 2023 inclusive não
    # — 2020..2023 são 4 linhas).
    assert re.findall(r'<th scope="row">(20\d\d)</th>', tabela) == [
        "2020",
        "2021",
        "2022",
        "2023",
    ]


def test_ano_ausente_nunca_vira_zero_na_serie():
    repo = _repo(history=_serie(2023, 2025))

    html = _html(_client(repo).get(ESCOLA))

    tabela = _tabela(html, "Série de matrículas por ano")
    assert _celulas_da_linha(tabela, "2024") == ["sem dado (ano ausente na fonte)", "sem dado"]
    assert ">0<" not in tabela


def test_grafico_marca_o_ano_ausente_como_lacuna_e_nao_como_barra():
    repo = _repo(history=_serie(2023, 2025))

    html = _html(_client(repo).get(ESCOLA))

    svg = re.search(r"<svg[^>]*>.*?</svg>", html, flags=re.S)
    assert svg is not None
    # Três anos no eixo; duas barras (2023 e 2025) e uma lacuna (2024).
    assert svg.group(0).count("<rect") == 2
    assert svg.group(0).count('class="serie__ausente"') == 1


# -- E4: contagem de escolas não se repete por etapa -------------------------


def test_composicao_por_etapa_nao_repete_a_contagem_de_escolas():
    repo = _repo(
        markets=[
            # A mart repete o total municipal em todas as etapas: a tela não pode.
            market_row(nu_ano_censo=2025, etapa=etapa, n_escolas_ativas=100,
                       n_escolas_privadas=30)
            for etapa in ("bas", "creche", "med")
        ],
        share=[share_row(nu_ano_censo=2025, etapa="bas")],
    )

    html = _html(_client(repo).get(MERCADO))

    tabela = _tabela(html, "Tamanho do mercado por etapa")
    assert "Escolas ativas" not in tabela
    assert "Privadas ativas" not in tabela
    # O total aparece uma única vez, em "Tamanho do mercado".
    assert html.count("Escolas privadas ativas no município e ano") == 1
    assert html.count("Escolas ativas no município e ano (todas as dependências)") == 1
    # E a explicação de onde o total vive acompanha a tabela.
    assert "aparecem uma única vez em" in html


# -- E5: rótulos INEP completos ---------------------------------------------
#
# A ficha segue o protótipo e não tem bloco de definição; os rótulos vivem na
# tabela da busca (só "Privada", sem o código — D5), com a mesma leitura da
# ficha. Estes testes cobrem a leitura aqui.


@pytest.mark.parametrize(
    ("codigo", "esperado"),
    [
        ("1", "Federal"),
        ("2", "Estadual"),
        ("3", "Municipal"),
        ("4", "Privada"),
    ],
)
def test_rotulo_de_dependencia_usa_o_nome_do_codigo_inep(codigo, esperado):
    repo = _repo(
        schools=[
            school_row(tp_dependencia=codigo, tp_situacao_funcionamento="1")
        ]
    )

    html = _html(_client(repo).get(BUSCA, params={"co_municipio": "3106200"}))

    assert esperado in html
    assert f"{codigo} — {esperado}" not in html
    assert "não privada" not in html


@pytest.mark.parametrize(
    ("codigo", "esperado"),
    [
        ("1", "Em atividade"),
        ("2", "Paralisada"),
        ("3", "Extinta"),
        ("4", "Extinta no ano anterior"),
    ],
)
def test_rotulo_de_situacao_usa_o_nome_do_codigo_inep(codigo, esperado):
    repo = _repo(
        schools=[
            school_row(tp_dependencia="3", tp_situacao_funcionamento=codigo)
        ]
    )

    html = _html(_client(repo).get(BUSCA, params={"co_municipio": "3106200"}))

    assert esperado in html
    assert f"{codigo} — {esperado}" not in html
    # "não ativa" colapsava paralisada e extinta num único texto.
    assert "não ativa" not in html


def test_codigo_inep_ausente_nao_e_classificado_por_deducao():
    repo = _repo(
        schools=[
            school_row(tp_dependencia=None, tp_situacao_funcionamento=None)
        ]
    )

    html = _html(_client(repo).get(BUSCA, params={"co_municipio": "3106200"}))

    assert "não informado" in html
    assert "não privada" not in html


# -- E6: jargão interno fora das telas --------------------------------------


def _telas(repo: FakeRepository) -> dict[str, str]:
    client = _client(repo)
    return {
        "busca": _html(client.get(BUSCA, params={"co_municipio": "3106200"})),
        "escola": _html(client.get(ESCOLA)),
        "concorrencia": _html(client.get(f"{ESCOLA}/concorrencia")),
        "mercado": _html(client.get(MERCADO)),
        "metodologia": _html(client.get(METODOLOGIA)),
    }


def test_nenhuma_tela_exibe_jargao_interno_como_texto():
    repo = _repo(
        schools=[school_row(of_bas=None, is_oferta_desconhecida=True)],
        history=_serie(
            2025,
            overrides={2025: {"is_oferta_desconhecida": True}},
        ),
        indicators=[indicator_row(is_abaixo_porte=True)],
        competidores=[competidor_row()],
        markets=[market_row(nu_ano_censo=2025, etapa="bas")],
        share=[
            share_row(
                nu_ano_censo=2025,
                etapa="bas",
                id_entidade="31000002",
                is_abaixo_porte=True,
            )
        ],
    )

    for nome, html in _telas(repo).items():
        for jargao in JARGAO_INTERNO:
            assert jargao not in html, f"{jargao!r} visível na tela {nome!r}"

    telas = _telas(repo)
    # A D1-E3 tirou o marcador de porte do ranking do mercado (a classe `nota`
    # saiu do template); o aviso continua onde é regra: na concorrência.
    assert "abaixo do porte mínimo de comparabilidade" not in telas["mercado"]
    # O aviso de porte é dos indicadores: mora na rota de concorrência (NAV-2).
    assert "abaixo do porte mínimo de comparabilidade" in telas["concorrencia"]
    # A busca V3 não exibe marcador de oferta (D5); a ficha mantém o dela.
    assert "Oferta desconhecida" not in telas["busca"]
    assert "Oferta desconhecida" in telas["escola"]


# -- E7: metodologia explica o aviso de metodologia --------------------------


def test_metodologia_explica_metodologia_incomparavel_2025():
    html = _html(_client(_repo()).get(METODOLOGIA))

    assert "METODOLOGIA_INCOMPARAVEL_2025" in html
    # Explicação, não só o código.
    assert "não é diretamente comparável" in html
    assert "Educação profissional e EJA" in html
    # E o aviso de porte continua explicado.
    assert "porte mínimo de comparabilidade" in html
    assert "cautela" in html


# -- E8: ?ano= na ficha é 422 ----------------------------------------------


@pytest.mark.parametrize("ano", ["2020", "2025", "1999"])
def test_ano_na_ficha_da_escola_responde_422_sem_consultar_repositorio(ano):
    repo = _repo(history=_serie(2025))

    resposta = _client(repo).get(f"{ESCOLA}?ano={ano}")

    assert resposta.status_code == 422
    html = _html(resposta, status=422)
    assert "Parâmetro inválido" in html
    assert "ano" in html
    # Nada foi consultado: a recusa acontece antes do acesso a dado.
    assert not [nome for nome, _ in repo.calls if nome == "get_school_history"]


def test_ficha_sem_ano_continua_200():
    repo = _repo(history=_serie(2025))

    _html(_client(repo).get(ESCOLA), status=200)

    assert [nome for nome, _ in repo.calls if nome == "get_school_history"]


# -- critério transversal: nada de None/nan nas telas ------------------------


def test_nenhuma_tela_vaza_none_ou_nan():
    repo = _repo(
        schools=[school_row(no_entidade=None, no_municipio=None, of_bas=None)],
        history=_serie(
            2023,
            2025,
            overrides={
                2023: {"qt_mat_bas": None, "is_qt_mat_bas_missing": True},
                2025: {"tp_dependencia": "3", "tp_situacao_funcionamento": "1"},
            },
        ),
        markets=[
            market_row(
                nu_ano_censo=2025,
                etapa="bas",
                n_escolas_entraram=None,
                n_escolas_ativas_com_baseline=None,
                n_escolas_sairam=None,
            )
        ],
        share=[share_row(nu_ano_censo=2025, etapa="bas", share_privado_pct=None)],
    )

    for nome, html in _telas(repo).items():
        assert not VAZAMENTO_PYTHON.search(html), (
            nome,
            VAZAMENTO_PYTHON.search(html),
        )
