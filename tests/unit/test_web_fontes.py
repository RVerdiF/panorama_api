"""Fontes self-hosted do front — card V1 `t_423aa547`.

O design do protótipo do dono (Open Design) usa três famílias: Source Serif 4
nos títulos, Inter no corpo e — no protótipo — IBM Plex Mono nos números. O
orçamento do card cortou o mono para `system-ui`: **3 arquivos, ≤ 200 KB**, sem
requisição externa.

O que este teste protege:

* o diretório `static/fonts/` existe com exatamente os 3 arquivos do subset, e
  o total não passa de 200 KB;
* cada `.woff2` é servido pelo `AssetRegistry` com hash e
  `Cache-Control: immutable` — nada de CDN;
* o `@font-face` do CSS **como servido** aponta para a URL com hash da fonte e
  declara `font-display: swap`;
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

#: Subset aprovado pelo card: Inter 400/600 + Source Serif 700.
ARQUIVOS_ESPERADOS = frozenset(
    {"inter-400.woff2", "inter-600.woff2", "source-serif-700.woff2"}
)

#: Orçamento de fontes do card (bytes).
TETO_FONTES_BYTES = 200 * 1024

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


def test_mono_cai_para_a_fonte_do_sistema_sem_arquivo_proprio(css_servido: str):
    """Sem IBM Plex Mono no subset: o `--fonte-mono` é do sistema."""
    assert "IBM Plex Mono" not in css_servido
    regra = re.search(r"--fonte-mono:\s*([^;]+);", css_servido)
    assert regra is not None
    assert "ui-monospace" in regra.group(1)


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
    assert len(blocos) >= 3, blocos

    servidas = {registro for registro in re.findall(r'url\("([^"]+)"\)', css_servido)}
    for bloco in blocos:
        assert "font-display: swap" in bloco, bloco
        fonte = re.search(r'url\("([^"]+)"\)', bloco)
        assert fonte is not None, bloco
        assert re.fullmatch(
            r"/app/static/[0-9a-f]{12}-[a-z0-9-]+\.woff2", fonte.group(1)
        ), fonte.group(1)
        assert fonte.group(1) in servidas

    # As três famílias declaradas; o mono não tem `@font-face`.
    for familia in ("Source Serif 4", "Inter"):
        assert f'font-family: "{familia}"' in css_servido, familia


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
