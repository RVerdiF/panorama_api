"""Contenção de overflow e barra do ranking (rodada 3 da revisão, `t_cbd54a92`).

Três regressões com prova viva no navegador, travadas aqui em texto:

* as tabelas largas (`table.tabela` tem `min-width: 720px` no bloco herdado)
  esticavam a `.duas-col` — o item de grade tem `min-width: auto` por padrão
  — e a ficha e o mercado rolavam na horizontal (`scrollWidth` 2086 a 1280);
* `.barra-share__preenche` é um `<span>` sem `display` no bloco herdado: como
  inline, o `width` aplicado pelo `app.js` (via CSSOM, pois a CSP barra
  `style=`) não renderizava (`getBoundingClientRect().width` 0);
* o painel "Escolas do mercado por share" do protótipo tem 4 colunas só de
  texto — sem barra (a barra vive no ranking da ficha).
"""

from __future__ import annotations

from pathlib import Path

CSS = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "panorama_api"
    / "web"
    / "static"
    / "app.css"
)

MERCADO_HTML = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "panorama_api"
    / "web"
    / "templates"
    / "mercado.html"
)


def test_filhos_da_duas_col_tem_min_width_zero():
    """O filho da grade não pode esticar a coluna: a rolagem fica dentro de
    `.tabela-rolagem` (`overflow-x: auto` no bloco herdado)."""
    css = CSS.read_text(encoding="utf-8")
    for seletor in (".duas-col > *", ".duas-col--iguais > *", ".painel"):
        assert seletor in css, f"seletor ausente em app.css: {seletor}"
    assert "min-width: 0" in css


def test_preenche_da_barra_e_bloco_para_a_largura_renderizar():
    """Sem `display: block`, o `width` do `app.js` não renderiza no `<span>`."""
    css = CSS.read_text(encoding="utf-8")
    blocos = css.split(".barra-share__preenche {")[1:]
    assert blocos, "regra ausente em app.css: .barra-share__preenche"
    assert any("display: block" in bloco.split("}", 1)[0] for bloco in blocos)


def test_tabela_de_share_do_mercado_e_so_texto_sem_barra():
    """O protótipo não usa barra neste painel: 4 colunas de texto."""
    html = MERCADO_HTML.read_text(encoding="utf-8")
    secao = html.split('id="titulo-escolas"')[-1].split("</section>")[0]
    assert "barra-share" not in secao
    assert "barra_share" not in secao
