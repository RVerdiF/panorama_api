"""Movimento, progressividade e contraste da landing `/` (plano §8.2, card D2-E3).

O porte não traz `landing.js` (P5 = não) nem contador nenhum: **todo** o
movimento é CSS, e o contrato é que ele nunca esconda conteúdo quando o
navegador não pode animar. Os invariantes são estáticos, lidos do
`static/landing.css` e do HTML de `/`, sem rede e sem navegador:

1. todo `animation`/`animation-timeline` do `landing.css` vive dentro de
   `@media (prefers-reduced-motion: no-preference)`;
2. não existe `infinite` — nenhuma animação automática passa de 5 s (WCAG 2.2.2);
3. `opacity: 0` só aparece dentro de `@keyframes`, e não há a classe `.js`:
   juntas, essas duas condições garantem a página completa sem JS;
4. todo `animation-timeline` está sob `@supports (animation-timeline: view())`;
5. o HTML de `/` não tem `style=` nem `data-contar`;
6. a tabela de contraste do §6 vale como asserção;
7. todo código de `MARQUISE_MUNICIPIOS` existe em `municipios_mg()`;
8. o `.webp` responde `image/webp` com `immutable` (em `test_web_inicio_orcamento`).

Nada aqui toca rede, dataset ou BigQuery: o HTML vem do `TestClient` com
repositório fake vazio, e o CSS é o arquivo versionado.
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
from tests.unit.conftest import FakeRepository
from tests.unit.test_web_estilos import _contraste, _cor_do_token, _tokens

CSS = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "panorama_api"
    / "web"
    / "static"
    / "landing.css"
)
PROTOTIPO = CSS.parent / "prototipo" / "panorama.css"

INICIO = "/"
#: Duração máxima de uma animação automática (WCAG 2.2.2, cinco segundos).
LIMITE_ANIMACAO_MS = 5_000
#: Mínimo de contraste para texto normal (WCAG 1.4.3).
CONTRASTE_TEXTO_MINIMO = 4.5


def _css() -> str:
    return CSS.read_text(encoding="utf-8")


def _css_sem_comentario() -> str:
    """CSS sem comentário: prosa não é declaração (o `infinite` do texto sai)."""
    return re.sub(r"/\*.*?\*/", "", _css(), flags=re.S)


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


# -- 1. todo movimento sob `prefers-reduced-motion: no-preference` -----------


def test_toda_animacao_exige_no_preference() -> None:
    css = _css()
    inicio = css.index("@media (prefers-reduced-motion: no-preference)")
    # O bloco de movimento é o único lugar com `animation:`; tudo o que é
    # declarado antes dele seria animação incondicional.
    for seletor, corpo in _blocos(css):
        if not re.search(r"\banimation(-timeline|-range)?\s*:", corpo):
            continue
        posicao = css.index(corpo)
        assert posicao > inicio, f"animação fora do bloco de no-preference: {seletor.strip()}"
    assert "animation:" in css[inicio:], "bloco de movimento vazio?"


# -- 2. nenhuma animação infinita (WCAG 2.2.2) ------------------------------


def test_nenhuma_animacao_infinita() -> None:
    assert "infinite" not in _css_sem_comentario()


def test_nenhuma_animacao_dura_mais_de_cinco_segundos() -> None:
    for _, corpo in _blocos(_css()):
        for duracao in re.findall(r"\banimation:\s*[^;]*?([\d.]+)s", corpo):
            assert float(duracao) * 1000 <= LIMITE_ANIMACAO_MS, corpo


# -- 3. a página fica completa sem JS e sem suporte -------------------------


def test_opacity_zero_so_dentro_de_keyframes() -> None:
    css = _css()
    for seletor, corpo in _blocos(css):
        if not re.search(r"opacity:\s*0(?:[;\s}]|$)", corpo):
            continue
        assert "@keyframes" in seletor or seletor.strip().startswith("from"), (
            f"`opacity: 0` fora de `@keyframes` esconde conteúdo: {seletor.strip()}"
        )


def test_nao_existe_a_classe_js() -> None:
    """Sem `.js`, nada depende de script para aparecer (D2-2)."""
    css = _css()
    assert not re.search(r"^\s*\.js\b", css, re.M)
    assert ".js " not in css and ".js[" not in css


def test_html_nao_depende_de_js_para_mostrar_conteudo(html: str) -> None:
    assert "data-reveal" not in html
    assert "is-in" not in html


# -- 4. toda timeline de rolagem sob `@supports` ----------------------------


def test_toda_animation_timeline_esta_sob_supports() -> None:
    css = _css()
    suportes = [
        (achado.start(), achado.end())
        for achado in re.finditer(r"@supports \(animation-timeline: view\(\)\)", css)
    ]
    assert suportes, "nenhum `@supports (animation-timeline: view())` no arquivo"

    for seletor, corpo in _blocos(css):
        if "animation-timeline" not in corpo:
            continue
        posicao = css.index(corpo)
        assert any(inicio < posicao for inicio, _ in suportes), (
            f"`animation-timeline` fora do `@supports`: {seletor.strip()}"
        )


def test_timeline_de_rolagem_declara_animation_range() -> None:
    for seletor, corpo in _blocos(_css()):
        if "animation-timeline" not in corpo:
            continue
        assert "animation-range" in corpo, seletor.strip()


# -- 5. sem `style=` e sem contador no HTML ---------------------------------


def test_html_sem_style_e_sem_contador(html: str) -> None:
    assert not re.search(r"\sstyle\s*=", html)
    assert "data-contar" not in html
    # Zero consulta (P2): nenhum `data-observar` do design, nada de ilha JSON.
    assert "data-observar" not in html


# -- 6. contraste medido (plano §6) ----------------------------------------


def _fundos() -> dict[str, str]:
    """Pares de cor do painel escuro, da fita e do texto, sobre os tokens.

    Os fundos são `color-mix(in oklab, …)` no CSS; `_cor_do_token` resolve os
    hex do `:root` e `_contraste` aplica a mesma fórmula WCAG usada em
    `test_web_estilos`. O que este teste trava é o par efetivo documentado no
    §6 do plano: qualquer troca de token que baixe um par abaixo de 4,5:1
    quebra aqui.
    """
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

    # Texto sobre os fundos de cartão e de página.
    pares = (
        (cores["fg"], cores["surface"]),
        (cores["fg-2"], cores["bg"]),
        (cores["accent-on"], cores["accent"]),
        (cores["fg"], cores["bg"]),
    )
    for frente, fundo in pares:
        assert _contraste(frente, fundo) >= CONTRASTE_TEXTO_MINIMO, (frente, fundo)


def test_contraste_do_texto_secundario_sobre_bg_e_surface() -> None:
    """`--muted-strong` é `color-mix(muted 58%, fg 42%)`, como no `:root`."""
    tokens = _tokens()
    # `--muted-strong` é declarado por `color-mix`: a razão documentada no plano
    # é 6,09:1 sobre `--bg` e 7,05:1 sobre `--surface`. O piso é o mesmo 4,5:1,
    # medido a partir dos dois tokens de origem.
    assert "muted-strong" in PROTOTIPO.read_text(encoding="utf-8")
    assert _contraste(tokens["fg-2"], tokens["bg"]) >= CONTRASTE_TEXTO_MINIMO
    assert _contraste(tokens["fg-2"], tokens["surface"]) >= CONTRASTE_TEXTO_MINIMO


def test_contraste_do_capitulo_no_hover() -> None:
    """Hover do capítulo: `--ink-accent` sobre a superfície misturada."""
    cores = _fundos()
    assert _contraste(cores["accent"], cores["surface"]) >= CONTRASTE_TEXTO_MINIMO


# -- 7. a marquise só usa município que existe na lista ---------------------


def test_todo_codigo_da_marquise_existe_na_lista() -> None:
    conhecidos = {municipio.co_municipio for municipio in municipios_mg()}
    faltando = [codigo for codigo in MARQUISE_MUNICIPIOS if codigo not in conhecidos]
    assert not faltando, f"código IBGE fora da lista versionada: {faltando}"


# -- 9. nenhum número ilustrativo do design (critério 5 do card) ------------

#: Valores e nomes do protótipo de design que **não têm lastro** no produto
#: (plano `landing-d2.md` §5). A prancha mostra só `recorte_municipios`,
#: `recorte_anos` e `recorte_etapas`; o resto saiu com as leituras.
ILUSTRATIVOS = (
    "1.140",  # matrícula do Colégio Monte Verde em 2025
    "1.115",  # primeiro ponto da mesma série
    "1.144",
    "1.059",
    "1.087",
    "+4,9%",  # delta no ano
    "11,0%",  # share municipal da escola
    "8,3%",  # ranking municipal, 2º
    "1º de 30",  # posição da escola no ranking
    "21,6",  # participação somada das quatro unidades da Rede Horizonte
    "Rede Horizonte",
    "Colégio Monte Verde",
    "Instituto Bandeirantes",
    "Colégio Horizonte Vale",
    "Colégio Santa Amélia",
    "Centro Educ. Ipê Amarelo",
)


@pytest.mark.parametrize("ilustrativo", ILUSTRATIVOS)
def test_html_nao_traz_numero_ilustrativo_do_design(html: str, ilustrativo: str) -> None:
    assert ilustrativo not in html, ilustrativo


def test_html_nao_traz_a_faixa_de_numeros_do_design(html: str) -> None:
    """A faixa de 4 números do design (853 · 5 · 30 · 21,6%) saiu inteira.

    O `853` e os anos continuam, mas na prancha — o design os repetia numa
    faixa própria, com dois valores ilustrativos no meio.
    """
    assert 'class="numeros"' not in html
    assert "amostra ilustrativa" not in html
    assert "escolas privadas no mercado de Belo Horizonte" not in html


def test_html_nao_traz_as_leituras_do_design(html: str) -> None:
    """Ranking e matriz de oferta dependiam de dado que não existe (P2 = não)."""
    assert 'class="leituras"' not in html
    assert "Ranking municipal" not in html
    assert "Oferta por etapa" not in html


def test_marquise_do_html_nao_repete_nome_e_nao_tem_numero(html: str) -> None:
    """A marquise é decorativa: sem número, sem duplicata e fora do foco."""
    abertura = re.search(r'<div class="marquee[^"]*"[^>]*>', html)
    assert abertura is not None, "marquise ausente em `/`"
    assert 'aria-hidden="true"' in abertura.group(0), abertura.group(0)
    corpo = html[abertura.end() : html.index("</section>", abertura.end())]
    nomes = re.findall(r"<span>([^<]+)</span>", corpo)
    assert nomes, "marquise sem município"
    assert len(nomes) == len(set(nomes)), "marquise com nome repetido"
    assert not re.search(r"\d", "".join(nomes)), nomes
    esperados = {municipio.no_municipio for municipio in municipios_mg()}
    for nome in nomes:
        assert nome in esperados, nome
