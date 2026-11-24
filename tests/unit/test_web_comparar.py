"""Comparação entre duas escolas — `/app/comparar?escolas=` (card C4, `t_58f9adbb`).

Cobre o que o card exige como verificável sobre o HTML renderizado de verdade
(``TestClient`` + repositório fake, sem rede/BigQuery):

* `?escolas=B,A` → **308** para a URL canônica `?escolas=A,B`, sem consultar o
  repositório; id repetido, lista vazia, três ids e id fora do formato → ``422``
  HTML; escola inexistente → ``404`` HTML do front;
* uma comparação com dois ids consulta o repositório **exatamente duas vezes**
  (série + oferta de cada escola saem do mesmo `get_school_history`), e a
  revalidação por `If-None-Match` responde ``304`` sem nenhuma chamada;
* a tabela tem as colunas Ano | A | B cobrindo a **união dos intervalos**; ano
  ausente em uma das escolas é "sem dado" com motivo, nunca zero; o SVG é
  `aria-hidden` e distingue as duas séries por classe (sólido × contorno);
* a oferta por etapa usa o ano mais recente **comum**, e sem ano comum a seção
  diz por quê em vez de escolher o ano de uma das escolas;
* a ficha tem o link de entrada e a página com um id tem o formulário de busca,
  cujos resultados linkam para a URL canônica;
* nada de `<script>` inline, `style=` ou `on*=` nas duas páginas novas.
"""

from __future__ import annotations

import re

import pytest

from tests.unit.conftest import FakeRepository, history_row, school_row

COMPARAR = "/app/comparar"

ESCOLA_A = "31000001"
ESCOLA_B = "31000002"
ESCOLA_C = "31000003"
INEXISTENTE = "99999999"

MUNICIPIO_A = "3106200"  # BELO HORIZONTE (o de `school_row`)
MUNICIPIO_C = "3100104"  # outro município de MG


def _url(*ids: str) -> str:
    return f"{COMPARAR}?escolas={','.join(ids)}"


def _settings():
    from panorama_api.config import Settings

    return Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        max_bytes_billed=256 * 1024 * 1024,
        validate_schema_on_startup=False,
        contract_version="mvp-1",
        data_version="dev",
        app_anos_disponiveis="2021,2022,2023,2024,2025",
    )


def _repositorio() -> FakeRepository:
    """A em BH (2021–2023, com lacuna em 2023) e B no mesmo município (2022–2024)."""
    return FakeRepository(
        schools=[
            school_row(co_entidade=ESCOLA_A, no_entidade="ESCOLA MODELO"),
            school_row(co_entidade=ESCOLA_B, no_entidade="ESCOLA CONCORRENTE"),
            school_row(
                co_entidade=ESCOLA_C,
                no_entidade="ESCOLA DE OUTRO MUNICÍPIO",
                co_municipio=MUNICIPIO_C,
                no_municipio="OUTRO MUNICÍPIO",
            ),
        ],
        history=[
            history_row(
                co_entidade=ESCOLA_A,
                no_entidade="ESCOLA MODELO",
                nu_ano_censo=2021,
                tp_dependencia="4",
                qt_mat_bas=100,
            ),
            history_row(
                co_entidade=ESCOLA_A,
                no_entidade="ESCOLA MODELO",
                nu_ano_censo=2022,
                tp_dependencia="4",
                qt_mat_bas=120,
            ),
            history_row(
                co_entidade=ESCOLA_A,
                no_entidade="ESCOLA MODELO",
                nu_ano_censo=2023,
                tp_dependencia="4",
                qt_mat_bas=None,
                is_qt_mat_bas_missing=True,
            ),
            history_row(
                co_entidade=ESCOLA_B,
                no_entidade="ESCOLA CONCORRENTE",
                nu_ano_censo=2022,
                tp_dependencia="4",
                qt_mat_bas=80,
            ),
            history_row(
                co_entidade=ESCOLA_B,
                no_entidade="ESCOLA CONCORRENTE",
                nu_ano_censo=2023,
                tp_dependencia="4",
                qt_mat_bas=90,
                qt_mat_creche=40,
            ),
            history_row(
                co_entidade=ESCOLA_B,
                no_entidade="ESCOLA CONCORRENTE",
                nu_ano_censo=2024,
                tp_dependencia="4",
                qt_mat_bas=95,
            ),
            history_row(
                co_entidade=ESCOLA_C,
                no_entidade="ESCOLA DE OUTRO MUNICÍPIO",
                co_municipio=MUNICIPIO_C,
                no_municipio="OUTRO MUNICÍPIO",
                nu_ano_censo=2022,
                tp_dependencia="4",
                qt_mat_bas=70,
            ),
        ],
    )


