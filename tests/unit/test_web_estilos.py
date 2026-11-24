"""Invariantes de acessibilidade dos controles em `web/static/app.css`.

Card `t_e9a9df42` (achados C1, C6 e D2 do relatório de UI). O CSS não tem
renderização testável aqui, mas os três invariantes que o card cobra são
numéricos e vivem no arquivo:

* borda de **controle** (input/select) com ≥3:1 sobre `#ffffff` — WCAG 1.4.11
  para o limite visual do controle, separada da borda decorativa de cartão;
* `:hover` em `a`, `button` e `.paginacao__link` (affordance de ponteiro);
* alvo de toque ≥44px em `.topo__nav a` e `.paginacao__link`.

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


def test_alvos_de_toque_do_topo_e_da_paginacao_tem_44px():
    for seletor in (".topo__nav a", ".paginacao__link"):
        regra = _regra(seletor)
        altura = re.search(r"min-height:\s*(\d+)px", regra)

        assert "inline-flex" in regra, f"{seletor} precisa de display inline-flex"
        assert altura is not None, f"{seletor} sem min-height explícito"
        assert int(altura.group(1)) >= ALVO_MINIMO_PX
