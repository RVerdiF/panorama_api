"""Hero da landing `/` e painel do recorte — card `t_437796c3` (spec §4, §5, §8).

O painel da coluna direita substitui a foto da referência visual por três
números que saem do **código e da config**, nunca de literal no template:

* municípios de MG — `len(municipios_mg())`, a lista IBGE versionada;
* anos publicados — `settings.anos_disponiveis` (`APP_ANOS_DISPONIVEIS`), em
  faixa quando a lista é contínua e separados por vírgula quando tem buraco;
* etapas e modalidades — chaves de `ETAPAS_ROTULOS` **sem** `"bas"`, que é o
  total oficial do Censo e não uma etapa do mercado.

Nada aqui toca rede ou BigQuery: o HTML vem do `TestClient` com repositório fake
vazio e os testes conferem que `GET /` continua com **0** chamadas ao
repositório. Não existe contagem de escolas porque `COUNT(*)` é proibido
(`repositories/bigquery/pagination.py:1-5`), e por isso não há o que consultar.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.main import create_app
from panorama_api.web import routes as web_routes
from panorama_api.web.municipios import Municipio, municipios_mg
from tests.unit.conftest import FakeRepository

ANOS = (2021, 2022, 2023, 2024, 2025)
ANOS_CSV = ",".join(str(ano) for ano in ANOS)
INICIO = "/"

VALOR = re.compile(r'<dd class="recorte__valor">([^<]*)</dd>')


def _settings(*, anos: str = ANOS_CSV) -> Settings:
    return Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        max_bytes_billed=256 * 1024 * 1024,
        validate_schema_on_startup=False,
        contract_version="mvp-1",
        data_version="dev",
        app_anos_disponiveis=anos,
    )


def _pagina(*, anos: str = ANOS_CSV) -> tuple[str, FakeRepository]:
    """HTML de `/` e o repositório fake que a página recebeu (para contar chamadas)."""
    repo = FakeRepository()
    app = create_app(settings=_settings(anos=anos), repository=repo)
    with TestClient(app) as cliente:
        resposta = cliente.request(
            "GET", INICIO, headers={"Accept": "text/html", "Accept-Encoding": "identity"}
        )

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/html")
    return resposta.text, repo


def _valores(html: str) -> list[str]:
    """Os três números do painel, na ordem em que a página os apresenta."""
    return VALOR.findall(html)


def test_painel_do_recorte_mostra_os_numeros_reais_do_produto():
    html, _ = _pagina()

    # 853 vem da lista versionada, não de um literal no template.
    assert len(municipios_mg()) == 853
    assert _valores(html) == ["853", "2021–2025", "8"]
    for rotulo in (
        "municípios de Minas Gerais",
        "anos do Censo Escolar publicados",
        "etapas e modalidades no mercado",
    ):
        assert rotulo in html
    assert "Fonte: Censo Escolar da Educação Básica (INEP)." in html


def test_painel_e_uma_secao_com_h2_e_lista_de_definicoes():
    html, _ = _pagina()

    assert re.search(
        r'<section class="recorte" aria-labelledby="recorte-titulo">', html
    )
    assert '<h2 id="recorte-titulo">Recorte dos dados</h2>' in html
    assert re.search(r"<dl class=\"recorte__lista\">", html)
    # Um `dt` por número: o termo vem antes do valor no `dl`, e o CSS inverte
    # apenas a ordem visual (número grande em cima do rótulo).
    assert html.count('class="recorte__rotulo"') == 3
    assert html.count('class="recorte__valor"') == 3


def test_anos_continuos_viram_faixa_e_anos_com_buraco_viram_lista():
    continuos, _ = _pagina(anos="2021,2022,2023,2024,2025")
    assert _valores(continuos)[1] == "2021–2025"

    com_buraco, _ = _pagina(anos="2021,2023")
    assert _valores(com_buraco)[1] == "2021, 2023"
    # A faixa prometeria um ano não publicado: nada de "2021–2023".
    assert "2021–2023" not in com_buraco


def test_painel_muda_quando_a_fonte_muda(monkeypatch: pytest.MonkeyPatch):
    """O painel é derivado, não decorado: trocar a fonte muda a página."""
    monkeypatch.setattr(
        web_routes,
        "municipios_mg",
        lambda: (
            Municipio(co_municipio="3106200", no_municipio="Belo Horizonte"),
            Municipio(co_municipio="3100104", no_municipio="Abadia dos Dourados"),
        ),
    )
    monkeypatch.setattr(
        web_routes,
        "ETAPAS_ROTULOS",
        {"bas": "Educação básica (total)", "med": "Ensino médio"},
    )

    html, _ = _pagina()

    assert _valores(html) == ["2", "2021–2025", "1"]


def test_inicio_nao_consulta_o_repositorio():
    """Contar escolas exigiria `COUNT(*)`; o painel não faz nenhuma consulta."""
    _, repo = _pagina()

    assert repo.calls == []


def test_template_nao_carrega_numero_literal_do_painel():
    """Os números saem do código e da config — o template só tem a marcação."""
    fonte = (web_routes.TEMPLATES_DIR / "inicio.html").read_text(encoding="utf-8")

    assert "853" not in fonte
    assert "2021" not in fonte
    for variavel in ("recorte_municipios", "recorte_anos", "recorte_etapas"):
        assert "{{ " + variavel + " }}" in fonte


def _hero(html: str) -> str:
    """Marcação da hero: a `<section class="hero">` com o painel aninhado dentro."""
    inicio = html.index('<section class="hero">')
    fim_do_painel = html.index("</section>", inicio) + len("</section>")
    fim = html.index("</section>", fim_do_painel) + len("</section>")
    return html[inicio:fim]


def test_hierarquia_de_titulos_do_hero():
    """Um `<h1>`; o painel abre nível com `<h2>`, sem pular nível dentro da hero."""
    html, _ = _pagina()
    hero = _hero(html)

    assert hero.count("<h1") == 1
    assert hero.index("<h1") < hero.index("<h2")
    assert hero.count("<h2") == 1
    # Nada de `<h3>` na hero: as seções abaixo dela (card L4) é que abrem nível.
    assert "<h3" not in hero
    assert html.count("<h1") == 1


def test_hero_mostra_a_copy_do_h1_e_do_subtitulo():
    html, _ = _pagina()

    assert "<h1>Escolas e mercados da educação básica em Minas Gerais</h1>" in html
    assert (
        "Matrículas, oferta por etapa, rendimento e participação de mercado das "
        "escolas" in html
    )
    assert "a partir do Censo Escolar da Educação Básica (INEP)." in html
