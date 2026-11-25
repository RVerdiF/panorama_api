"""Orçamento de peso da landing `/` — card `t_386b791c` (spec §7).

Este é o teste que vale para **todos** os cards da landing (L1→L4): quem
engordar o HTML de `/` ou o `app.css` além do orçamento quebra aqui, antes do
review. Os limites, em bytes:

| Item | Bruto | gzip nível 6 |
|---|---|---|
| HTML de `/` | 65.536 B | 14.336 B |
| `app.css` | 45.056 B | 10.240 B |

O orçamento do **CSS** foi reescrito no card V1 (`t_423aa547`) quando o dono
entregou o protótipo do Open Design: o `app.css` deixou de ser uma folha de
documento (15.650 B) e passou a carregar o sistema visual inteiro — tokens,
escala tipográfica, cartões, navbar com bisel, tabela ordenável, chips,
paginação e estados —, o que vale 32,9 KB brutos e 7,9 KB em gzip medidos.
O teto antigo (16.384 B / 4.608 B) era de outra peça; mantê-lo obrigaria a
rejeitar o design que o card manda aplicar. O que o orçamento continua
protegendo é a **forma** do recurso: um único stylesheet, sem `@import`, sem
origem externa, e o custo comprimido contido em ~10 KB.

As fontes são orçamento à parte (`test_web_fontes.py`): 3 arquivos, ≤ 200 KB.

Além do peso, o orçamento inclui a forma do recurso: **4 requests** na primeira
visita (o HTML, um único stylesheet, o `app.js` com `defer` — card
`t_71b25279` — e o `preload` da fonte do corpo, card V1), nenhum `<img>`,
`<iframe>`, `@import` ou `url(` de origem externa no CSS. A página continua
funcionando sem JS: o script é só melhoria progressiva.

As medições são impressas (rode com `-s` para vê-las) e aparecem no handoff do
card. Nada aqui toca rede ou BigQuery: o HTML vem do `TestClient` com
repositório fake vazio e o CSS, do arquivo versionado.
"""

from __future__ import annotations

import gzip
import re

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.main import create_app
from panorama_api.web.routes import STATIC_DIR
from tests.unit.conftest import FakeRepository

INICIO = "/"
CSS = STATIC_DIR / "app.css"

#: Limites do orçamento (bytes). O do CSS foi revisto no card V1 `t_423aa547`
#: (ver o docstring): o app.css agora carrega o sistema visual do protótipo.
LIMITE_HTML_BRUTO = 65_536
LIMITE_HTML_GZIP = 14_336
LIMITE_CSS_BRUTO = 45_056
LIMITE_CSS_GZIP = 10_240

#: Nível fixo: gzip -6 é o default dos servidores e o que o teste deve medir
#: para que o número não dependa do compressor do ambiente.
NIVEL_GZIP = 6

#: `src`/`href` de origem externa (protocolo-relativo ou absoluto).
REFERENCIA = re.compile(r'(?:src|href)="([^"]*)"')
ESTILO = re.compile(r"<link[^>]*rel=\"stylesheet\"[^>]*>")
ASSET_CSS = re.compile(r'href="/app/static/[0-9a-f]{12}-app\.css"')
SCRIPT = re.compile(r"<script\b[^>]*>\s*</script>")
ASSET_JS = re.compile(r'src="/app/static/[0-9a-f]{12}-app\.js" defer')


def _settings() -> Settings:
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


@pytest.fixture
def html_da_landing() -> bytes:
    """HTML cru (sem gzip) de `/`: a landing não consulta o repositório."""
    app = create_app(settings=_settings(), repository=FakeRepository())
    with TestClient(app) as cliente:
        resposta = cliente.get(
            INICIO, headers={"Accept-Encoding": "identity", "Accept": "text/html"}
        )

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/html")
    return resposta.content


def _gzip(tamanho: bytes) -> int:
    return len(gzip.compress(tamanho, NIVEL_GZIP))


# -- peso --------------------------------------------------------------------


def test_html_da_landing_cabe_no_orcamento(html_da_landing: bytes):
    bruto = len(html_da_landing)
    comprimido = _gzip(html_da_landing)
    print(f"HTML de {INICIO}: {bruto} B brutos, {comprimido} B em gzip (nível {NIVEL_GZIP})")

    assert bruto <= LIMITE_HTML_BRUTO, f"HTML de `/` com {bruto} B > {LIMITE_HTML_BRUTO} B"
    assert comprimido <= LIMITE_HTML_GZIP, (
        f"HTML de `/` com {comprimido} B em gzip > {LIMITE_HTML_GZIP} B"
    )


def test_css_do_front_cabe_no_orcamento():
    corpo = CSS.read_bytes()
    bruto = len(corpo)
    comprimido = _gzip(corpo)
    print(f"{CSS.name}: {bruto} B brutos, {comprimido} B em gzip (nível {NIVEL_GZIP})")

    assert bruto <= LIMITE_CSS_BRUTO, f"{CSS.name} com {bruto} B > {LIMITE_CSS_BRUTO} B"
    assert comprimido <= LIMITE_CSS_GZIP, (
        f"{CSS.name} com {comprimido} B em gzip > {LIMITE_CSS_GZIP} B"
    )


# -- forma do recurso: 3 requests, sem terceiros -----------------------------


def test_landing_carrega_so_o_app_js_local(html_da_landing: bytes):
    html = html_da_landing.decode("utf-8")

    scripts = SCRIPT.findall(html)
    assert len(scripts) == 1, f"esperado 1 script, achei {len(scripts)}"
    assert ASSET_JS.search(scripts[0]), scripts[0]
    assert "<img" not in html.lower()
    assert "<iframe" not in html.lower()


def test_landing_tem_um_unico_stylesheet_versionado(html_da_landing: bytes):
    html = html_da_landing.decode("utf-8")
    estilos = ESTILO.findall(html)

    assert len(estilos) == 1, f"esperado 1 stylesheet, achei {len(estilos)}"
    # Asset local com hash de conteúdo (`/app/static/<hash>-app.css`).
    assert ASSET_CSS.search(estilos[0]), estilos[0]


def test_landing_nao_referencia_origem_externa(html_da_landing: bytes):
    html = html_da_landing.decode("utf-8")
    externos = [
        url for url in REFERENCIA.findall(html) if url.startswith(("http://", "https://", "//"))
    ]

    assert externos == []


def test_css_sem_import_e_sem_url_externa():
    """Só assets locais com hash. O CSS é lido **como servido** (pós-registro)."""
    from panorama_api.web.routes import assets

    registro = assets()
    asset = registro.get(registro.url("app.css").rsplit("/", 1)[-1])
    assert asset is not None
    css = asset.corpo.decode("utf-8")

    assert "@import" not in css
    # Fontes self-hosted (card V1 `t_423aa547`): o CSS ganhou `url()`, mas só
    # para assets locais com hash, servidos pelo próprio app. Nenhuma origem
    # externa, nenhum caminho relativo solto e nenhum placeholder: a referência
    # `{{asset:...}}` tem de estar resolvida nos bytes que o navegador recebe.
    assert "http://" not in css
    assert "https://" not in css
    assert "{{asset:" not in css
    urls = re.findall(r"url\(([^)]*)\)", css)
    assert urls, "o CSS deve referenciar as fontes locais"
    for url in urls:
        assert re.fullmatch(r'"/app/static/[0-9a-f]{12}-[a-z0-9-]+\.woff2"', url), url
        # A URL aponta para um asset que o handler de fato serve.
        assert registro.get(url.strip('"').rsplit("/", 1)[-1]) is not None, url
