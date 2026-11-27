"""Movimento e progressividade da landing `/` — card `t_e42049c1` (Regra Zero).

O design usa JS (`landing.js` vendorizado em `static/landing.js`): a classe
`js` no `<html>`, a revelação `[data-reveal]` → `is-in`, os contadores
(`data-contar`), a barra de progresso (`#progresso`) e a navbar compacta
(`data-compacto`). O movimento do CSS é o do protótipo — marquee em loop
infinito de 52 s, pulso de 2,8 s — e tudo respeita `prefers-reduced-motion`.

Os invariantes são estáticos, lidos do `static/landing.css`, do
`static/landing.js` e do HTML de `/`, sem rede e sem navegador:

1. `.js [data-reveal]` e `.js [data-reveal].is-in` existem no CSS, e o
   `landing.js` põe a classe `js` no `<html>`;
2. o HTML de `/` tem 28 `data-reveal`, 5 `data-contar` e 2 `data-observar`;
3. zero `style=` no HTML (os 40 valores do design vivem como `:nth-child()`
   no CSS, na mesma ordem);
4. o conjunto de `@keyframes` é o do protótipo (nem mais, nem menos);
5. a marquee repete a sequência 2×, é `aria-hidden` e pausa no hover;
6. o bloco `prefers-reduced-motion: reduce` neutraliza o movimento;
7. a tabela de contraste do §6 do plano antigo vale como asserção;
8. todo código de `MARQUISE_MUNICIPIOS` existe em `municipios_mg()`;
9. o `.webp` responde `image/webp` com `immutable` (em
   `test_web_inicio_orcamento`).

O que saiu com o porte literal (revogado pela Regra Zero):

* `test_nao_existe_a_classe_js`, `test_html_nao_depende_de_js...`,
  `test_html_sem_style_e_sem_contador` (antigo), `test_toda_animacao_exige_no_preference`,
  `test_nenhuma_animacao_infinita`, `test_nenhuma_animacao_dura_mais...` — o
  design usa JS e animações incondicionais; o substituto é a presença do
  mecanismo (itens 1–2) e o conjunto exato de keyframes (item 4);
* `test_html_nao_traz_*` (ilustrativos, faixa de números, leituras) — os
  literais do protótipo entram por definição; a asserção equivalente é a
  copy literal em `test_web_inicio.py`.

Nada aqui toca rede, dataset ou BigQuery: o HTML vem do `TestClient` com
repositório fake vazio, e o CSS/JS são os arquivos versionados.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.main import create_app
from panorama_api.web.conteudo import MARQUISE_MUNICIPIOS
from panorama_api.web.municipios import municipios_mg
from tests.unit.conftest import FakeRepository, share_row
from tests.unit.test_web_estilos import _contraste, _cor_do_token, _tokens

CSS = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "panorama_api"
    / "web"
    / "static"
    / "landing.css"
)
JS = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "panorama_api"
    / "web"
    / "static"
    / "landing.js"
)
PROTOTIPO = CSS.parent / "prototipo" / "panorama.css"

INICIO = "/"
#: Mínimo de contraste para texto normal (WCAG 1.4.3).
CONTRASTE_TEXTO_MINIMO = 4.5
#: O conjunto fechado de animações do protótipo (nem mais, nem menos).
KEYFRAMES_DO_DESIGN = frozenset(
    {"linha-sobe", "desenha", "aparece", "ponto-entra", "pulso", "desliza"}
)


def _css() -> str:
    return CSS.read_text(encoding="utf-8")


def _js() -> str:
    return JS.read_text(encoding="utf-8")


def _blocos(css: str) -> list[tuple[str, str]]:
    """Pares (seletor, corpo) de toda regra do arquivo."""
    return re.findall(r"([^{}]*)\{([^{}]*)\}", css)


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
def html() -> str:
    app = create_app(settings=_settings(), repository=FakeRepository())
    with TestClient(app) as cliente:
        resposta = cliente.get(
            INICIO, headers={"Accept-Encoding": "identity", "Accept": "text/html"}
        )
    assert resposta.status_code == 200
    return resposta.text


# -- 1. o mecanismo de revelação: `.js` + `is-in` ----------------------------


def test_revelacao_exige_a_classe_js() -> None:
    css = _css()

    assert ".js [data-reveal]" in css
    assert ".js [data-reveal].is-in" in css


def test_landing_js_poe_a_classe_js_no_html() -> None:
    js = _js()

    assert 'document.documentElement.classList.add("js")' in js


def test_revelacao_observa_rolagem_com_intersection_observer() -> None:
    js = _js()

    assert "IntersectionObserver" in js
    assert '"is-in"' in js or "'is-in'" in js
    assert "[data-reveal]" in js
    assert "[data-observar]" in js


def test_contadores_progresso_e_nav_compacta_no_js() -> None:
    js = _js()

    assert "[data-contar]" in js
    assert 'getElementById("progresso")' in js
    assert 'getElementById("nav")' in js
    assert '"data-compacto"' in js or "'data-compacto'" in js


# -- 2. o DOM que o JS espera --------------------------------------------------


def test_html_tem_os_ganchos_do_js(html: str) -> None:
    assert html.count("data-reveal") == 28
    assert html.count("data-contar") == 5
    assert html.count("data-observar") == 2
    assert 'id="progresso"' in html
    assert 'id="nav"' in html
    assert 'data-compacto="false"' in html


def test_html_sem_style_inline(html: str) -> None:
    """Os 40 `style=` do protótipo viraram `:nth-child()` no `landing.css`."""
    assert not re.search(r"\sstyle\s*=", html)


def test_atrasos_do_design_viraram_nth_child_no_css() -> None:
    css = _css()

    # Mesmos valores, mesma ordem do documento do protótipo (40 atributos).
    for regra in (
        ".hero__titulo .hero__linha:nth-child(1) > span { --d: 60ms; }",
        ".hero__lead { --d: 420ms; }",
        ".prancha[data-reveal] { --d: 340ms; }",
        ".numeros > div:nth-child(4) { --d: 270ms; }",
        ".capitulos > .capitulo:nth-child(3) { --d: 140ms; }",
        ".barras > li:nth-child(1) { --i: 0; }",
        ".barras > li:nth-child(5) { --i: 4; }",
        ".matriz > .matriz__linha:nth-child(7) { --i: 6; }",
        ".metodo__regras > .regra:nth-child(4) { --d: 240ms; }",
        ".fecho__acoes { --d: 140ms; }",
    ):
        assert regra in css, regra


def test_barras_sem_largura_fixa_de_mock() -> None:
    """As larguras mock 100/76/63/57/48% por posição saíram do CSS.

    O `:nth-child()` das barras carrega só o índice de entrada (`--i`); a
    largura (`--w`) vem das classes quantizadas `bw-N` (passo 5).
    """
    css = _css()

    for regra in (
        ".barras > li:nth-child(1) { --i: 0; --w: 100%; }",
        ".barras > li:nth-child(5) { --i: 4; --w: 48%; }",
    ):
        assert regra not in css, regra
    for largura_mock in ("--w: 76%", "--w: 63%", "--w: 57%", "--w: 48%"):
        assert largura_mock not in css, largura_mock
    for classe in ("bw-0", "bw-5", "bw-50", "bw-100"):
        assert f".barras > li.{classe}" in css, classe


def test_barras_proporcionais_ao_share() -> None:
    """A largura de cada barra é `share/max`, quantizada em passo 5 (`bw-N`)."""
    repo = FakeRepository(
        share=[
            share_row(
                id_entidade=f"3100000{i}",
                no_entidade=nome,
                mat_entidade=1000.0,
                share_privado_pct=share,
                nu_ano_censo=2025,
            )
            for i, (nome, share) in enumerate(
                (
                    ("Escola Alfa", 2.0),
                    ("Escola Beta", 1.9),
                    ("Escola Gama", 1.7),
                    ("Escola Delta", 1.6),
                    ("Escola Epsilon", 1.4),
                ),
                start=1,
            )
        ]
    )
    app = create_app(settings=_settings(), repository=repo)
    with TestClient(app) as cliente:
        resposta = cliente.get(
            INICIO, headers={"Accept-Encoding": "identity", "Accept": "text/html"}
        )

    assert resposta.status_code == 200
    classes = re.findall(r'<li class="(bw-\d+)"', resposta.text)
    assert classes == ["bw-100", "bw-95", "bw-85", "bw-80", "bw-70"], classes
    larguras = [int(classe.removeprefix("bw-")) for classe in classes]
    assert larguras == sorted(larguras, reverse=True), larguras
    for rotulo in ("2,0%", "1,9%", "1,7%", "1,6%", "1,4%"):
        assert rotulo in resposta.text, rotulo


def test_classe_largura_sem_dado_e_minimo_visivel() -> None:
    """`_classe_largura`: sem dado/max zerado vira `bw-0`; fiapo vira `bw-5`."""
    from panorama_api.web.routes import _classe_largura

    assert _classe_largura(None, 2.0) == "bw-0"
    assert _classe_largura(1.5, None) == "bw-0"
    assert _classe_largura(1.5, 0) == "bw-0"
    assert _classe_largura(0.0, 2.0) == "bw-0"
    assert _classe_largura(0.01, 2.0) == "bw-5"
    assert _classe_largura(2.0, 2.0) == "bw-100"


# -- 3. o conjunto de animações é o do protótipo -------------------------------


def test_keyframes_sao_os_do_design() -> None:
    keyframes = set(re.findall(r"@keyframes\s+([A-Za-z-]+)", _css()))

    assert keyframes == KEYFRAMES_DO_DESIGN


def test_marquee_em_loop_com_pausa_no_hover() -> None:
    css = _css()

    assert "animation: desliza 52s linear infinite;" in css
    assert ".marquee:hover .marquee__trilha { animation-play-state: paused; }" in css


def test_pulso_do_sinal_e_de_2_8s() -> None:
    assert "animation: pulso 2.8s ease-in-out infinite;" in _css()


def test_mascara_do_titulo_termina_visivel() -> None:
    """O `@keyframes` da máscara tem de terminar em `translateY(0)`."""
    css = re.sub(r"/\*.*?\*/", "", _css(), flags=re.S)
    keyframes = re.search(r"@keyframes linha-sobe\s*\{(.*?)\n\}", css, re.S)
    assert keyframes is not None, "@keyframes linha-sobe ausente"
    assert re.search(r"to\s*\{\s*transform:\s*translateY\(0\)", keyframes.group(1)), (
        keyframes.group(1)
    )
    regra = re.search(r"\.hero__linha > span\s*\{([^}]*)\}", css)
    assert regra is not None
    assert "translateY(112%)" in regra.group(1), regra.group(1)


def test_movimento_reduzido_neutraliza_o_design() -> None:
    css = _css()

    assert "@media (prefers-reduced-motion: reduce)" in css
    bloco = css[css.index("@media (prefers-reduced-motion: reduce)") :]
    for invariante in (
        ".marquee__trilha { animation: none; }",
        "[data-reveal] { opacity: 1; transform: none; }",
        ".hero__linha > span { transform: none; }",
    ):
        assert invariante in bloco, invariante


# -- 4. marquise: sequência duplicada, fora do foco ----------------------------


def test_marquise_do_html_repete_a_sequencia_2x(html: str) -> None:
    """O loop do marquee exige a sequência duplicada (é o design, não um erro)."""
    abertura = re.search(r'<div class="marquee[^"]*"[^>]*>', html)
    assert abertura is not None, "marquise ausente em `/`"
    assert 'aria-hidden="true"' in abertura.group(0), abertura.group(0)
    corpo = html[abertura.end() : html.index("</section>", abertura.end())]
    nomes = re.findall(r"<span>([^<]+)</span>", corpo)
    assert nomes, "marquise sem município"
    metade = len(nomes) // 2
    assert nomes[:metade] == nomes[metade:]
    assert not re.search(r"\d", "".join(nomes)), nomes
    esperados = {municipio.no_municipio for municipio in municipios_mg()}
    for nome in nomes:
        assert nome in esperados, nome


# -- 5. contraste medido (plano §6) -------------------------------------------


def _fundos() -> dict[str, str]:
    """Pares de cor do painel escuro, da fita e do texto, sobre os tokens."""
    tokens = _tokens()
    return {
        "surface": tokens["surface"],
        "bg": tokens["bg"],
        "fg": tokens["fg"],
        "fg-2": tokens["fg-2"],
        "accent": tokens["accent"],
        "accent-on": tokens["accent-on"],
    }


def test_contraste_dos_pares_do_painel_e_da_fita() -> None:
    cores = _fundos()

    pares = (
        (cores["fg"], cores["surface"]),
        (cores["fg-2"], cores["bg"]),
        (cores["accent-on"], cores["accent"]),
        (cores["fg"], cores["bg"]),
    )
    for frente, fundo in pares:
        assert _contraste(frente, fundo) >= CONTRASTE_TEXTO_MINIMO, (frente, fundo)


def test_contraste_do_texto_secundario_sobre_bg_e_surface() -> None:
    tokens = _tokens()
    assert "muted-strong" in PROTOTIPO.read_text(encoding="utf-8")
    assert _contraste(tokens["fg-2"], tokens["bg"]) >= CONTRASTE_TEXTO_MINIMO
    assert _contraste(tokens["fg-2"], tokens["surface"]) >= CONTRASTE_TEXTO_MINIMO


def test_contraste_do_capitulo_no_hover() -> None:
    cores = _fundos()
    assert _contraste(cores["accent"], cores["surface"]) >= CONTRASTE_TEXTO_MINIMO


# -- 6. a marquise só usa município que existe na lista ------------------------


def test_todo_codigo_da_marquise_existe_na_lista() -> None:
    conhecidos = {municipio.co_municipio for municipio in municipios_mg()}
    faltando = [codigo for codigo in MARQUISE_MUNICIPIOS if codigo not in conhecidos]
    assert not faltando, f"código IBGE fora da lista versionada: {faltando}"
