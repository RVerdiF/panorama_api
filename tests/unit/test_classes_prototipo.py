"""Classes literais de template cobertas pelo CSS do protótipo (plano §3, item 5).

Toda classe literal em `class="…"` nos templates precisa estar em
`classes(panorama.css ∪ panorama-telas.css ∪ landing.css) ∪ PENDENTES[template]`
(V3-D14). `PENDENTES` só encolhe: quando um card de tela migra o template,
a entrada correspondente vai a `∅` no mesmo PR (§4.1).

Depois do card D2-E3 (`t_3f09d837`) sobra **uma** tela escalada ao dono (P7):
`comparar.html`. A landing saiu da lista porque porta a camada visual do
protótipo para `static/landing.css`, carregado só em `/` — por isso esse
arquivo entra na união de classes cobertas e também na varredura de órfão
(como o `app.css`). A trava `test_pendentes_so_as_telas_escaladas` falha se
qualquer outra entrada voltar, e `test_app_only_nao_declara_classe_orfa`
(abaixo) impede que o CSS app-only e o da landing acumulem seletor que nenhum
template, partial, módulo Python ou `static/app.js` usa.

Extração (igual à medição do plano §1.3):

* só atributos literais `class="…"` (ou `'…'`);
* trechos Jinja `{{ … }}` e `{% … %}` são removidos do valor antes de
  partir por espaço — classes condicionais ficam com o teste de 2.3.

Nada aqui toca rede ou dataset: lê arquivos versionados do checkout.
"""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATES = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "panorama_api"
    / "web"
    / "templates"
)
WEB = TEMPLATES.parent
APP_CSS = WEB / "static" / "app.css"
APP_JS = WEB / "static" / "app.js"
#: Stylesheet da landing (D2-E3): camada visual carregada só em `/`. Entra na
#: união de classes cobertas porque é dele que a landing tira as classes do
#: design — e entra na varredura de órfão pelo mesmo motivo que o `app.css`.
LANDING_CSS = WEB / "static" / "landing.css"
PROTOTIPO_CSS = (
    TEMPLATES.parent / "static" / "prototipo" / "panorama.css"
)
PROTOTIPO_TELAS_CSS = (
    TEMPLATES.parent / "static" / "prototipo" / "panorama-telas.css"
)

#: Atributo `class="…"` literal, com aspas duplas ou simples.
CLASSE_ATTR = re.compile(r"""class\s*=\s*([\"'])(.*?)\1""")
#: Trechos Jinja ignorados dentro do valor do atributo.
JINJA_EXPR = re.compile(r"{{.*?}}")
JINJA_BLOCO = re.compile(r"{%.*?%}")
#: Seletor de classe `.nome` nos CSS do protótipo.
SELETOR_CLASSE = re.compile(r"\.[A-Za-z_-][A-Za-z0-9_-]*")

#: Classes que o CSS app-only pode declarar sem virar órfão mesmo quando só
#: aparecem em comentário neste arquivo — hoje nenhuma: o teste de órfão lê
#: template, partial, `app.js` e os módulos de HTML gerado no servidor.
PENDENTES: dict[str, frozenset[str]] = {
    # Shell zerou: sem classe fora do prototipo.
    "base.html": frozenset(),
    # Shell zerou: `topo__*` e `selo-dados*` viraram o DOM do prototipo.
    "partials/topo.html": frozenset(),
    # Shell zerou e apagou o arquivo (virou `p.trilha`): ausente = vazio,
    # mas a chave fica para travar que nada legado volta.
    "partials/breadcrumb.html": frozenset(),
    # Zera no card da busca (ordem 2).
    "busca.html": frozenset(),
    # Zera no card do mercado (ordem 3).
    "mercado.html": frozenset(),
    # Zera no card do mercado (ordem 3).
    "partials/mercado.html": frozenset(),
    # Zera no card do indice de municipios (ordem 4).
    "mercados_indice.html": frozenset(),
    # Zera no card do erro (ordem 5, heranca). D1-E5 zerou: `erro.html` usa so
    # `tela-topo`/`tela-sub`/`painel`/`aviso`/`acoes-filtro`/`rodape-meta` e
    # HTML semantico sem classe no que nao tem componente.
    "erro.html": frozenset(),
    # Zera no card da metodologia (ordem 5, heranca).
    "metodologia.html": frozenset(),
    # D1-E7 zerou o residuo da ficha: `lista-regras` virou `div.nota-metodo` e
    # `nao-se-aplica` virou `div.definicao` (o motivo de `null != 0` segue no
    # texto).
    "escola.html": frozenset(),
    # D1-E7 zerou as macros mortas (`recorte`) e trocou o `nao-se-aplica` por
    # `div.definicao` em `bloco_nao_se_aplica`.
    "partials/macros.html": frozenset(),
    # D2-E3 (t_3f09d837) zerou: a landing porta a camada visual do protótipo e
    # as classes agora vivem em `static/landing.css`. A chave fica para travar
    # que nada legado (`.subtitulo`, `.encontra`, `.recorte`) volta.
    "inicio.html": frozenset(),
    # Por ultimo: comparar so recebe o shell, aguarda referencia do dono.
    "comparar.html": frozenset(
        {
            "campo--acao",
            "dica",
            "formulario",
            "grupo-etapas",
            "lista-definicoes",
            "lista-regras",
            "nota",
            "recorte",
            "serie-figura",
            "subtitulo",
            "tabela-rolavel",
        }
    ),
}

