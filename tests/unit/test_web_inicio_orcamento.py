"""Orçamento de peso da landing `/` — card `t_386b791c` (spec §7).

Este é o teste que vale para **todos** os cards da landing (L1→L4): quem
engordar o HTML de `/` ou o `app.css` além do orçamento quebra aqui, antes do
review. Os limites, em bytes:

| Item | Bruto | gzip nível 6 |
|---|---|---|
| HTML de `/` | 65.536 B | 14.336 B |
| CSS total (3 stylesheets) | 66.560 B | 16.384 B |

O orçamento do **CSS** foi reescrito no card V1 (`t_423aa547`) quando o dono
entregou o protótipo do Open Design, revisto no V2 (`t_cbd54a92`) e de novo na
fundação D1 (`t_686b363e`): o visual do protótipo vive vendorizado em
`static/prototipo/{panorama,panorama-telas}.css`, linkados no `base.html`
antes do `app.css` app-only — 3 stylesheets. Medido na D1: 65.189 B brutos e
15.175 B em gzip no total (3 contextos gzip somem mais que 1 arquivo só).
O que o orçamento continua protegendo é a
**forma** dos recursos: stylesheets locais com hash, sem `@import`, sem origem
externa, e o custo comprimido total contido.

As fontes são orçamento à parte (`test_web_fontes.py`): 6 arquivos, ≤ 360 KB.

Além do peso, o orçamento inclui a forma dos recursos: **6 requests** na
primeira visita (o HTML, três stylesheets, o `app.js` com `defer` — card
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
from tests.unit.conftest import FakeRepository

INICIO = "/"
#: Os três stylesheets na ordem da cascata (D1-a): protótipo vendorizado e o
#: `app.css` app-only por último.
CSS_ORDEM = ("panorama.css", "panorama-telas.css", "app.css")

#: Limites do orçamento (bytes). O do CSS foi revisto na fundação D1
#: `t_686b363e` (ver o docstring): soma dos três stylesheets servidos —
#: medido 65.189 B / 15.175 B em gzip, tetos com folga em 65/16 KB.
LIMITE_HTML_BRUTO = 65_536
LIMITE_HTML_GZIP = 14_336
LIMITE_CSS_BRUTO = 66_560
LIMITE_CSS_GZIP = 16_384

#: Nível fixo: gzip -6 é o default dos servidores e o que o teste deve medir
#: para que o número não dependa do compressor do ambiente.
NIVEL_GZIP = 6

#: `src`/`href` de origem externa (protocolo-relativo ou absoluto).
REFERENCIA = re.compile(r'(?:src|href)="([^"]*)"')
ESTILO = re.compile(r"<link[^>]*rel=\"stylesheet\"[^>]*>")
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
    from panorama_api.web.routes import assets

    registro = assets()
    brutos = 0
    comprimidos = 0
    for nome in CSS_ORDEM:
        asset = registro.get(registro.url(nome).rsplit("/", 1)[-1])
        assert asset is not None, f"asset ausente no registro: {nome}"
        corpo = asset.corpo
        brutos += len(corpo)
        comprimidos += _gzip(corpo)
        print(f"{nome}: {len(corpo)} B brutos, {_gzip(corpo)} B em gzip (nível {NIVEL_GZIP})")
    print(f"CSS total: {brutos} B brutos, {comprimidos} B em gzip")

    assert brutos <= LIMITE_CSS_BRUTO, f"CSS total com {brutos} B > {LIMITE_CSS_BRUTO} B"
    assert comprimidos <= LIMITE_CSS_GZIP, (
        f"CSS total com {comprimidos} B em gzip > {LIMITE_CSS_GZIP} B"
    )


# -- forma dos recursos: 3 stylesheets com hash, sem terceiros ------------


def test_landing_carrega_so_o_app_js_local(html_da_landing: bytes):
    html = html_da_landing.decode("utf-8")

    scripts = SCRIPT.findall(html)
    assert len(scripts) == 1, f"esperado 1 script, achei {len(scripts)}"
    assert ASSET_JS.search(scripts[0]), scripts[0]
    assert "<img" not in html.lower()
    assert "<iframe" not in html.lower()


def test_landing_tem_os_tres_stylesheets_versionados_em_ordem(html_da_landing: bytes):
    html = html_da_landing.decode("utf-8")
    estilos = ESTILO.findall(html)

    assert len(estilos) == 3, f"esperados 3 stylesheets, achei {len(estilos)}"
    # Protótipo vendorizado antes do app-only: a cascata decide o efetivo.
    for tag, nome in zip(estilos, CSS_ORDEM):
        esperado = re.compile(
            rf'href="/app/static/[0-9a-f]{{12}}-{re.escape(nome)}"'
        )
        assert esperado.search(tag), (tag, nome)


def test_landing_nao_referencia_origem_externa(html_da_landing: bytes):
    html = html_da_landing.decode("utf-8")
    externos = [
        url for url in REFERENCIA.findall(html) if url.startswith(("http://", "https://", "//"))
    ]

    assert externos == []


def test_css_sem_import_e_url_externa():
    """Só assets locais com hash. Cada CSS é lido **como servido** (pós-registro)."""
    from panorama_api.web.routes import assets

    registro = assets()
    todas_urls: list[tuple[str, str]] = []
    for nome in CSS_ORDEM:
        asset = registro.get(registro.url(nome).rsplit("/", 1)[-1])
        assert asset is not None, f"asset ausente no registro: {nome}"
        css = asset.corpo.decode("utf-8")

        assert "@import" not in css, nome
        # Fontes self-hosted: o CSS tem `url()` só para fontes locais com hash
        # (o registro resolve `{{asset:}}` e `../fonts/` no boot). Nenhuma
        # origem externa e nenhum placeholder: a referência tem de estar
        # resolvida nos bytes que o navegador recebe. (`panorama-telas.css`
        # não tem `url()` — só estrutura; as fontes vivem nos outros dois.)
        assert "http://" not in css, nome
        assert "https://" not in css, nome
        assert "{{asset:" not in css, nome
        assert "../fonts/" not in css, nome
        urls = re.findall(r"url\(([^)]*)\)", css)
        for url in urls:
            todas_urls.append((nome, url))
            assert re.fullmatch(r'"/app/static/[0-9a-f]{12}-[a-z0-9-]+\.woff2"', url), (nome, url)
            # A URL aponta para um asset que o handler de fato serve.
            assert registro.get(url.strip('"').rsplit("/", 1)[-1]) is not None, (nome, url)
    assert todas_urls, "nenhum url() nos stylesheets? as fontes sumiram"