@pytest.fixture
def repo() -> FakeRepository:
    return _repositorio()


@pytest.fixture
def client(repo):
    from fastapi.testclient import TestClient

    from panorama_api.main import create_app

    with TestClient(create_app(settings=_settings(), repository=repo)) as test_client:
        yield test_client


def _html(response, status: int = 200) -> str:
    assert response.status_code == status, response.text[:400]
    assert response.headers["content-type"].startswith("text/html")
    return response.text


def _leituras(repository) -> list[str]:
    """Leituras de dado da requisição (o `get_table_columns` é do boot)."""
    return [nome for nome in repository.methods_called() if nome != "get_table_columns"]


def _tabela(html: str, marca: str) -> str:
    for tabela in re.findall(r"<table[^>]*>.*?</table>", html, flags=re.S):
        if marca in tabela:
            return tabela
    raise AssertionError(f"tabela ausente: {marca}")


def _linhas(tabela: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", linha)).strip()
        for linha in re.findall(r"<tr>(.*?)</tr>", tabela, flags=re.S)
    ]


# -- URL canônica, validação e erros -----------------------------------------


def test_dois_ids_fora_de_ordem_redirecionam_308_para_a_canonica(client, repo):
    resposta = client.get(_url(ESCOLA_B, ESCOLA_A), follow_redirects=False)

    assert resposta.status_code == 308
    assert resposta.headers["location"] == _url(ESCOLA_A, ESCOLA_B)
    # Redirecionar não consulta nada: a página canônica é que paga o custo.
    assert _leituras(repo) == []


def test_ordem_crescente_e_a_url_canonica(client, repo):
    resposta = client.get(_url(ESCOLA_A, ESCOLA_B), follow_redirects=False)

    assert resposta.status_code == 200
    assert _leituras(repo) == ["get_school_history", "get_school_history"]


@pytest.mark.parametrize(
    "escolas",
    [
        f"{ESCOLA_A},{ESCOLA_A}",  # id repetido
        "",  # nenhum id
        f"{ESCOLA_A},{ESCOLA_B},{ESCOLA_C}",  # três ids
        "3100",  # id curto
        "31abcdef",  # formato inválido
        "31000001,",  # segundo id vazio
    ],
)
def test_escolas_invalido_responde_422_html_sem_consultar(client, repo, escolas):
    resposta = client.get(f"{COMPARAR}?escolas={escolas}", follow_redirects=False)

    assert resposta.status_code == 422
    assert resposta.headers["content-type"].startswith("text/html")
    assert resposta.headers["cache-control"] == "no-store"
    assert _leituras(repo) == []


def test_escolas_ausente_responde_422(client, repo):
    resposta = client.get(COMPARAR, follow_redirects=False)

    assert resposta.status_code == 422
    assert resposta.headers["content-type"].startswith("text/html")
    assert _leituras(repo) == []


def test_escola_inexistente_responde_404_html(client, repo):
    resposta = client.get(_url(ESCOLA_A, INEXISTENTE), follow_redirects=False)

    assert resposta.status_code == 404
    assert resposta.headers["content-type"].startswith("text/html")
    assert "Não encontrado no recorte de Minas Gerais" in resposta.text


