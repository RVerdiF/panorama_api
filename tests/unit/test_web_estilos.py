"""Invariantes de acessibilidade dos controles em `web/static/app.css`.

Card `t_e9a9df42` (achados C1, C6 e D2 do relatório de UI). O CSS não tem
renderização testável aqui, mas os três invariantes que o card cobra são
numéricos e vivem no arquivo:

* borda de **controle** (input/select) com ≥3:1 sobre `#ffffff` — WCAG 1.4.11
  para o limite visual do controle, separada da borda decorativa de cartão;
* `:hover` em `a`, `button` e `.paginacao__link` (affordance de ponteiro);
* alvo de toque ≥44px em `.topo__nav a` e `.paginacao__link`;
* texto do painel do recorte da landing com ≥4,5:1 sobre o fundo `#eaf1f6`
  (card `t_437796c3`) — o painel não fica mais sobre o branco do cartão.

Um teste aqui impede que uma edição futura devolva a borda decorativa para o
input ou encolha de novo o link de navegação.
"""

from __future__ import annotations

import re
from pathlib import Path

CSS = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "panorama_api"
    / "web"
    / "static"
    / "app.css"
)

#: Mínimo de WCAG 1.4.11 (contraste de elemento não textual).
CONTRASTE_MINIMO = 3.0

#: Mínimo de alvo de toque do card (WCAG 2.5.5 é 44x44 CSS px).
ALVO_MINIMO_PX = 44


def _regra(seletor: str) -> str:
    """Declarações da regra cujo seletor é exatamente `seletor`."""
    css = CSS.read_text(encoding="utf-8")
    achado = re.search(rf"(?m)^{re.escape(seletor)}\s*\{{([^}}]*)\}}", css)
    assert achado is not None, f"regra ausente em app.css: {seletor}"
    return achado.group(1)


def _canal_linear(valor: int) -> float:
    canal = valor / 255
    return canal / 12.92 if canal <= 0.04045 else ((canal + 0.055) / 1.055) ** 2.4


def _luminancia(cor: str) -> float:
    """Luminância relativa WCAG de uma cor `#rrggbb`."""
    assert re.fullmatch(r"#[0-9a-fA-F]{6}", cor), f"cor não é #rrggbb: {cor!r}"
    r, g, b = (int(cor[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _canal_linear(r) + 0.7152 * _canal_linear(g) + 0.0722 * _canal_linear(b)


def _contraste(cor_a: str, cor_b: str) -> float:
    la, lb = sorted((_luminancia(cor_a), _luminancia(cor_b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_borda_de_controle_tem_contraste_de_3_para_1_sobre_branco():
    css = CSS.read_text(encoding="utf-8")
    achado = re.search(r"--cor-borda-controle:\s*(#[0-9a-fA-F]{6})", css)
    assert achado is not None, "variável --cor-borda-controle ausente"
    cor = achado.group(1)

    assert _contraste(cor, "#ffffff") >= CONTRASTE_MINIMO
    # O controle usa a variável de controle, não a decorativa de cartão.
    assert "var(--cor-borda-controle)" in _regra(".campo select")


def test_hover_em_link_botao_e_paginacao():
    css = CSS.read_text(encoding="utf-8")
    linhas_com_hover = [linha for linha in css.splitlines() if ":hover" in linha]

    assert len(linhas_com_hover) >= 2
    for seletor in ("a:hover", "button:hover", ".paginacao__link:hover"):
        assert seletor in css, f":hover ausente para {seletor}"


def test_acao_do_formulario_so_vira_linha_com_o_link_limpar():
    """Sem o link, a ação continua em coluna: o botão estica na largura da
    célula. A linha vale só quando `.limpar-filtros` existe (busca com filtro),
    senão o form do mercado — fora do escopo do card — muda de largura."""
    base = _regra(".campo--acao")
    assert "flex-direction" not in base, (
        "`.campo--acao` não deve trocar flex-direction na regra base"
    )

    linha = _regra(".campo--acao:has(.limpar-filtros)")
    assert "flex-direction: row" in linha


def test_alvos_de_toque_do_topo_e_da_paginacao_tem_44px():
    for seletor in (".topo__nav a", ".paginacao__link"):
        regra = _regra(seletor)
        altura = re.search(r"min-height:\s*(\d+)px", regra)

        assert "inline-flex" in regra, f"{seletor} precisa de display inline-flex"
        assert altura is not None, f"{seletor} sem min-height explícito"
        assert int(altura.group(1)) >= ALVO_MINIMO_PX


# -- hero da landing e painel do recorte (card t_437796c3) --------------------

#: Fundo do painel do recorte (spec §4): tom de `--cor-destaque`. O texto do
#: painel não fica mais sobre `#ffffff` — o contraste tem de ser medido aqui.
FUNDO_PAINEL = "#eaf1f6"

#: WCAG 1.4.3 para texto normal (o card pede 4,5:1, não os 3:1 de elemento).
CONTRASTE_TEXTO_MINIMO = 4.5


def test_texto_do_painel_do_recorte_tem_contraste_de_4_5_para_1():
    css = CSS.read_text(encoding="utf-8")
    texto = re.search(r"--cor-texto:\s*(#[0-9a-fA-F]{6})", css)
    suave = re.search(r"--cor-texto-suave:\s*(#[0-9a-fA-F]{6})", css)
    assert texto is not None and suave is not None

    assert _contraste(texto.group(1), FUNDO_PAINEL) >= CONTRASTE_TEXTO_MINIMO
    assert _contraste(suave.group(1), FUNDO_PAINEL) >= CONTRASTE_TEXTO_MINIMO


def test_painel_do_recorte_usa_o_fundo_e_o_raio_da_spec():
    css = CSS.read_text(encoding="utf-8")
    painel = _regra(".hero .recorte")

    assert f"background: {FUNDO_PAINEL}" in painel
    assert "border-radius: var(--raio-grande)" in painel
    # A variável nova é o 16 px da especificação, não um valor solto na regra.
    assert re.search(r"--raio-grande:\s*16px", css)


def test_rotulos_e_fonte_do_painel_usam_o_texto_suave_medido_acima():
    for seletor in (".recorte__rotulo", ".recorte__fonte"):
        assert "var(--cor-texto-suave)" in _regra(seletor), seletor


def test_hero_empilha_antes_de_48rem_e_vira_duas_colunas_depois():
    base = _regra(".hero")
    assert "display: grid" in base
    # Abaixo do breakpoint é uma coluna: nada de `1.1fr 0.9fr` na regra base.
    assert "display: flex" not in base
    assert "1.1fr" not in base

    css = CSS.read_text(encoding="utf-8")
    bloco = re.search(r"@media \(min-width: 48rem\)\s*\{(.*?)\n\}", css, re.S)
    assert bloco is not None, "breakpoint do hero ausente"
    assert ".hero" in bloco.group(1)
    assert "1.1fr 0.9fr" in bloco.group(1)


def test_nenhum_outline_none_no_css():
    """O foco visível de 3 px vale para o hero também: nada de removê-lo."""
    css = CSS.read_text(encoding="utf-8")

    assert re.search(r"outline:\s*(?:none|0)\b", css) is None
