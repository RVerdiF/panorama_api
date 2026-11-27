"""Shell de navegação do front — card NAV-1 `t_d31ce632` (spec §1, §2.1, §2.3, §7),
no DOM do protótipo (card V3-S0).

Cobre, sobre o HTML renderizado de verdade (``TestClient`` + repositório fake,
nenhuma rede/BigQuery):

* a navbar de nível 1 (Escolas · Municípios · Redes inerte · Metodologia)
  existe **uma vez** em todas as telas — inclusive nas páginas de erro — e na
  ordem da spec, com o logo levando para a landing `/`;
* Metodologia é link simples (sem ``<details>``/``<summary>``, sem
  ``role="menu"`` e sem JS) com ``aria-current="page"`` quando ativo, e a
  página `/app/metodologia` mantém as âncoras de conteúdo;
* `aria-current`: ``"page"`` no item cuja tela é a própria, ``"true"`` na área
  dona de uma tela-filha (ficha → Escolas, mercado → Municípios);
* o índice novo ``GET /app/mercados/`` (com barra) responde 200 com a tabela
  de municípios no DOM do protótipo (7 colunas, uma linha SSR por município
  + filtro no cliente): 1 consulta no 200; 303 para o mercado escolhido e
  422 no código inválido, sem tocar no repositório;
* o shell não depende de JS: a única tag de script é o `app.js` com `defer`
  (card `t_71b25279`), sem inline em template nenhum;
* o `<header>` renderizado cabe em 1,5 KB (spec §6: partials ≤ 1,5 KB).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.core.http_cache import HttpCacheMiddleware
from panorama_api.main import create_app
from panorama_api.web import PREFIXO_WEB
from panorama_api.web.municipios import municipios_mg
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
from tests.unit.test_web_indice import fixture_853

ANOS = (2021, 2022, 2023, 2024, 2025)
BUSCA = f"{PREFIXO_WEB}/"
METODOLOGIA = f"{PREFIXO_WEB}/metodologia"
MUNICIPIO = "3106200"
MERCADO = f"{PREFIXO_WEB}/mercados/{MUNICIPIO}"
INDICE = f"{PREFIXO_WEB}/mercados/"
ESCOLA = f"{PREFIXO_WEB}/escolas/31000001"

#: Fragmentos do painel do submenu: cada href da navbar tem de casar com um `id`
#: de `metodologia.html` (contrato de link compartilhado, spec §3.2).
FRAGMENTOS = ("versao", "regras", "definicoes", "avisos", "universo")

#: Teto do `<header>` renderizado (spec §6: partials ≤ 1,5 KB).
TETO_HEADER_BYTES = 1536

DIRETORIO_WEB = Path(__file__).resolve().parents[2] / "src" / "panorama_api" / "web"
TEMPLATES = DIRETORIO_WEB / "templates"
STATIC = DIRETORIO_WEB / "static"


def _settings(*, anos: str = ",".join(str(ano) for ano in ANOS)) -> Settings:
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


@pytest.fixture
def navegacao_repo() -> FakeRepository:
    """Repositório fake com uma escola, uma série e um mercado completo."""
    return FakeRepository(
        municipios=[municipio_row()],
        schools=[school_row()],
        history=[history_row(nu_ano_censo=ano) for ano in ANOS],
        indicators=[indicator_row(nu_ano_censo=2025)],
        competidores=[competidor_row(nu_ano_censo=2025)],
        markets=[market_row(nu_ano_censo=ano, etapa="bas") for ano in ANOS],
        share=[share_row(nu_ano_censo=ano) for ano in ANOS],
    )


@pytest.fixture
def cliente(navegacao_repo: FakeRepository) -> TestClient:
    app = create_app(settings=_settings(), repository=navegacao_repo)
    with TestClient(app) as test_client:
        yield test_client


def _limpar_cache_de_paginas(cliente: TestClient) -> None:
    """Esvazia o LRU das páginas `/app` (a chave não inclui o repositório)."""
    pilha = cliente.app.middleware_stack
    while pilha is not None:
        if (
            isinstance(pilha, HttpCacheMiddleware)
            and pilha.prefix == PREFIXO_WEB
            and pilha.pagina
        ):
            pilha.cache.clear()
            return
        pilha = getattr(pilha, "app", None)
    raise AssertionError("cache de páginas /app não encontrado no stack")


def _get(cliente: TestClient, caminho: str, **kwargs):
    _limpar_cache_de_paginas(cliente)
    return cliente.request("GET", caminho, **kwargs)


def _navbar(html: str) -> str:
    """Bloco do `<nav aria-label="Navegação principal">` — nada além dele.

    Os atributos são contados **no bloco**, não no documento: a trilha da
    ficha e do mercado também usa link + `span` para o último item.
    """
    achado = re.search(
        r'<nav class="menu" aria-label="Navegação principal">.*?</nav>', html, re.S
    )
    assert achado is not None, "navbar de nível 1 ausente no HTML"
    return achado.group(0)


def _header(html: str) -> str:
    achado = re.search(r'<header class="topo">.*?</header>', html, re.S)
    assert achado is not None, "header do topo ausente no HTML"
    return achado.group(0)


# -- 1. navbar única, na ordem da spec, em todas as telas ---------------------

PAGINAS = [
    (BUSCA, 200),
    (METODOLOGIA, 200),
    (ESCOLA, 200),
    (MERCADO, 200),
    (INDICE, 200),
    (f"{PREFIXO_WEB}/inexistente", 404),
    (f"{INDICE}?co_municipio=999", 422),
]


def test_navbar_unica_na_ordem_certa_em_todas_as_telas(cliente: TestClient):
    for caminho, status in PAGINAS:
        resposta = _get(cliente, caminho)

        assert resposta.status_code == status, caminho
        html = resposta.text
        assert html.count('aria-label="Navegação principal"') == 1, caminho
        navbar = _navbar(html)
        # Ordem de nível 1: Escolas · Municípios · Redes · Metodologia (spec §2.1,
        # DOM do protótipo: Redes é item inerte, não link).
        assert navbar.index(">Escolas<") < navbar.index(">Municípios<") < navbar.index(
            ">Redes<"
        ) < navbar.index(">Metodologia<"), caminho
        # Redes é inerte: `span` sem `href`, nunca link nem item ativo (V3-S0).
        assert '<span aria-disabled="true">Redes</span>' in navbar, caminho
        trecho_redes = re.search(r"<span[^>]*>Redes</span>", navbar)
        assert trecho_redes is not None, caminho
        assert "href" not in trecho_redes.group(0), caminho
        # O logo é a volta para a entrada do sistema, em qualquer tela (A5).
        # Card V1 `t_423aa547` + protótipo V3-S0: a marca é o sinal `PE`
        # (decorativo) + nome + subtítulo; o nome acessível do link continua
        # sendo "Panorama Escola".
        assert '<a class="marca" href="/">' in html, caminho
        assert '<span class="marca__sinal" aria-hidden="true">PE</span>' in html, caminho
        assert '<span class="marca__nome">Panorama Escola</span>' in html, caminho
        assert '<span class="marca__sub">Inteligência de mercado · MG</span>' in html, caminho
        # O selo à direita declara a fonte do dado exibido (V3-S0).
        assert '<span class="selo-data">' in html, caminho


def test_navbar_nao_usa_role_menu_nem_js(cliente: TestClient):
    html = _get(cliente, BUSCA).text
    navbar = _navbar(html)

    assert 'role="menu"' not in html
    assert 'role="menuitem"' not in html
    # Metodologia virou link simples: sem disclosure, sem painel, sem JS.
    assert "<details" not in navbar and "<summary" not in navbar
    assert "<button" not in navbar


# -- 2. Metodologia como link simples ----------------------------------------


def test_metodologia_e_link_simples_e_a_pagina_mantem_as_ancoras(cliente: TestClient):
    navbar = _navbar(_get(cliente, BUSCA).text)
    metodologia = _get(cliente, METODOLOGIA).text

    # O destino da área continua a um clique, direto no item da navbar.
    assert f'<a href="{METODOLOGIA}">Metodologia</a>' in navbar
    # Sem disclosure nem painel na navbar do protótipo.
    assert "<details" not in navbar
    assert "topo__submenu" not in navbar
    assert "topo__painel" not in navbar
    # As âncoras de conteúdo da metodologia continuam existindo na página.
    for fragmento in FRAGMENTOS:
        assert f'id="{fragmento}"' in metodologia, fragmento


# -- 3. aria-current: page na tela, true na área ------------------------------


def test_aria_current_da_busca_marca_so_o_link_de_escolas(cliente: TestClient):
    navbar = _navbar(_get(cliente, BUSCA).text)

    assert '<a href="/app/" aria-current="page">Escolas</a>' in navbar
    assert navbar.count('aria-current="page"') == 1
    assert 'aria-current="true"' not in navbar


def test_aria_current_do_indice_marca_so_o_link_de_municipios(cliente: TestClient):
    navbar = _navbar(_get(cliente, INDICE).text)

    assert '<a href="/app/mercados/" aria-current="page">Municípios</a>' in navbar
    assert navbar.count('aria-current="page"') == 1
    assert 'aria-current="true"' not in navbar


def test_aria_current_da_metodologia_marca_so_o_link(cliente: TestClient):
    navbar = _navbar(_get(cliente, METODOLOGIA).text)

    assert f'<a href="{METODOLOGIA}" aria-current="page">Metodologia</a>' in navbar
    assert navbar.count('aria-current="page"') == 1
    assert 'aria-current="true"' not in navbar


def test_aria_current_da_ficha_marca_a_area_escolas_como_true(cliente: TestClient):
    navbar = _navbar(_get(cliente, ESCOLA).text)

    assert '<a href="/app/" aria-current="true">Escolas</a>' in navbar
    assert navbar.count('aria-current="true"') == 1
    # A ficha não é a busca: nenhum item é `page`.
    assert 'aria-current="page"' not in navbar


def test_aria_current_do_mercado_marca_a_area_municipios_como_true(cliente: TestClient):
    navbar = _navbar(_get(cliente, MERCADO).text)

    assert '<a href="/app/mercados/" aria-current="true">Municípios</a>' in navbar
    assert navbar.count('aria-current="true"') == 1
    assert 'aria-current="page"' not in navbar


def test_redes_segue_inerte_em_todas_as_telas(cliente: TestClient):
    for caminho, _status in PAGINAS:
        navbar = _navbar(_get(cliente, caminho).text)

        assert '<span aria-disabled="true">Redes</span>' in navbar, caminho
        assert "Redes</a>" not in navbar, caminho
        assert re.search(r'<[^>]*aria-current[^>]*>Redes<', navbar) is None, caminho


# -- 3b. rodapé final único de cada página ------------------------------------


def test_rodape_final_traz_fonte_e_versoes(cliente: TestClient):
    html = _get(cliente, MERCADO).text

    assert '<footer class="rodape-final">' in html
    assert "Fonte: Censo Escolar (INEP)" in html
    assert "<code>dados dev · contrato mvp-1</code>" in html
    assert '<footer class="rodape">' not in html


def test_rodape_final_omite_a_nota_onde_nao_ha_valor(cliente: TestClient):
    # O índice (V4-I) exibe valores — KPIs e colunas numéricas — então leva a
    # nota; a busca segue sem valor nenhum e sem nota (achado A3).
    sem_nota = (BUSCA,)
    com_nota = (ESCOLA, MERCADO, INDICE)
    nota = "Esta página nunca troca dado ausente por zero"

    for caminho in sem_nota:
        assert nota not in _get(cliente, caminho).text, caminho
    for caminho in com_nota:
        assert nota in _get(cliente, caminho).text, caminho


# -- 4. índice `/app/mercados/`: 200 com 1 consulta; 303 e 422 sem consulta --


def test_indice_responde_200_com_a_tabela_de_municipios_e_uma_consulta(
    cliente: TestClient, navegacao_repo: FakeRepository
):
    navegacao_repo.indice = fixture_853(
        [m.co_municipio for m in municipios_mg()]
    )
    navegacao_repo.calls.clear()
    resposta = _get(cliente, INDICE)

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/html")
    html = resposta.text
    total = len(municipios_mg())
    # Uma linha SSR por município no DOM do protótipo, com o link da ficha.
    assert html.count('class="acao-tabela"') == total
    assert html.count("Abrir mercado") == total
    assert html.count(f'href="{INDICE}31') == total
    # Sem o select antigo: nada de `option` nem de campo nomeado.
    assert 'name="co_municipio"' not in html
    assert "<option" not in html
    # O número anunciado vem de `len(municipios_mg())`, nunca de literal.
    # Contador do protótipo: sem ponto final (o JS limpa o filtro igual).
    assert f"{total} municípios no recorte" in html
    assert f"{total} municípios no recorte." not in html
    assert 'role="status"' in html
    # 445 sem escola privada: marcador explícito, nunca 0 (P-V-1, variante A).
    assert html.count('title="sem escola privada ativa"') == 445 * 3
    # O 200 consulta uma vez; 303/422 (abaixo) continuam sem consulta.
    assert navegacao_repo.calls == [("get_indice_municipios", {"ano": 2025})]


def test_indice_tem_filtro_progressivo_no_cliente():
    """O filtro do índice é progressivo: SSR completo + refinamento em JS.

    O JS não roda no TestClient, então a cobertura é estática: o campo de
    busca, os ids que o `filtrarIndice` (`app.js`) procura, a coluna do nome
    lida do cabeçalho (o 4b tem `#` antes do nome), a tabela ordenável e o
    iniciador com a trava de idempotência.
    """
    texto = (TEMPLATES / "mercados_indice.html").read_text(encoding="utf-8")

    assert 'id="filtro-municipio"' in texto
    assert 'type="search"' in texto
    assert 'id="retorno-municipios"' in texto
    assert 'id="tabela-municipios"' in texto
    assert 'data-ordenavel' in texto
    assert 'data-tipo="texto"' in texto
    assert 'data-tipo="numero"' in texto
    assert 'id="indice-municipios"' in texto
    assert 'data-largura="{{ linha.largura }}"' in texto
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "filtrarIndice" in js
    assert "data-filtro-pronto" in js
    assert '"Município"' in js
    assert ".cela-barra__preenche[data-largura]" in js


def test_indice_redireciona_303_para_o_mercado_escolhido(
    cliente: TestClient, navegacao_repo: FakeRepository
):
    navegacao_repo.calls.clear()
    resposta = _get(
        cliente,
        INDICE,
        params={"co_municipio": MUNICIPIO},
        follow_redirects=False,
    )

    assert resposta.status_code == 303
    assert resposta.headers["location"] == MERCADO
    assert navegacao_repo.calls == []


def test_indice_com_municipio_invalido_responde_422_html_sem_consulta(
    cliente: TestClient, navegacao_repo: FakeRepository
):
    navegacao_repo.calls.clear()
    resposta = _get(cliente, INDICE, params={"co_municipio": "999"})

    assert resposta.status_code == 422
    assert resposta.headers["content-type"].startswith("text/html")
    html = resposta.text
    assert f'href="{INDICE}"' in html
    assert "Escolher um município" in html
    assert navegacao_repo.calls == []


def test_atalho_sem_barra_continua_existindo_fora_do_indice(cliente: TestClient):
    """O índice com barra convive com o atalho `/app/mercados` (P2): nenhum dos
    dois foi removido — um redireciona com `q`/vazio, o outro escolhe."""
    resposta = _get(
        cliente, f"{PREFIXO_WEB}/mercados", params={"co_municipio": MUNICIPIO},
        follow_redirects=False,
    )

    assert resposta.status_code == 303
    assert resposta.headers["location"] == MERCADO


# -- 5. JavaScript: só o asset único, com `defer` ---------------------------


def test_script_unico_e_o_app_js_com_defer():
    """Card `t_71b25279`: o front tem base de JS versionada com `defer`.

    Substitui a guarda de "zero JavaScript" do NAV-1: o shell continua completo
    sem JS, mas as únicas tags **executáveis** permitidas são as dos assets
    servidos pelo `AssetRegistry` — o `app.js` herdado de `base.html` em todas
    as telas, e só em `/` também o `landing.js` vendorizado do protótipo
    (card `t_e42049c1`: revelação, contadores, progresso). Nada de `<script>`
    inline. Ilhas de dados (`type="application/json"`, card V2 `t_cbd54a92`)
    não executam e passam: o `app.js` as lê por `textContent`.
    """
    for caminho in sorted(TEMPLATES.rglob("*.html")):
        texto = caminho.read_text(encoding="utf-8")
        for tag in re.findall(r"<script\b[^>]*>", texto):
            if 'type="application/json"' in tag:
                continue
            assert 'src="{{ js_url }}"' in tag or 'src="{{ js_landing_url }}"' in tag, (
                f"{caminho.name}: script sem src: {tag}"
            )
            if 'src="{{ js_landing_url }}"' in tag:
                assert caminho.name == "inicio.html", (
                    f"{caminho.name}: landing.js fora da landing: {tag}"
                )
            assert "defer" in tag, f"{caminho.name}: script sem defer: {tag}"
        assert texto.count("<script") <= 2, caminho.name

    assert sorted(p.name for p in STATIC.glob("*.js")) == ["app.js", "landing.js"]


# -- 6. orçamento do partial -------------------------------------------------


def test_header_renderizado_cabe_em_1_5_kb(cliente: TestClient):
    header = _header(_get(cliente, BUSCA).text)
    tamanho = len(header.encode("utf-8"))

    assert tamanho <= TETO_HEADER_BYTES, f"header com {tamanho} bytes"