def test_um_id_inexistente_responde_404_html(client):
    resposta = client.get(_url(INEXISTENTE), follow_redirects=False)

    assert resposta.status_code == 404
    assert resposta.headers["content-type"].startswith("text/html")


def test_q_com_dois_ids_responde_422(client, repo):
    """A busca por nome é da página com um id; ignorar `q` mentiria no recorte."""
    resposta = client.get(
        f"{_url(ESCOLA_A, ESCOLA_B)}&q=modelo", follow_redirects=False
    )

    assert resposta.status_code == 422
    assert _leituras(repo) == []


# -- custo: uma consulta por escola; 304 sem consulta ------------------------


def test_comparacao_consulta_o_repositorio_uma_vez_por_escola(client, repo):
    _html(client.get(_url(ESCOLA_A, ESCOLA_B)))

    # Série e oferta saem do mesmo `get_school_history`: 1 por escola.
    assert _leituras(repo) == ["get_school_history", "get_school_history"]
    assert [
        kwargs["co_entidade"]
        for nome, kwargs in repo.calls
        if nome == "get_school_history"
    ] == [ESCOLA_A, ESCOLA_B]


def test_if_none_match_devolve_304_sem_consultar_o_repositorio(client, repo):
    primeira = client.get(_url(ESCOLA_A, ESCOLA_B))
    chamadas = len(_leituras(repo))

    segunda = client.get(
        _url(ESCOLA_A, ESCOLA_B),
        headers={"If-None-Match": primeira.headers["etag"]},
    )

    assert primeira.status_code == 200
    assert segunda.status_code == 304
    assert segunda.content == b""
    assert len(_leituras(repo)) == chamadas


def test_lru_serve_a_comparacao_sem_consultar(client, repo):
    primeira = client.get(_url(ESCOLA_A, ESCOLA_B))
    chamadas = len(_leituras(repo))

    segunda = client.get(_url(ESCOLA_A, ESCOLA_B))

    assert segunda.status_code == 200
    assert segunda.text == primeira.text
    assert len(_leituras(repo)) == chamadas


# -- tabela da série: união dos intervalos, "sem dado" com motivo ------------


def test_tabela_tem_colunas_ano_a_b_e_cobre_a_uniao_dos_intervalos(client):
    html = _html(client.get(_url(ESCOLA_A, ESCOLA_B)))
    tabela = _tabela(html, "Série de matrículas por ano censitário — comparação")
    cabecalho = _linhas(tabela)[0]

    assert "Ano" in cabecalho
    assert "ESCOLA MODELO" in cabecalho
    assert "ESCOLA CONCORRENTE" in cabecalho
    # A: 2021–2023; B: 2022–2024 ⇒ união 2021–2024.
    for ano in ("2021", "2022", "2023", "2024"):
        assert f"<th scope=\"row\">{ano}</th>" in tabela, ano


def test_ano_ausente_em_uma_escola_e_sem_dado_com_motivo(client):
    tabela = _tabela(
        _html(client.get(_url(ESCOLA_A, ESCOLA_B))),
        "Série de matrículas por ano censitário — comparação",
    )

    # 2021 só existe em A; 2024 só em B.
    assert re.search(
        r"<th scope=\"row\">2021</th>\s*<td>100</td>\s*"
        r"<td>sem dado \(ano ausente na fonte\)</td>",
        tabela,
    )
    assert re.search(
        r"<th scope=\"row\">2024</th>\s*"
        r"<td>sem dado \(ano ausente na fonte\)</td>\s*<td>95</td>",
        tabela,
    )
    # Ausência nunca vira zero.
    assert not re.search(r"<td>0</td>", tabela)


def test_matricula_ausente_na_fonte_mostra_a_flag_de_origem(client):
    tabela = _tabela(
        _html(client.get(_url(ESCOLA_A, ESCOLA_B))),
        "Série de matrículas por ano censitário — comparação",
    )

    assert re.search(
        r"<th scope=\"row\">2023</th>\s*"
        r"<td>sem dado \(is_qt_mat_bas_missing\)</td>\s*<td>90</td>",
        tabela,
    )


