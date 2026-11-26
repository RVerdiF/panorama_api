"""Invariantes de acessibilidade dos controles do front (D1-a em diante: união
dos três stylesheets — `static/prototipo/*.css` + `static/app.css` app-only).

Card `t_e9a9df42` (achados C1, C6 e D2 do relatório de UI). O CSS não tem
renderização testável aqui, mas os três invariantes que o card cobra são
numéricos e vivem no arquivo:

* borda de **controle** (input/select) com ≥3:1 sobre `#ffffff` — WCAG 1.4.11
  para o limite visual do controle, separada da borda decorativa de cartão;
* `:hover` em `a` e `button` (affordance de ponteiro);
* alvo de toque ≥44px nos campos e botões do formulário do SSR;
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

#: CSS vendorizado do protótipo (D1-a): fonte dos tokens e das regras de base.
#: Os invariantes visuais valem para a página renderizada, que é a união dos
#: três stylesheets linkados no `base.html` — por isso as leituras abaixo usam
#: o CSS total, não só o app-only.
PROTOTIPO = CSS.parent / "prototipo" / "panorama.css"
PROTOTIPO_TELAS = CSS.parent / "prototipo" / "panorama-telas.css"


def _css_total() -> str:
    """Os três stylesheets na ordem da cascata: protótipo, telas, app-only."""
    return (
        PROTOTIPO.read_text(encoding="utf-8")
        + "\n"
        + PROTOTIPO_TELAS.read_text(encoding="utf-8")
        + "\n"
        + CSS.read_text(encoding="utf-8")
    )


def _tokens() -> dict[str, str]:
    """Valor `#rrggbb` de cada token do `:root` vendorizado."""
    saida: dict[str, str] = {}
    for bloco in re.findall(r":root\s*\{(.*?)\}", PROTOTIPO.read_text(encoding="utf-8"), re.S):
        for nome, valor in re.findall(r"--([A-Za-z0-9-]+):\s*(#[0-9a-fA-F]{6})", bloco):
            saida[nome] = valor
    assert saida, "nenhum token no :root vendorizado?"
    return saida

#: Mínimo de WCAG 1.4.11 (contraste de elemento não textual).
CONTRASTE_MINIMO = 3.0

#: Mínimo de alvo de toque do card (WCAG 2.5.5 é 44x44 CSS px).
ALVO_MINIMO_PX = 44


def _regra(seletor: str) -> str:
    """Declarações da regra cujo seletor é exatamente `seletor`.

    Procura no CSS total (protótipo vendorizado + app-only, na ordem da
    cascata): o invariante vale para a página renderizada.
    """
    css = _css_total()
    achados = re.findall(rf"(?m)^{re.escape(seletor)}\s*\{{([^}}]*)\}}", css)
    assert achados, f"regra ausente no CSS total: {seletor}"
    # Última na cascata vence: é a efetiva no navegador.
    return achados[-1]


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
    # A borda do controle é o token `--muted` (D1-a: zero literal no app-only),
    # distinto do `--border` decorativo do cartão: resolve a var e mede.
    regra = _regra(".campo select")
    achado = re.search(r"border:\s*1px solid\s*var\(--([A-Za-z0-9-]+)\)", regra)
    assert achado is not None, "borda do controle sem token var(--…)"
    cor = _tokens()[achado.group(1)]

    assert _contraste(cor, "#ffffff") >= CONTRASTE_MINIMO


def test_hover_em_link_botao_e_paginacao():
    css = _css_total()
    linhas_com_hover = [linha for linha in css.splitlines() if ":hover" in linha]

    assert len(linhas_com_hover) >= 2
    for seletor in (
        ".menu a:hover",
        ".botao--secundario:hover",
        ".subnav a:hover",
    ):
        assert seletor in css, f":hover ausente para {seletor}"


def test_acao_do_formulario_nao_troca_flex_direction_na_regra_base():
    """O botão de busca estica na largura da célula em `campo--acao`.

    A busca do protótipo não tem mais o link "Limpar filtros" dentro da célula
    de ação (o limpar é um `a.botao` nos chips), então a regra `:has()` que
    virava linha saiu no D1-E7. O que sobra é o invariante: a base não força
    `row`, senão o botão deixa de esticar na coluna.
    """
    base = _regra(".campo--acao")
    assert "flex-direction" not in base, (
        "`.campo--acao` não deve trocar flex-direction na regra base"
    )


def test_alvos_de_toque_do_formulario_tem_44px():
    """O formulário do SSR empilha campos e botão; ambos com alvo ≥44px.

    O `.paginacao__link` do SSR antigo saiu no D1-E7 — a paginação das telas
    migradas é `nav.paginacao > .botao` (`.botao` já tem 46px no protótipo).
    """
    campos = _regra('.campo input[type="search"],\n.campo select')
    for regra, alvo in ((campos, "campos"), (_regra(".formulario button"), "botão")):
        altura = re.search(r"(?:min-)?height:\s*(\d+)px", regra)
        assert altura is not None, f"{alvo} do formulário sem altura explícita"
        assert int(altura.group(1)) >= ALVO_MINIMO_PX


# -- hero da landing e painel do recorte (card t_437796c3) --------------------

#: Fundo do painel do recorte: `--surface-warm` do protótipo. O texto do painel
#: não fica sobre o branco do cartão — o contraste tem de ser medido no painel.
FUNDO_PAINEL = "--surface-warm"

#: WCAG 1.4.3 para texto normal (o card pede 4,5:1, não os 3:1 de elemento).
CONTRASTE_TEXTO_MINIMO = 4.5


def _cor_do_token(nome: str) -> str:
    """Valor `#rrggbb` de um token `--<nome>` do `:root` vendorizado."""
    tokens = _tokens()
    assert nome in tokens, f"token --{nome} ausente no :root vendorizado"
    return tokens[nome]


def test_texto_do_painel_do_recorte_tem_contraste_de_4_5_para_1():
    css = _css_total()
    texto = re.search(r"--fg:\s*(#[0-9a-fA-F]{6})", css)
    assert texto is not None
    fundo = _cor_do_token(FUNDO_PAINEL.lstrip("-"))

    assert _contraste(texto.group(1), fundo) >= CONTRASTE_TEXTO_MINIMO


def test_painel_do_recorte_usa_o_fundo_e_o_raio_da_spec():
    css = _css_total()
    painel = _regra(".hero .recorte")

    # Fundo pelo token, não por hex solto: um só lugar decide a cor do painel.
    assert "background: var(--surface-warm)" in painel
    # 16 px é o raio desta peça do SSR (o protótipo vai até `--radius-lg`).
    assert "border-radius: 16px" in painel


def test_rotulos_e_fonte_do_painel_usam_o_texto_secundario():
    for seletor in (".recorte__rotulo", ".recorte__fonte"):
        assert "var(--muted-strong)" in _regra(seletor), seletor


def test_hero_empilha_antes_de_48rem_e_vira_duas_colunas_depois():
    base = _regra(".hero")
    assert "display: grid" in base
    # Abaixo do breakpoint é uma coluna: nada de `1.1fr 0.9fr` na regra base.
    assert "display: flex" not in base
    assert "1.1fr" not in base

    css = _css_total()
    bloco = re.search(r"@media \(min-width: 48rem\)\s*\{(.*?)\n\}", css, re.S)
    assert bloco is not None, "breakpoint do hero ausente"
    assert ".hero" in bloco.group(1)
    assert "1.1fr 0.9fr" in bloco.group(1)


def test_nenhum_outline_none_sem_indicador_visivel():
    """Todo `outline: none` do protótipo anda com um indicador visível.

    O protótipo zera o `outline` só onde o anel de foco (`--focus-ring`) assume
    no `:focus-visible`; no gráfico da série o foco vai para o retângulo de
    captura (`.grafico__captura`). Remover o contorno sem substituto quebra o
    foco visível — este teste impede a regressão.
    """
    css = _css_total()
    blocos = re.findall(r"([^{}]*)\{([^{}]*)\}", css)
    assert blocos, "nenhum bloco de regra no CSS?"

    for seletor, corpo in blocos:
        if not re.search(r"outline:\s*none\b", corpo):
            continue
        if "grafico" in seletor:
            continue
        assert "var(--focus-ring)" in corpo, (
            f"{seletor.strip()} remove o outline sem o anel de foco"
        )

    # A exceção documentada: o foco do gráfico vive no retângulo de captura.
    assert ".grafico svg:focus-visible .grafico__captura" in css


# -- busca no hero da landing (card t_e075a6f6, spec §6/§8) -------------------

#: Seletor composto dos controles da barra do hero, como está no arquivo.
CAMPOS_DO_HERO = '.hero__campo input[type="search"],\n.hero__campo select'


def _cor_da_variavel(nome: str) -> str:
    tokens = _tokens()
    assert nome in tokens, f"variável --{nome} ausente no :root vendorizado"
    return tokens[nome]


def test_botao_primario_do_hero_tem_branco_sobre_a_cor_de_destaque():
    """"Buscar escolas": o par texto/fundo medido, não herdado."""
    primario = _regra(".botao--primario")

    assert "background: var(--accent)" in primario
    assert "color: var(--accent-on)" in primario
    assert (
        _contraste(_cor_da_variavel("accent"), _cor_da_variavel("accent-on"))
        >= CONTRASTE_TEXTO_MINIMO
    )


def test_botao_secundario_do_hero_e_contorno_com_a_cor_de_acao():
    """`formaction` do mercado: superfície elevada, texto `--fg` e borda token."""
    secundario = _regra(".botao--secundario")
    base = _regra(".botao")

    assert "background: var(--surface-raise)" in secundario
    assert "color: var(--fg)" in secundario
    assert "border: 1px solid transparent" in base
    assert (
        _contraste(_cor_da_variavel("fg"), "#ffffff") >= CONTRASTE_TEXTO_MINIMO
    )


def test_hover_do_botao_secundario_nao_troca_o_texto_de_cor():
    """O `:hover` do secundário mantém o texto `--fg`: nada de azul sobre azul."""
    hover = _regra(".botao--secundario:hover")

    assert "color: var(--fg)" in hover
    # A borda do hover chama o acento, não um azul estranho.
    assert "var(--accent)" in hover


def test_campos_e_botoes_da_busca_do_hero_tem_alvo_de_44px():
    """WCAG 2.5.5 nos dois modos (empilhado e em pílula)."""
    campos = _regra(CAMPOS_DO_HERO)
    botao = _regra(".botao")

    for regra, alvo in ((campos, "campos"), (botao, "botões")):
        altura = re.search(r"min-height:\s*(\d+)px", regra)
        assert altura is not None, f"{alvo} da busca do hero sem min-height"
        assert int(altura.group(1)) >= ALVO_MINIMO_PX

    # Largura: os campos ocupam 100% da coluna e os botões, a do `.hero__acoes`.
    assert "width: 100%" in campos
    assert "grid-template-columns: minmax(0, 1fr)" in _regra(".hero__acoes")


def test_barra_do_hero_empilha_com_raio_16px_e_vira_pilula_em_48rem():
    css = _css_total()
    base = _regra(".hero__busca")

    # Empilhada abaixo de 48rem: uma coluna, raio de 16 px e sombra da peça.
    assert "grid-template-columns: minmax(0, 1fr)" in base
    assert "border-radius: 16px" in base
    assert "box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08)" in base
    # Pílula a partir de 48rem: o raio de 999 px vive dentro do breakpoint.
    pilula = css.index("border-radius: 999px")
    assert css.rindex("@media (min-width: 48rem)", 0, pilula) >= 0
    # O bloco dos botões ocupa a linha inteira da grade da barra.
    assert "grid-column: 1 / -1" in css


def test_foco_visivel_continua_valendo_para_os_botoes():
    """`button:focus-visible` com o contorno do acento, inclusive no hero."""
    css = _css_total()

    assert "button:focus-visible" in css
    assert "outline: 2px solid var(--accent)" in css


# -- escala tipográfica do protótipo (card V1 `t_423aa547`) -------------------

def test_h1_usa_a_escala_do_prototipo():
    """`h1` com `clamp()`; a landing chega ao `--text-3xl` do protótipo.

    O teto é o token da escala (card V1 manda medir o CSS, não o olho). O
    mínimo mantém o título legível a 390 px.
    """
    css = _css_total()
    base = _regra("h1")
    hero = _regra(".hero h1")

    assert "clamp(" in base and "clamp(" in hero
    assert "28px" in base, base
    assert "var(--text-3xl)" in hero, hero

    # A escala existe e é a do protótipo.
    assert re.search(r"--text-3xl:\s*54px", css)
    assert re.search(r"--text-4xl:\s*76px", css)
    assert re.search(r"--leading-tight:\s*1\.08", css)
    assert re.search(r"--tracking-display:\s*-0\.014em", css)


def test_titulos_e_numeros_usam_as_familias_do_prototipo():
    """Serifada nos títulos, Inter no corpo, `tabular-nums` nos números."""
    css = _css_total()
    titulos = _regra("h1")

    assert "var(--font-display)" in titulos

    corpo = _regra("body")
    assert "var(--font-body)" in corpo

    numeros = _regra(".tabela td[data-valor],\n.tabela tbody th[data-valor]")
    assert "tabular-nums" in numeros
    assert "text-align: right" in numeros

    # Coluna numérica declarada no template (sem ordenação) também alinha.
    coluna = _regra("table.tabela .num")
    assert "tabular-nums" in coluna
    assert "text-align: right" in coluna


def test_paleta_de_acao_e_a_do_prototipo():
    """Verde institucional único: `#1e5a4c` em ação **e** link."""
    css = _css_total()

    assert re.search(r"--accent:\s*#1e5a4c", css)
    assert re.search(r"--bg:\s*#e6eae6", css)
    assert re.search(r"--surface:\s*#f8faf7", css)
    # Ação primária e link de navegação herdam o acento; não existe um azul.
    assert "var(--accent)" in _regra(".botao--primario")
    assert "var(--ink-accent)" in _regra(".menu a[aria-current]")
    assert "#1f5f8b" not in css, "o azul da paleta antiga voltou"


def test_raios_e_sombra_do_prototipo_estao_nos_tokens():
    css = _css_total()

    assert re.search(r"--radius-sm:\s*7px", css)
    assert re.search(r"--radius-md:\s*10px", css)
    assert re.search(r"--radius-lg:\s*13px", css)
    assert re.search(r"--radius-pill:\s*9999px", css)
    # Sombra curta e direcional: as duas camadas do `--elev-raised`.
    assert "0 1px 2px rgba(22, 33, 29, 0.07)" in css
    assert "0 10px 22px -14px rgba(22, 33, 29, 0.30)" in css


def test_movimento_respeita_prefers_reduced_motion():
    css = _css_total()

    assert "@media (prefers-reduced-motion: reduce)" in css
    bloco = css[css.index("@media (prefers-reduced-motion: reduce)") :]
    assert "transition-duration" in bloco


def test_foco_visivel_usa_o_anel_do_prototipo():
    css = _css_total()

    assert re.search(r"--focus-ring:\s*0 0 0 3px rgba\(30, 90, 76, 0\.30\)", css)


# -- navbar do protótipo (V3-S0): link do menu com alvo de toque -------------


def test_menu_do_topo_declara_alvo_de_toque():
    """A navbar é `.menu` do protótipo (V3-S0); o `<details>` do NAV-1 saiu.

    O alvo é 40px no vendorizado — acima do mínimo AA da WCAG 2.5.8 (24px),
    abaixo dos 44px que o card antigo pedia para o `.topo__nav a` do SSR
    (seletor que o shell apagou). A divergência para 44px é decisão de design
    do protótipo, registrada no handoff do D1-E7; o que este teste trava é o
    link do menu continuar declarando altura própria.
    """
    regra = _regra(".menu a")
    altura = re.search(r"min-height:\s*(\d+)px", regra)

    assert "inline-flex" in regra, "`.menu a` precisa de display inline-flex"
    assert altura is not None, "`.menu a` sem min-height explícito"
    assert int(altura.group(1)) >= 24, "alvo de toque abaixo do mínimo AA (24px)"


# -- destaque da linha alvo do ranking (card t_e120b83b) ---------------------

#: Fundo do destaque da linha alvo (`:target`) — `--surface-warm` do protótipo.
#: Como no painel do recorte, o hex é decisão do design; o contrato que este
#: teste protege é o par token × contraste × marca não cromática.
FUNDO_ALVO = "--surface-warm"


def test_destaque_da_linha_alvo_nao_depende_de_js_nem_de_cor():
    """`:target` em CSS puro: fundo + marca de espessura, não só cor (WCAG 1.4.1).

    O destaque tem de sobreviver a quem não distingue a cor do fundo: por isso
    a primeira célula ganha uma marca não cromática (espessura de 4px). E a
    linha não pode parar sob o topo de uma página rolada — `scroll-margin-top`.
    """
    alvo = _regra(".tabela tbody tr:target")
    marca = _regra(".tabela tbody tr:target > *:first-child")

    fundo = re.search(r"background:\s*var\(--surface-warm\)", alvo)
    assert fundo is not None, "linha alvo sem o fundo do token --surface-warm"
    margem = re.search(r"scroll-margin-top:\s*([\d.]+)rem", alvo)
    assert margem is not None, "linha alvo sem scroll-margin-top"
    assert float(margem.group(1)) >= 4

    # Espessura explícita: a marca existe em escala de cinza, não é só cor.
    espessura = re.search(r"(?:box-shadow|border-left)[^;]*?(\d+)px", marca)
    assert espessura is not None, "marca do alvo sem espessura (box-shadow/border-left)"
    assert int(espessura.group(1)) >= 4

    destaque = _cor_da_variavel("fg")
    assert _contraste(destaque, "#ffffff") >= CONTRASTE_MINIMO
    assert _contraste(destaque, _cor_do_token(FUNDO_ALVO.lstrip("-"))) >= CONTRASTE_MINIMO