#: As unicas telas que podem ter classe fora do prototipo (P7 aberta).
TELAS_ESCALADAS = frozenset({"comparar.html"})

#: Classes que o protótipo emite no DOM mas não declara em nenhum CSS
#: vendorizado (Regra Zero: o HTML é o do protótipo, literal). Hoje só
#: `sec`: o `render` do índice no design (`assets/js/app.js`,
#: `'<td class="num sec">'`) usa a classe sem regra — ela posiciona nada,
#: só compõe o literal. Válida em qualquer template, sem virar PENDENTES.
CLASSES_DO_DOM_DO_PROTOTIPO = frozenset({"sec"})


def _classes_do_valor(valor: str) -> set[str]:
    """Tokens de classe de um `class="…"` sem os trechos Jinja."""
    sem_jinja = JINJA_BLOCO.sub("", JINJA_EXPR.sub("", valor))
    return set(sem_jinja.split())


def _classes_do_template(caminho: Path) -> set[str]:
    """Classes literais de um template; arquivo ausente = vazio."""
    if not caminho.is_file():
        return set()
    texto = caminho.read_text(encoding="utf-8")
    classes: set[str] = set()
    for aspas, valor in CLASSE_ATTR.findall(texto):
        _ = aspas
        classes.update(_classes_do_valor(valor))
    return classes


def _classes_do_prototipo() -> set[str]:
    """Conjunto de seletores de classe dos CSS do prototipo e da landing."""
    classes: set[str] = set()
    for css in (PROTOTIPO_CSS, PROTOTIPO_TELAS_CSS, LANDING_CSS):
        classes.update(
            sel[1:] for sel in SELETOR_CLASSE.findall(css.read_text(encoding="utf-8"))
        )
    assert classes, "nenhum seletor de classe no CSS do prototipo?"
    return classes


def _relativos_no_disco() -> set[str]:
    return {
        p.relative_to(TEMPLATES).as_posix()
        for p in sorted(TEMPLATES.rglob("*.html"))
    }


def _classes_usadas_no_html_renderizado() -> set[str]:
    """Classes que o app emite mesmo sem `class="…"` no template.

    Duas origens fora do Jinja:

    * `static/app.js` — combobox, tooltip do gráfico e a linha vazia da lista
      são criados/conferidos em JS; classe citada ali conta como uso;
    * os módulos Python que montam markup no servidor: `escola.py` desenha a
      série SVG e `mercado.py` o trilho do share. Lá a classe às vezes sai de
      uma tupla/f-string, não de um `class="…"` isolado, então três formas
      contam como uso:
      1. `class="…"` literal;
      2. valor de um par `classe`/`class` (dict ou kwarg) — é como o subnav
         recebe `subnav__saida`;
      3. string literal cujos tokens tenham `__`/`--`, todas com cara de
         classe CSS — é como `serie__barra serie__barra--b` sai da tupla de
         séries. A regra 3 é conservadora de propósito: só cobre nomes com
         prefixo/sufixo BEM, e um órfão de nome simples (`.rodape`) continua
         sendo apanhado.

    Sem esta varredura o teste de órfão apagaria regra viva.
    """
    usadas: set[str] = set()
    for nome in ("app.js", "landing.js"):
        texto = (WEB / "static" / nome).read_text(encoding="utf-8")
        for aspas, valor in CLASSE_ATTR.findall(texto):
            _ = aspas
            usadas.update(valor.split())
        for valor in re.findall(r"""className\s*=\s*["']([^"']+)["']""", texto):
            usadas.update(valor.split())
        usadas.update(
            re.findall(
                r"""setAttribute\(\s*["']class["']\s*,\s*["']([^"']+)["']""", texto
            )
        )
        # O `landing.js` do design (V5) liga a revelação por
        # `classList.add("js"/"is-in")`: é uso, não órfão.
        usadas.update(
            re.findall(r"""classList\.add\(\s*["']([^"']+)["']\s*\)""", texto)
        )
    for modulo in sorted(WEB.glob("*.py")):
        texto = modulo.read_text(encoding="utf-8")
        for aspas, valor in CLASSE_ATTR.findall(texto):
            _ = aspas
            usadas.update(JINJA_EXPR.sub("", valor).split())
        # (2) par `classe`/`class` com string literal.
        for valor in re.findall(
            r"""["']?class(?:e)?["']?\s*[:=]\s*["']([^"']+)["']""", texto
        ):
            usadas.update(valor.split())
        # (3) literal com cara de lista de classes BEM.
        for valor in re.findall(r"""["']([^"'\n]*)["']""", texto):
            tokens = valor.split()
            if tokens and all(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", t) for t in tokens):
                if any("__" in t or "--" in t for t in tokens):
                    usadas.update(tokens)
    return usadas


def _classes_do_app_css() -> dict[str, set[str]]:
    """Seletores de classe declarados no app-only **e no `landing.css`**.

    O `landing.css` é o quarto stylesheet, carregado só em `/` (D2-E3): os
    seletores dele também precisam de uso, e a checagem é a mesma. Só o seletor
    conta: declaração (`propriedade: valor`) e comentário ficam de fora, então
    `url("{{asset:…}}")` e a prosa das seções não viram "classe declarada".
    """
    declaradas: dict[str, set[str]] = {}
    for arquivo in (APP_CSS, LANDING_CSS):
        texto = arquivo.read_text(encoding="utf-8")
        sem_comentario = re.sub(
            r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), texto, flags=re.S
        )
        for linha in sem_comentario.splitlines():
            limpa = linha.strip()
            if not limpa:
                continue
            if re.match(r"^[a-zA-Z-]+\s*:", limpa):  # declaração
                continue
            for nome in SELETOR_CLASSE.findall(limpa):
                declaradas.setdefault(nome[1:], set()).add(limpa)
    return declaradas