def test_svg_tem_aria_hidden_e_as_duas_classes_de_serie(client):
    html = _html(client.get(_url(ESCOLA_A, ESCOLA_B)))
    svg = re.search(r"<svg[^>]*>.*?</svg>", html, flags=re.S)

    assert svg is not None
    assert 'aria-hidden="true"' in svg.group(0)
    assert re.search(r'class="serie__barra"', svg.group(0))
    # A segunda série se distingue sem depender de cor.
    assert re.search(r'class="serie__barra serie__barra--b"', svg.group(0))


def test_uma_escola_sem_ano_observado_nao_gera_barras():
    repo = FakeRepository(
        schools=[school_row(co_entidade=ESCOLA_A), school_row(co_entidade=ESCOLA_B)],
        history=[
            history_row(co_entidade=ESCOLA_A, nu_ano_censo=2021, qt_mat_bas=100),
            history_row(co_entidade=ESCOLA_A, nu_ano_censo=2022, qt_mat_bas=120),
            # B tem os dois anos na fonte, mas sem matrícula observada.
            history_row(
                co_entidade=ESCOLA_B,
                nu_ano_censo=2021,
                qt_mat_bas=None,
                is_qt_mat_bas_missing=True,
            ),
            history_row(
                co_entidade=ESCOLA_B,
                nu_ano_censo=2022,
                qt_mat_bas=None,
                is_qt_mat_bas_missing=True,
            ),
        ],
    )
    from fastapi.testclient import TestClient

    from panorama_api.main import create_app

    with TestClient(create_app(settings=_settings(), repository=repo)) as client:
        html = _html(client.get(_url(ESCOLA_A, ESCOLA_B)))

    svg = re.search(r"<svg[^>]*>.*?</svg>", html, flags=re.S)
    assert svg is not None
    # B não desenha barra em ano nenhum; a lacuna fica marcada nos dois anos.
    assert 'class="serie__barra serie__barra--b"' not in svg.group(0)
    assert svg.group(0).count('class="serie__ausente"') == 2
    assert svg.group(0).count('<rect') == 2  # só as duas barras de A


# -- oferta por etapa do ano mais recente comum ------------------------------


def test_oferta_usa_o_ano_mais_recente_comum(client):
    html = _html(client.get(_url(ESCOLA_A, ESCOLA_B)))

    # Comum a A (2021–2023) e B (2022–2024) = 2023, o mais recente.
    assert "Oferta e matrícula por etapa (2023)" in html
    tabela = _tabela(html, "Oferta e matrícula por etapa em 2023 — comparação")
    linhas = _linhas(tabela)

    assert "ESCOLA MODELO" in linhas[0] or any("ESCOLA MODELO" in l for l in linhas[:2])
    # A matrícula BAS de 2023 em A está ausente; a de B é 90.
    assert any("sem dado (is_qt_mat_bas_missing)" in linha for linha in linhas)
    assert any("90" in linha for linha in linhas)
    # Creche de B (40) aparece na linha da etapa; A não oferta creche em 2023.
    linha_creche = next(linha for linha in linhas if "Creche" in linha)
    assert "40" in linha_creche


def test_sem_ano_comum_mostra_o_motivo_e_nao_escolhe_um_ano():
    repo = FakeRepository(
        schools=[school_row(co_entidade=ESCOLA_A), school_row(co_entidade=ESCOLA_B)],
        history=[
            history_row(co_entidade=ESCOLA_A, nu_ano_censo=2021, qt_mat_bas=100),
            history_row(co_entidade=ESCOLA_B, nu_ano_censo=2022, qt_mat_bas=80),
        ],
    )
    from fastapi.testclient import TestClient

    from panorama_api.main import create_app

    with TestClient(create_app(settings=_settings(), repository=repo)) as client:
        html = _html(client.get(_url(ESCOLA_A, ESCOLA_B)))

    assert "não têm ano censitário em comum" in html
    assert "Oferta e matrícula por etapa em" not in html


