"""Orçamento de peso da landing `/` — card `t_386b791c` (spec §7).

Este é o teste que vale para **todos** os cards da landing (L1→L4): quem
engordar o HTML de `/` ou o `app.css` além do orçamento quebra aqui, antes do
review. Os limites, em bytes:

| Item | Bruto | gzip nível 6 |
|---|---|---|
| HTML de `/` | 65.536 B | 14.336 B |
| CSS total nas demais telas (3 stylesheets) | 66.560 B | 16.384 B |
| CSS total em `/` (até 4 stylesheets) | 73.728 B | 18.432 B |

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
#: Os três stylesheets base na ordem da cascata (D1-a): protótipo vendorizado
#: e o `app.css` app-only por último. `/` pode acrescentar um quarto, injetado
#: pelo bloco `estilos_pagina` do `base.html` — as demais telas não.
CSS_ORDEM = ("panorama.css", "panorama-telas.css", "app.css")

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
#: Teto do CSS **da landing**: os do P4 do plano `landing-d2.md` (73.728 B
#: brutos / 18.432 B em gzip), para o quarto stylesheet da landing caber sem
#: abrir o mesmo espaço nas outras telas.
LIMITE_CSS_LANDING_BRUTO = 73_728
LIMITE_CSS_LANDING_GZIP = 18_432
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