def test_pendentes_so_referencia_templates_conhecidos():
    desconhecidas = set(PENDENTES) - _relativos_no_disco() - {
        "partials/breadcrumb.html"
    }
    assert not desconhecidas, (
        f"PENDENTES com chave sem template correspondente: {sorted(desconhecidas)}"
    )


def test_breadcrumb_ausente_continua_declarado_com_conjunto_vazio():
    """O shell apagou o arquivo; a chave fica para travar o resgate."""
    assert "partials/breadcrumb.html" in PENDENTES
    assert PENDENTES["partials/breadcrumb.html"] == frozenset()
    assert not (TEMPLATES / "partials" / "breadcrumb.html").exists()


def test_pendentes_so_as_duas_telas_escaladas():
    """Trava do P7: só `comparar.html` segue fora do protótipo.

    Qualquer entrada com classe volta a falhar aqui, antes do HTML quebrar
    em tela — é o teste que substitui o grep de "legado = 0".
    """
    com_classe = {rel for rel, classes in PENDENTES.items() if classes}
    assert com_classe == set(TELAS_ESCALADAS), (
        "PENDENTES fora das telas escaladas ao dono (P7): "
        f"{sorted(com_classe - TELAS_ESCALADAS)}"
    )
    assert set(PENDENTES) >= TELAS_ESCALADAS


def test_toda_classe_literal_esta_no_prototipo_ou_em_pendentes():
    prototipo = _classes_do_prototipo()
    novas: dict[str, list[str]] = {}
    obsoletas: dict[str, list[str]] = {}
    for rel in sorted(set(_relativos_no_disco()) | set(PENDENTES)):
        literais = _classes_do_template(TEMPLATES / rel)
        permitidas = (
            prototipo
            | set(PENDENTES.get(rel, frozenset()))
            | CLASSES_DO_DOM_DO_PROTOTIPO
        )
        fora = sorted(literais - permitidas)
        if fora:
            novas[rel] = fora
        # PENDENTES so encolhe: entrada que o template nao usa mais tem
        # que sair (ir a vazio) no mesmo PR. Arquivo ausente nao conta:
        # `breadcrumb.html` foi zerado pelo shell e a chave fica.
        if (TEMPLATES / rel).is_file():
            sobra = sorted(set(PENDENTES.get(rel, frozenset())) - literais)
            if sobra:
                obsoletas[rel] = sobra
    assert not novas, (
        "classes literais fora do prototipo e fora de PENDENTES: "
        + "; ".join(f"{rel}: {','.join(v)}" for rel, v in novas.items())
    )
    assert not obsoletas, (
        "PENDENTES com classe que o template nao usa mais (encolher no PR): "
        + "; ".join(f"{rel}: {','.join(v)}" for rel, v in obsoletas.items())
    )


def test_app_only_nao_declara_classe_orfa():
    """Nenhum seletor do app-only nem do `landing.css` fica sem uso.

    Uso = `class="…"` em template ou partial, classe citada no `app.js`, ou
    markup montado por módulo Python do front. Classe ambígua por construção
    (`<div class="{{ item.classe }}">` do subnav) entra por este último
    caminho, não por exceção no teste.

    D2-E3 (`t_3f09d837`): a varredura cobre também o `landing.css`, o quarto
    stylesheet — sem isso um recorte do design com regra morta passaria.
    """
    usadas = set()
    for html in sorted(TEMPLATES.rglob("*.html")):
        usadas |= _classes_do_template(html)
    usadas |= _classes_usadas_no_html_renderizado()

    orfas = sorted(set(_classes_do_app_css()) - usadas)
    assert not orfas, (
        "seletor do app-only ou da landing sem uso em template, partial, "
        "módulo Python ou app.js: " + ", ".join(f".{nome}" for nome in orfas)
    )