def test_escolas_de_municipios_diferentes_avisam_que_a_comparacao_municipal_nao_se_aplica(
    client,
):
    html = _html(client.get(_url(ESCOLA_A, ESCOLA_C)))

    assert "municípios diferentes" in html
    assert "não se aplica a este par" in html


def test_mesmo_municipio_nao_mostra_o_aviso(client):
    html = _html(client.get(_url(ESCOLA_A, ESCOLA_B)))

    assert "municípios diferentes" not in html


# -- entradas: link da ficha e formulário de busca --------------------------


def test_ficha_tem_o_link_para_comparar(client):
    html = _html(client.get(f"/app/escolas/{ESCOLA_A}"))

    assert (
        f'<a href="/app/comparar?escolas={ESCOLA_A}">Comparar com outra escola</a>'
        in html
    )


def test_pagina_com_um_id_tem_o_formulario_de_busca(client):
    html = _html(client.get(_url(ESCOLA_A)))

    assert 'action="/app/comparar"' in html
    assert f'<input type="hidden" name="escolas" value="{ESCOLA_A}">' in html
    assert 'name="q"' in html
    assert "Comparação entre escolas" in html


def test_pagina_com_um_id_nao_consulta_a_busca_sem_q(client, repo):
    _html(client.get(_url(ESCOLA_A)))

    assert _leituras(repo) == ["get_school_history"]


def test_resultado_da_busca_linka_para_a_url_canonica(client):
    html = _html(client.get(f"{_url(ESCOLA_A)}&q=concorrente"))

    # A < B: a URL canônica já sai na ordem crescente, sem 308.
    assert (
        f'<a href="/app/comparar?escolas={ESCOLA_A},{ESCOLA_B}">Comparar com esta</a>'
        in html
    )


def test_resultado_da_busca_e_canonico_quando_a_segunda_escola_e_menor():
    repo = FakeRepository(
        schools=[
            school_row(co_entidade=ESCOLA_A, no_entidade="ESCOLA MODELO"),
            school_row(co_entidade="31000000", no_entidade="ESCOLA ANTERIOR"),
        ],
        history=[
            history_row(co_entidade=ESCOLA_A, nu_ano_censo=2022, qt_mat_bas=120),
            history_row(co_entidade="31000000", nu_ano_censo=2022, qt_mat_bas=60),
        ],
    )
    from fastapi.testclient import TestClient

    from panorama_api.main import create_app

    with TestClient(create_app(settings=_settings(), repository=repo)) as client:
        html = _html(client.get(f"{_url(ESCOLA_A)}&q=anterior"))

    assert (
        '<a href="/app/comparar?escolas=31000000,31000001">Comparar com esta</a>'
        in html
    )


def test_a_propria_escola_a_nao_recebe_link_de_comparacao(client):
    html = _html(client.get(f"{_url(ESCOLA_A)}&q=modelo"))

    assert "é a escola desta página" in html
    assert f'href="/app/comparar?escolas={ESCOLA_A},{ESCOLA_A}"' not in html


def test_busca_com_resultado_vazio_nao_inventa_link(client):
    html = _html(client.get(f"{_url(ESCOLA_A)}&q=escolaquenaoexiste"))

    assert "Nenhuma escola encontrada para esta busca." in html
    assert ">Comparar com esta</a>" not in html


# -- guarda de markup: nada de inline --------------------------------------


@pytest.mark.parametrize("caminho", [_url(ESCOLA_A), _url(ESCOLA_A, ESCOLA_B)])
def test_pagina_nova_sem_script_inline_style_ou_on(client, caminho):
    html = _html(client.get(caminho))

    assert "<style" not in html
    assert not re.search(r"\sstyle\s*=", html)
    assert not re.search(r"\son[a-z]+\s*=", html)
    # O único `<script>` é o asset versionado com `defer` (card C1).
    assert len(re.findall(r"<script\b[^>]*>\s*</script>", html)) == 1
