"""Orçamento de peso da landing `/` — card `t_e42049c1` (porte literal, V5).

Este é o teste que vale para **todos** os cards da landing (L1→L4 e V5): quem
engordar o HTML de `/` ou o `app.css` além do orçamento quebra aqui, antes do
review. Os limites, em bytes:

| Item | Bruto | gzip nível 6 |
|---|---|---|
| HTML de `/` | 65.536 B | 14.336 B |
| CSS total nas demais telas (3 stylesheets) | 66.560 B | 16.384 B |
| CSS total em `/` (4 stylesheets) | 88.064 B | 21.504 B |

O teto de `/` subiu no V5 (`t_e42049c1`): o `landing.css` agora é o do
protótipo verbatim (26.679 B) mais a seção de `:nth-child()` que substitui
os 40 `style=` inline (a CSP é `style-src 'self'`). Medido: 83.981 B brutos
e 20.078 B em gzip no total (4 contextos gzip somem mais que 1 arquivo só).
Diferença para o teto antigo do P4 (73.728 B / 18.432 B): +10.253 B brutos
(+13,9%) e +1.646 B em gzip (+8,9%) — é o peso do design, não folga.

O teto de `/` é o do **P4** aprovado no plano `landing-d2.md` (card
`t_891eee10`): o porte da landing acrescenta um quarto stylesheet, carregado
só em `/`, e o orçamento por página impede que esse crescimento vaze para as
outras telas. O orçamento do **CSS** foi reescrito no card V1 (`t_423aa547`)
quando o dono entregou o protótipo do Open Design, revisto no V2
(`t_cbd54a92`) e de novo na fundação D1 (`t_686b363e`): o visual do protótipo
vive vendorizado em `static/prototipo/{panorama,panorama-telas}.css`,
linkados no `base.html` antes do `app.css` app-only — 3 stylesheets. Medido na
D1: 65.189 B brutos e 15.175 B em gzip no total (3 contextos gzip somem mais
que 1 arquivo só).
O que o orçamento continua protegendo é a
**forma** dos recursos: stylesheets locais com hash, sem `@import`, sem origem
externa, e o custo comprimido total contido.

A imagem da landing também é orçamento: o WebP servido com hash e
`immutable`, dentro dos bytes e das dimensões do design.

As fontes são orçamento à parte (`test_web_fontes.py`): 6 arquivos, ≤ 360 KB.

Além do peso, o orçamento inclui a forma dos recursos: **8 requests** na
primeira visita (o HTML, quatro stylesheets, o `app.js` e o `landing.js` com
`defer` — card `t_e42049c1` — e o `preload` da fonte do corpo, card V1), um
`<img>` (a foto da banda), nenhum `<iframe>`, `@import` ou `url(` de origem
externa no CSS. A página continua legível sem JS: os scripts são melhoria
progressiva (revelação, contadores, progresso).

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
#: Os três stylesheets base na ordem da cascata (D1-a): protótipo vendorizado
#: e o `app.css` app-only por último. `/` acrescenta um quarto — o
#: `landing.css`, injetado pelo bloco `estilos_pagina` do `base.html` — e as
#: demais telas não.
CSS_ORDEM = ("panorama.css", "panorama-telas.css", "app.css")
#: A cascata de `/` (plano `landing-d2.md` §7): o quarto stylesheet entra entre
#: o protótipo e o app-only, para o recorte da landing vencer sem depender de
#: ordem implícita.
CSS_ORDEM_LANDING = ("panorama.css", "panorama-telas.css", "landing.css", "app.css")

#: Telas que **não** são a landing: continuam com os três stylesheets e com o
#: teto anterior. Todas respondem 200 com o repositório fake vazio.
OUTRAS_TELAS = ("/app/", "/app/metodologia", "/app/mercados/")

#: Limites do orçamento (bytes). O do CSS base foi revisto na fundação D1
#: `t_686b363e` (ver o docstring): soma dos três stylesheets servidos —
#: medido 65.189 B / 15.175 B em gzip, tetos com folga em 65/16 KB.
LIMITE_HTML_BRUTO = 65_536
LIMITE_HTML_GZIP = 14_336
LIMITE_CSS_BRUTO = 66_560
LIMITE_CSS_GZIP = 16_384
#: Teto do CSS **da landing**: revisto no V5 (`t_e42049c1`) para o peso do
#: design verbatim + a seção de `:nth-child()` (medido 83.981 B brutos /
#: 20.078 B em gzip, tetos com folga em 86/21 KB).
LIMITE_CSS_LANDING_BRUTO = 88_064
LIMITE_CSS_LANDING_GZIP = 21_504
#: Orçamento da foto da landing (P4): 1 WebP 960×540 de até 80 KB, e nenhuma
#: outra imagem no HTML de `/` (o teste de `<img>` continua abaixo).
LIMITE_IMAGEM_BRUTOS = 81_920
IMAGEM_LARGURA = 960
IMAGEM_ALTURA = 540
IMAGEM = "escola-felisburgo-mg.webp"

#: Nível fixo: gzip -6 é o default dos servidores e o que o teste deve medir
#: para que o número não dependa do compressor do ambiente.
NIVEL_GZIP = 6

#: `src`/`href` de origem externa (protocolo-relativo ou absoluto).
REFERENCIA = re.compile(r'(?:src|href)="([^"]*)"')
ESTILO = re.compile(r"<link[^>]*rel=\"stylesheet\"[^>]*>")
SCRIPT = re.compile(r"<script\b[^>]*>\s*</script>")
ASSET_JS = re.compile(r'src="/app/static/[0-9a-f]{12}-app\.js" defer')
ASSET_LANDING_JS = re.compile(r'src="/app/static/[0-9a-f]{12}-landing\.js" defer')
#: Tag `<img …>` inteira (o porte permite exatamente uma, a foto da banda).
IMAGEM_TAG = re.compile(r"<img\b[^>]*>")


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
    """HTML cru (sem gzip) de `/` (repositório fake vazio: blocos em 'sem dado')."""
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


def _soma_css(nomes: tuple[str, ...]) -> tuple[int, int, list[str]]:
    """Bruto e gzip-6 da soma dos stylesheets, com a linha de cada um."""
    from panorama_api.web.routes import assets

    if not nomes:
        return 0, 0, []
    registro = assets()
    brutos = 0
    comprimidos = 0
    linhas: list[str] = []
    for nome in nomes:
        asset = registro.get(registro.url(nome).rsplit("/", 1)[-1])
        assert asset is not None, f"asset ausente no registro: {nome}"
        corpo = asset.corpo
        brutos += len(corpo)
        comprimidos += _gzip(corpo)
        linhas.append(f"{nome}: {len(corpo)} B brutos, {_gzip(corpo)} B em gzip (nível {NIVEL_GZIP})")
    return brutos, comprimidos, linhas


def test_css_do_front_cabe_no_orcamento():
    """Teto das **demais telas**: os três stylesheets, sem o quarto da landing."""
    brutos, comprimidos, linhas = _soma_css(CSS_ORDEM)
    for linha in linhas:
        print(linha)
    print(f"CSS total das demais telas: {brutos} B brutos, {comprimidos} B em gzip")

    assert brutos <= LIMITE_CSS_BRUTO, f"CSS total com {brutos} B > {LIMITE_CSS_BRUTO} B"
    assert comprimidos <= LIMITE_CSS_GZIP, (
        f"CSS total com {comprimidos} B em gzip > {LIMITE_CSS_GZIP} B"
    )


def _href(tag: str) -> str:
    """URL do `href` de uma tag `<link ...>` (a dos assets: `/app/static/…`)."""
    achado = re.search(r'href="([^"]+)"', tag)
    assert achado is not None, tag
    return achado.group(1)


def _nomes_dos_stylesheets(html: str) -> tuple[str, ...]:
    """Nome público (`<hash>-<nome>`) de cada stylesheet da página, em ordem."""
    return tuple(_href(tag).rsplit("/", 1)[-1] for tag in ESTILO.findall(html))


def test_css_da_landing_tem_teto_proprio(html_da_landing: bytes):
    """Orçamento por página (P4): `/` soma os stylesheets que ela carrega."""
    html = html_da_landing.decode("utf-8")
    caminhos = _nomes_dos_stylesheets(html)
    nomes = tuple(re.sub(r"^[0-9a-f]{12}-", "", caminho) for caminho in caminhos)
    brutos, comprimidos, linhas = _soma_css(nomes)
    for linha in linhas:
        print(linha)
    print(f"CSS total de {INICIO} ({len(nomes)} stylesheets): {brutos} B brutos, {comprimidos} B em gzip")

    assert brutos <= LIMITE_CSS_LANDING_BRUTO, (
        f"CSS de `/` com {brutos} B > {LIMITE_CSS_LANDING_BRUTO} B"
    )
    assert comprimidos <= LIMITE_CSS_LANDING_GZIP, (
        f"CSS de `/` com {comprimidos} B em gzip > {LIMITE_CSS_LANDING_GZIP} B"
    )


# -- forma dos recursos: 3 stylesheets com hash, sem terceiros ------------


def test_landing_carrega_app_js_e_landing_js_com_defer(html_da_landing: bytes):
    """A landing soma o `landing.js` (V5) ao `app.js`: dois scripts, com `defer`."""
    html = html_da_landing.decode("utf-8")

    scripts = SCRIPT.findall(html)
    assert len(scripts) == 2, f"esperados 2 scripts, achei {len(scripts)}"
    assert ASSET_JS.search(scripts[0]), scripts[0]
    assert ASSET_LANDING_JS.search(scripts[1]), scripts[1]
    assert "<iframe" not in html.lower()

    # Exatamente uma imagem: a foto da banda, local, com hash, fora do caminho
    # crítico e com dimensões declaradas (P4). O design trazia a foto em `<img>`
    # sem orçamento; o porte fixa o contrato aqui.
    imagens = IMAGEM_TAG.findall(html)
    assert len(imagens) == 1, f"esperado 1 `<img>`, achei {len(imagens)}"
    img = imagens[0]
    assert re.search(rf'src="/app/static/[0-9a-f]{{12}}-{re.escape(IMAGEM)}"', img), img
    assert 'loading="lazy"' in img, img
    assert 'decoding="async"' in img, img
    assert f'width="{IMAGEM_LARGURA}"' in img and f'height="{IMAGEM_ALTURA}"' in img, img
    alt = re.search(r'alt="([^"]*)"', img)
    assert alt is not None and alt.group(1).strip(), img


def test_landing_tem_os_quatro_stylesheets_versionados_em_ordem(html_da_landing: bytes):
    html = html_da_landing.decode("utf-8")
    estilos = ESTILO.findall(html)

    assert len(estilos) == 4, f"esperados 4 stylesheets, achei {len(estilos)}"
    # Protótipo antes do recorte da landing, e o app-only fechando a cascata.
    for tag, nome in zip(estilos, CSS_ORDEM_LANDING):
        esperado = re.compile(
            rf'href="/app/static/[0-9a-f]{{12}}-{re.escape(nome)}"'
        )
        assert esperado.search(tag), (tag, nome)


def test_landing_nao_referencia_origem_externa(html_da_landing: bytes):
    """Recurso externo é proibido; `<a href>` externo só no crédito da foto.

    A foto do Commons é CC BY-SA 4.0 e a licença exige o link para o arquivo e
    para a licença (plano §9). Por isso a única origem externa admitida é o
    crédito — e nenhuma delas em `src`.
    """
    html = html_da_landing.decode("utf-8")
    externos = [
        url for url in REFERENCIA.findall(html) if url.startswith(("http://", "https://", "//"))
    ]

    assert externos, "o crédito da foto tem de linkar a origem e a licença"
    for url in externos:
        assert url.startswith(
            ("https://commons.wikimedia.org/", "https://creativecommons.org/")
        ), url
    assert "src=\"http" not in html
    assert "href=\"http" not in "".join(ESTILO.findall(html))


def test_css_sem_import_e_url_externa():
    """Só assets locais com hash. Cada CSS é lido **como servido** (pós-registro)."""
    from panorama_api.web.routes import assets

    registro = assets()
    todas_urls: list[tuple[str, str]] = []
    for nome in CSS_ORDEM_LANDING:
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


# -- orçamento por página: as demais telas não crescem --------------------


@pytest.mark.parametrize("caminho", OUTRAS_TELAS)
def test_demais_telas_continuam_com_tres_stylesheets(caminho: str):
    """O quarto stylesheet é da landing: as outras telas seguem com os três.

    Protege o P4 do plano: o teto novo de `/` é por página, e nada dele vaza
    para telas que não são a landing.
    """
    app = create_app(settings=_settings(), repository=FakeRepository())
    with TestClient(app) as cliente:
        resposta = cliente.get(caminho)

    assert resposta.status_code == 200, caminho
    estilos = ESTILO.findall(resposta.text)

    assert len(estilos) == 3, f"{caminho}: esperados 3 stylesheets, achei {len(estilos)}"
    for tag, nome in zip(estilos, CSS_ORDEM):
        esperado = re.compile(rf'href="/app/static/[0-9a-f]{{12}}-{re.escape(nome)}"')
        assert esperado.search(tag), (caminho, tag, nome)
    assert "landing.css" not in resposta.text, caminho


# -- a imagem da landing: orçamento de bytes, dimensões e cache -------------


def _dimensoes_webp(corpo: bytes) -> tuple[int, int]:
    """Largura e altura de um WebP, sem dependência: lê o cabeçalho RIFF."""
    assert corpo[:4] == b"RIFF" and corpo[8:12] == b"WEBP", "não é WebP"
    tipo = corpo[12:16]
    if tipo == b"VP8 ":  # com perda: sinal de sincronia 9d 01 2a e 14 bits
        assert corpo[23:26] == b"\x9d\x01\x2a", "frame VP8 sem start code"
        largura = int.from_bytes(corpo[26:28], "little") & 0x3FFF
        altura = int.from_bytes(corpo[28:30], "little") & 0x3FFF
        return largura, altura
    if tipo == b"VP8X":  # estendido: canvas de 24 bits em menos um
        largura = int.from_bytes(corpo[24:27], "little") + 1
        altura = int.from_bytes(corpo[27:30], "little") + 1
        return largura, altura
    if tipo == b"VP8L":  # sem perda: 14 bits cada, em menos um
        bits = int.from_bytes(corpo[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    raise AssertionError(f"chunk WebP desconhecido: {tipo!r}")


def test_imagem_da_landing_cabe_no_orcamento():
    from panorama_api.web.routes import STATIC_DIR

    caminho = STATIC_DIR / "img" / IMAGEM
    assert caminho.is_file(), f"imagem ausente: {caminho}"

    corpo = caminho.read_bytes()
    largura, altura = _dimensoes_webp(corpo)
    print(f"{IMAGEM}: {len(corpo)} B, {largura}×{altura}")

    assert len(corpo) <= LIMITE_IMAGEM_BRUTOS, (
        f"{IMAGEM} com {len(corpo)} B > {LIMITE_IMAGEM_BRUTOS} B"
    )
    assert (largura, altura) == (IMAGEM_LARGURA, IMAGEM_ALTURA), (largura, altura)


def test_imagem_da_landing_e_servida_como_webp_imutavel():
    """Critério do card: `200` + `image/webp` + `immutable` na URL com hash."""
    from panorama_api.web.routes import assets

    registro = assets()
    url = registro.url(IMAGEM)
    assert re.fullmatch(rf"/app/static/[0-9a-f]{{12}}-{re.escape(IMAGEM)}", url), url
    asset = registro.get(url.rsplit("/", 1)[-1])
    assert asset is not None, url

    app = create_app(settings=_settings(), repository=FakeRepository())
    with TestClient(app) as cliente:
        resposta = cliente.get(url)

    assert resposta.status_code == 200, url
    assert resposta.headers["content-type"] == "image/webp", resposta.headers["content-type"]
    assert resposta.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert resposta.headers["x-content-type-options"] == "nosniff"
    assert resposta.content == asset.corpo


# -- o `landing.js` da landing: orçamento, servido e construções ---------------


#: Orçamento do `landing.js` vendorizado (V5, byte a byte do protótipo, sem
#: minificação). O teto é o tamanho real medido (`wc -c`, 4269) com folga.
ORCAMENTO_LANDING_JS = 8_192

#: Construções proibidas num arquivo sob CSP estrita sem `'unsafe-eval'`
#: (mesma lista do `app.js`: o `landing.js` do design usa `textContent` e
#: CSSOM, nunca `innerHTML`).
PROIBIDOS_LANDING_JS = ("eval(", "innerHTML", "new Function", "document.write")


def test_landing_js_e_servido_como_javascript_imutavel():
    """Critério 10 do card: `200` + `immutable` + `text/javascript` na URL com hash."""
    from panorama_api.web.routes import STATIC_DIR, assets

    assert (STATIC_DIR / "landing.js").is_file(), "landing.js ausente em static/"

    registro = assets()
    url = registro.url("landing.js")
    assert re.fullmatch(r"/app/static/[0-9a-f]{12}-landing\.js", url), url

    app = create_app(settings=_settings(), repository=FakeRepository())
    with TestClient(app) as cliente:
        resposta = cliente.get(url)

    assert resposta.status_code == 200, url
    assert resposta.headers["content-type"] == "text/javascript; charset=utf-8"
    assert resposta.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert resposta.headers["x-content-type-options"] == "nosniff"


def test_landing_js_cabe_no_orcamento_de_8192_bytes():
    from panorama_api.web.routes import STATIC_DIR

    tamanho = len((STATIC_DIR / "landing.js").read_bytes())
    print(f"landing.js: {tamanho} B brutos")

    assert tamanho <= ORCAMENTO_LANDING_JS, f"landing.js com {tamanho} bytes"


def test_landing_js_nao_usa_construcoes_incompativeis_com_a_csp():
    from panorama_api.web.routes import STATIC_DIR

    fonte = (STATIC_DIR / "landing.js").read_text(encoding="utf-8")
    for proibido in PROIBIDOS_LANDING_JS:
        assert proibido not in fonte, proibido

