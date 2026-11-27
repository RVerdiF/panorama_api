"""Índice de municípios no DOM do protótipo (card V4-I `t_5825770b`).

Cobre, sobre o HTML renderizado de verdade (``TestClient`` + repositório
fake, nenhuma rede/BigQuery):

* os 7 ``th`` do protótipo, na ordem e com as classes/`data-*` literais;
* 853 ``tr`` no SSR, em matrícula desc com nulos por último, cada um com o
  link "Abrir mercado" (sem JS a ordem e os links já estão prontos);
* barras ``cela-barra`` via ``data-largura`` (zero ``style=``);
* ``NULL ≠ 0``: os municípios sem escola privada ativa levam o marcador
  ``title="sem escola privada ativa"`` na matrícula, na variação e no share
  — nunca ``0``; ``n_escolas = 0`` é medição real e sai como ``0``;
* a degradação do §4.6: BigQuery fora → 200 com o 4a + ``div.aviso``, sem
  ``ETag`` e fora do LRU (nova consulta a cada abertura);
* nenhum número do mock de ``dados.js`` ("recorte de demonstração",
  "quatorze", "Belo Horizonte · 30");
* 1 consulta por abertura no caminho normal; zero nos 303/422.

A fixture espelha o §4.4 medido: 408 mercados privados (matrícula desc) +
445 sem escola privada (``qt``/variação/share nulos, ``n_escolas = 0``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.core.errors import UpstreamUnavailable
from panorama_api.main import create_app
from tests.unit.conftest import FakeRepository

ANOS = (2021, 2022, 2023, 2024, 2025)
INDICE = "/app/mercados/"
PREFIXO_MERCADO = "/app/mercados/"

DIRETORIO_WEB = Path(__file__).resolve().parents[2] / "src" / "panorama_api" / "web"
TEMPLATES = DIRETORIO_WEB / "templates"
STATIC = DIRETORIO_WEB / "static"
MUNICIPIOS_JSON = DIRETORIO_WEB / "data" / "municipios_mg.json"

#: Textos do mock (`dados.js` do design) que nunca podem chegar ao HTML.
FORA_DO_MOCK = ("recorte de demonstração", "quatorze", "Belo Horizonte · 30")
#: Aviso da degradação (§4.6), literal.
AVISO_INDISPONIVEL = "Os números do índice estão indisponíveis agora"


def _codigos_mg() -> list[str]:
    return [item["co_municipio"] for item in json.loads(MUNICIPIOS_JSON.read_text())]


def fixture_853(codigos: list[str]) -> list[dict]:
    """853 linhas na ordem do SQL: matrícula desc, nulos por último."""
    assert len(codigos) == 853
    linhas: list[dict] = []
    for i, co in enumerate(codigos[:408]):
        qt = 300000.0 - i * 137.5
        anterior: float | None = round(qt - (i % 5) * 100.0, 2)
        if i == 5:
            # Matrícula no ano mas sem base: variação nula com motivo próprio.
            anterior = None
        variacao = (qt - anterior) / anterior * 100 if anterior else None
        linhas.append(
            {
                "co_municipio": co,
                "qt_mat_privada": qt,
                "qt_mat_privada_anterior": anterior,
                "n_escolas_privadas": (i % 200) + 1,
                "variacao_pct": variacao,
                "share_lider_pct": round(1.0 + (i % 90) / 10.0, 2),
            }
        )
    for co in codigos[408:]:
        linhas.append(
            {
                "co_municipio": co,
                "qt_mat_privada": None,
                "qt_mat_privada_anterior": None,
                "n_escolas_privadas": 0,
                "variacao_pct": None,
                "share_lider_pct": None,
            }
        )
    return linhas


def _settings() -> Settings:
    return Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        max_bytes_billed=256 * 1024 * 1024,
        validate_schema_on_startup=False,
        contract_version="mvp-1",
        data_version="dev",
        app_anos_disponiveis=",".join(str(ano) for ano in ANOS),
    )


@pytest.fixture
def indice_repo() -> FakeRepository:
    repo = FakeRepository()
    repo.indice = fixture_853(_codigos_mg())
    return repo


@pytest.fixture
def indice_cliente(indice_repo: FakeRepository) -> TestClient:
    app = create_app(settings=_settings(), repository=indice_repo)
    with TestClient(app) as cliente:
        yield cliente


def _html(cliente: TestClient, caminho: str = INDICE, **kwargs) -> str:
    resposta = cliente.get(caminho, **kwargs)
    assert resposta.status_code == 200, resposta.text[:600]
    assert resposta.headers["content-type"].startswith("text/html")
    return resposta.text


def _tbody(html: str) -> str:
    corpo = re.search(r'<tbody id="corpo-municipios">(.*?)</tbody>', html, re.S)
    assert corpo is not None, "sem tbody#corpo-municipios no HTML normal"
    return corpo.group(1)


# -- 7 th do protótipo --------------------------------------------------------


def test_sete_th_do_prototipo_em_ordem(indice_cliente: TestClient):
    cabeca = re.search(
        r'<table class="tabela" id="tabela-municipios" data-ordenavel>'
        r".*?<thead>.*?<tr>(.*?)</tr>",
        _html(indice_cliente),
        re.S,
    )
    assert cabeca is not None
    ths = re.findall(r"<th\b([^>]*)>(.*?)</th>", cabeca.group(1))

    assert [(atributos.strip(), texto) for atributos, texto in ths] == [
        ('class="num" scope="col"', "#"),
        (
            'class="ordenavel" data-campo="nome" data-tipo="texto" scope="col"',
            "Município",
        ),
        (
            'class="ordenavel num" data-campo="matricula" data-tipo="numero" '
            'aria-sort="descending" scope="col"',
            "Matrícula privada",
        ),
        (
            'class="ordenavel num" data-campo="escolas" data-tipo="numero" '
            'scope="col"',
            "Escolas ativas",
        ),
        (
            'class="ordenavel num" data-campo="variacao" data-tipo="numero" '
            'scope="col"',
            "Variação anual",
        ),
        (
            'class="ordenavel num" data-campo="lider" data-tipo="numero" '
            'scope="col"',
            "Maior share",
        ),
        ('scope="col"', "Ficha"),
    ]


# -- 853 tr no SSR, em matrícula desc ------------------------------------------


def test_853_tr_em_matricula_desc_com_853_abrir_mercado(
    indice_cliente: TestClient, indice_repo: FakeRepository
):
    corpo = _tbody(_html(indice_cliente))

    assert corpo.count("<tr>") == 853
    assert corpo.count("Abrir mercado") == 853

    hrefs = re.findall(r'href="(/app/mercados/31\d{5})"', corpo)
    esperados = [f"/app/mercados/{r['co_municipio']}" for r in indice_repo.indice]
    assert hrefs == esperados

    # Maior matrícula primeiro, nulos por último (ordem do serviço/SQL).
    primeira = re.search(
        r'<td class="num metrica" data-valor="([^"]*)">', corpo
    )
    assert primeira is not None and float(primeira.group(1)) == max(
        r["qt_mat_privada"]
        for r in indice_repo.indice
        if r["qt_mat_privada"] is not None
    )
    assert corpo.rstrip().endswith("</tr>")
    ultima_linha = corpo.strip().rsplit("<tr>", 1)[-1]
    assert 'data-valor=""' in ultima_linha


def test_sem_js_ordem_e_links_ja_prontos_no_ssr(
    indice_cliente: TestClient, indice_repo: FakeRepository
):
    """Sem JS nada muda: o SSR já entrega ordem e links (critério 3).

    O ``TestClient`` não executa JS por construção — o HTML asserido aqui é
    exatamente o que o navegador recebe com script desabilitado.
    """
    html = _html(indice_cliente)
    corpo = _tbody(html)

    assert html.count("Abrir mercado") == 853
    assert "São 853 municípios de MG." in html
    # Cabeçalho sem botão: a ordenação nasce no JS (`ordenarTabelas`).
    assert "<thead>" in html and "<button" not in html.split("</thead>")[0]


# -- NULL ≠ 0 -----------------------------------------------------------------


def test_sem_escola_privada_e_marcador_nunca_zero(indice_cliente: TestClient):
    corpo = _tbody(_html(indice_cliente))

    # 445 sem matrícula × 3 colunas (matrícula, variação, share).
    assert corpo.count('title="sem escola privada ativa"') == 445 * 3
    # Matrícula e share nulos: 445 + 445 células com `data-valor` vazio.
    assert corpo.count('<td class="num metrica" data-valor="">') == 445 * 2
    # A variação do município sem ano anterior tem motivo próprio.
    assert corpo.count('title="sem ano anterior"') == 1
    # `n_escolas = 0` é medição real: sai como 0, sem marcador.
    assert corpo.count(">0</td>") == 445


def test_kpis_somam_ignorando_none(indice_cliente: TestClient):
    html = _html(indice_cliente)

    assert html.count('<div class="kpi">') == 4
    assert "Municípios no recorte" in html
    assert "Matrícula privada 2025" in html
    assert "Escolas privadas ativas" in html
    assert "Variação do recorte" in html
    assert "matrícula privada vs. 2024, só municípios com os dois anos" in html
    assert "853 municípios de MG" in html
    assert "Censo Escolar (INEP)" in html
    assert "Mercados privados de Minas Gerais — ano de referência 2025" in html


# -- barras, zero style= -------------------------------------------------------


def test_barras_com_data_largura_e_zero_style(indice_cliente: TestClient):
    html = _html(indice_cliente)
    corpo = _tbody(html)

    assert corpo.count('data-largura="') == 408
    assert 'data-largura="100.0%"' in corpo
    # Zero `style=`: atributo, não a palavra em comentário Jinja.
    assert "style=" not in html
    sem_comentario = re.sub(
        r"{#.*?#}", "", (TEMPLATES / "mercados_indice.html").read_text(), flags=re.S
    )
    assert "style=" not in sem_comentario

    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert ".cela-barra__preenche[data-largura]" in js


# -- degradação do §4.6 ----------------------------------------------------------


def test_degradacao_200_sem_etag_fora_do_lru(
    indice_cliente: TestClient, indice_repo: FakeRepository
):
    indice_repo.errors["get_indice_municipios"] = UpstreamUnavailable("timeout")

    primeira = indice_cliente.get(INDICE)
    assert primeira.status_code == 200
    assert "etag" not in primeira.headers
    assert primeira.headers["cache-control"] == "no-store"
    assert AVISO_INDISPONIVEL in primeira.text
    assert "a lista continua navegável" in primeira.text
    # 4a: 853 links, sem colunas numéricas nem KPIs.
    assert primeira.text.count("Ver mercado") == 853
    assert "Abrir mercado" not in primeira.text
    assert "kpis-municipios" not in primeira.text
    assert "corpo-municipios" not in primeira.text

    # Fora do LRU: a segunda abertura consulta de novo.
    indice_repo.calls.clear()
    segunda = indice_cliente.get(INDICE)
    assert segunda.status_code == 200
    assert AVISO_INDISPONIVEL in segunda.text
    assert [nome for nome, _ in indice_repo.calls] == ["get_indice_municipios"]


# -- nenhum número do mock ------------------------------------------------------


def test_nenhum_numero_do_mock(indice_cliente: TestClient):
    html = _html(indice_cliente)
    for texto in FORA_DO_MOCK:
        assert texto not in html, texto


def test_nenhum_numero_do_mock_na_degradacao(
    indice_cliente: TestClient, indice_repo: FakeRepository
):
    indice_repo.errors["get_indice_municipios"] = UpstreamUnavailable("timeout")
    html = _html(indice_cliente)
    for texto in FORA_DO_MOCK:
        assert texto not in html, texto


# -- contrato de consulta -------------------------------------------------------


def test_uma_consulta_por_abertura(
    indice_cliente: TestClient, indice_repo: FakeRepository
):
    indice_repo.calls.clear()
    _html(indice_cliente)

    assert indice_repo.calls == [("get_indice_municipios", {"ano": 2025})]

    # *Hit* do LRU: a segunda abertura não toca no repositório (custo 0).
    _html(indice_cliente)
    assert indice_repo.calls == [("get_indice_municipios", {"ano": 2025})]


def test_indice_vazio_responde_200_com_kpis_sem_dado():
    """Guarda do ``test_web_seguranca``: repositório vazio também é 200."""
    repo = FakeRepository()
    app = create_app(settings=_settings(), repository=repo)
    with TestClient(app) as cliente:
        html = _html(cliente)

    assert "São 0 municípios de MG." in html
    assert html.count('<div class="kpi">') == 4
    assert "style=" not in html
    for texto in FORA_DO_MOCK:
        assert texto not in html, texto
