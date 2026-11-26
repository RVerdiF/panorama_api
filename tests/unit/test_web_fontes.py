"""Fontes self-hosted do front — card V1 `t_423aa547`, peça do protótipo V2.

O design do protótipo do dono (Open Design) usa três famílias: Source Serif 4
nos títulos, Inter no corpo e IBM Plex Mono nos números: **6 arquivos**,
servidos com hash e sem requisição externa.

O que este teste protege:

* o diretório `static/fonts/` existe com exatamente os 6 arquivos do protótipo,
  e o total não passa do teto;
* cada `.woff2` é servido pelo `AssetRegistry` com hash e
  `Cache-Control: immutable` — nada de CDN;
* cada `@font-face` **efetivo** (o último por família/peso, na seção
  `app-only` do `app.css`, que vem depois na cascata) aponta para a URL com
  hash da fonte e declara `font-display: swap` — os arquivos vendorizados
  do protótipo usam URLs relativas `../fonts/`, servidas em `/app/fonts/`;
* o `<head>` faz `preload` do Inter 400 (a fonte do corpo), com `crossorigin`,
  e o HTML não referencia nenhuma origem externa.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.main import create_app
from panorama_api.web.routes import STATIC_DIR, assets
from tests.unit.conftest import FakeRepository

FONTES = STATIC_DIR / "fonts"

#: Arquivos do protótipo: Inter 400/600 + Source Serif 600/700 + Plex Mono 400/500.
ARQUIVOS_ESPERADOS = frozenset(
    {
        "inter-400.woff2",
        "inter-600.woff2",
        "source-serif-600.woff2",
        "source-serif-700.woff2",
        "plex-mono-400.woff2",
        "plex-mono-500.woff2",
    }
)

#: Orçamento de fontes (bytes): 6 arquivos do protótipo com folga.
TETO_FONTES_BYTES = 360 * 1024

INICIO = "/"


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


@pytest.fixture(scope="module")
def css_servido() -> str:
    """O `app.css` como o navegador o recebe (referências já resolvidas)."""
    registro = assets()
    asset = registro.get(registro.url("app.css").rsplit("/", 1)[-1])
    assert asset is not None
    return asset.corpo.decode("utf-8")


def test_subset_de_fontes_tem_tres_arquivos_e_cabe_em_200_kb():
    arquivos = sorted(caminho for caminho in FONTES.glob("*.woff2"))

    assert {caminho.name for caminho in arquivos} == ARQUIVOS_ESPERADOS
    total = sum(caminho.stat().st_size for caminho in arquivos)
    print(f"fontes: {len(arquivos)} arquivos, {total} B")
    assert total <= TETO_FONTES_BYTES, f"{total} B > {TETO_FONTES_BYTES} B"


def test_mono_do_prototipo_tem_arquivo_proprio():
    """O `--font-mono` do protótipo é o IBM Plex Mono, servido aqui."""
    registro = assets()
    servido = registro.get(registro.url("panorama.css").rsplit("/", 1)[-1])
    assert servido is not None
    css_vendorizado = servido.corpo.decode("utf-8")
    assert "IBM Plex Mono" in css_vendorizado
    regra = re.search(r"--font-mono:\s*([^;]+);", css_vendorizado)
    assert regra is not None
    assert "IBM Plex Mono" in regra.group(1)


def test_cada_fonte_e_servida_com_hash_e_cache_imutavel():
    registro = assets()
    with TestClient(create_app(settings=_settings(), repository=FakeRepository())) as cliente:
        for nome in sorted(ARQUIVOS_ESPERADOS):
            url = registro.url(nome)
            assert re.fullmatch(rf"/app/static/[0-9a-f]{{12}}-{re.escape(nome)}", url), url

            resposta = cliente.get(url)
            assert resposta.status_code == 200, nome
            assert resposta.headers["cache-control"] == (
                "public, max-age=31536000, immutable"
            )
            assert resposta.headers["content-type"] == "font/woff2"


def test_font_face_aponta_para_a_url_com_hash_e_usa_swap(css_servido: str):
    blocos = re.findall(r"@font-face\s*\{(.*?)\}", css_servido, re.S)
    assert len(blocos) >= 6, blocos

    for bloco in blocos:
        assert "font-display: swap" in bloco, bloco

    # O `app.css` app-only só usa URLs com hash (as relativas `../fonts/`
    # vivem nos arquivos vendorizados do protótipo, servidas em `/app/fonts/`).
    # As efetivas por família/peso usam hash do próprio app.
    relativas = set(re.findall(r'url\("\.\./fonts/([a-z0-9-]+\.woff2)"\)', css_servido))
    assert relativas <= ARQUIVOS_ESPERADOS, relativas

    efetivos: dict[tuple[str, str], str] = {}
    for bloco in blocos:
        familia = re.search(r'font-family:\s*"([^"]+)"', bloco)
        peso = re.search(r"font-weight:\s*(\d+)", bloco)
        fonte = re.search(r'url\("([^"]+)"\)', bloco)
        assert familia is not None and peso is not None and fonte is not None, bloco
        efetivos[(familia.group(1), peso.group(1))] = fonte.group(1)

    servidas = set(re.findall(r'url\("([^"]+)"\)', css_servido))
    for (familia, peso), fonte in efetivos.items():
        assert re.fullmatch(
            r"/app/static/[0-9a-f]{12}-[a-z0-9-]+\.woff2", fonte
        ), (familia, peso, fonte)
        assert fonte in servidas

    # As três famílias declaradas, com os pesos do protótipo.
    for familia in ("Source Serif 4", "Inter", "IBM Plex Mono"):
        assert f'font-family: "{familia}"' in css_servido, familia


def test_fontes_no_caminho_relativo_do_prototipo_sem_404():
    """O `panorama.css` vendorizado declara `../fonts/*.woff2` (NÃO editável).

    A partir da URL do stylesheet isso resolve para `/app/fonts/*`: o
    servidor atende os 6 arquivos ali, imutáveis, e dá 404 de endereço fora
    da lista — sem esse caminho, o CSS vendorizado renderiza sem fonte.
    """
    app = create_app(settings=_settings(), repository=FakeRepository())
    with TestClient(app) as cliente:
        for nome in sorted(ARQUIVOS_ESPERADOS):
            resposta = cliente.get(f"/app/fonts/{nome}")
            assert resposta.status_code == 200, nome
            assert resposta.headers["cache-control"] == (
                "public, max-age=31536000, immutable"
            )
            assert resposta.headers["content-type"] == "font/woff2"
            assert resposta.content == (FONTES / nome).read_bytes(), nome

        assert cliente.get("/app/fonts/nao-existe.woff2").status_code == 404


def test_head_faz_preload_do_inter_400_com_crossorigin():
    app = create_app(settings=_settings(), repository=FakeRepository())
    with TestClient(app) as cliente:
        html = cliente.get(INICIO, headers={"Accept-Encoding": "identity"}).text

    preload = re.findall(r"<link[^>]*rel=\"preload\"[^>]*>", html)
    assert len(preload) == 1, preload
    assert 'as="font"' in preload[0]
    assert 'type="font/woff2"' in preload[0]
    assert "crossorigin" in preload[0]
    assert re.search(
        r'href="/app/static/[0-9a-f]{12}-inter-400\.woff2"', preload[0]
    ), preload[0]
    # O preload vem antes do stylesheet: é o ponto de antecipar o corpo do texto.
    assert html.index(preload[0]) < html.index('rel="stylesheet"')


def test_html_nao_referencia_origem_externa():
    app = create_app(settings=_settings(), repository=FakeRepository())
    with TestClient(app) as cliente:
        html = cliente.get(INICIO, headers={"Accept-Encoding": "identity"}).text

    externos = [
        url
        for url in re.findall(r'(?:src|href)="([^"]*)"', html)
        if url.startswith(("http://", "https://", "//"))
    ]
    assert externos == []
