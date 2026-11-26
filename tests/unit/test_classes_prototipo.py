"""Classes literais de template cobertas pelo CSS do protótipo (plano §3, item 5).

Toda classe literal em `class="…"` nos templates precisa estar em
`classes(panorama.css ∪ panorama-telas.css) ∪ PENDENTES[template]`
(V3-D14). `PENDENTES` só encolhe: quando um card de tela migra o template,
a entrada correspondente vai a `∅` no mesmo PR (§4.1).

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
PROTOTIPO_CSS = (
    TEMPLATES.parent / "static" / "prototipo" / "panorama.css"
)
PROTOTIPO_TELAS_CSS = (
    TEMPLATES.parent / "static" / "prototipo" / "panorama-telas.css"
)

#: Atributo `class="…"` literal, com aspas duplas ou simples.
CLASSE_ATTR = re.compile(r"""class\s*=\s*(["'])(.*?)\1""")
#: Trechos Jinja ignorados dentro do valor do atributo.
JINJA_EXPR = re.compile(r"{{.*?}}")
JINJA_BLOCO = re.compile(r"{%.*?%}")
#: Seletor de classe `.nome` nos CSS do protótipo.
SELETOR_CLASSE = re.compile(r"\.[A-Za-z_-][A-Za-z0-9_-]*")

#: Residuo medido APOS o card do shell: `base.html`, `partials/topo.html`
#: e `partials/breadcrumb.html` zerados; demais entradas sao as classes
#: legadas restantes no estado atual dos arquivos. Cada entrada diz qual
#: card futuro zera.
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
    # Zera no card do erro (ordem 5, heranca).
    "erro.html": frozenset(
        {
            "aviso--temporario",
            "codigo-erro",
            "lista-regras",
            "paginacao__link",
            "painel--erro",
            "rodape-erro",
            "subtitulo",
        }
    ),
    # Zera no card da metodologia (ordem 5, heranca).
    "metodologia.html": frozenset(
        {"lista-definicoes", "lista-regras", "subtitulo"}
    ),
    # Zera no card da ficha (ordem 6, residuo).
    "escola.html": frozenset({"lista-regras", "nao-se-aplica"}),
    # Zera no card da limpeza (ordem 7).
    "partials/macros.html": frozenset(
        {"lista-definicoes", "lista-regras", "nao-se-aplica", "recorte"}
    ),
    # Por ultimo: landing so recebe o shell, aguarda referencia do dono (P7).
    "inicio.html": frozenset(
        {
            "dica",
            "encontra",
            "hero",
            "hero__acoes",
            "hero__busca",
            "hero__campo",
            "hero__texto",
            "recorte",
            "recorte__fonte",
            "recorte__item",
            "recorte__lista",
            "recorte__rotulo",
            "recorte__valor",
            "secao",
            "subtitulo",
        }
    ),
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
    """Conjunto de seletores de classe dos dois CSS do prototipo."""
    classes: set[str] = set()
    for css in (PROTOTIPO_CSS, PROTOTIPO_TELAS_CSS):
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


def test_toda_classe_literal_esta_no_prototipo_ou_em_pendentes():
    prototipo = _classes_do_prototipo()
    novas: dict[str, list[str]] = {}
    obsoletas: dict[str, list[str]] = {}
    for rel in sorted(set(_relativos_no_disco()) | set(PENDENTES)):
        literais = _classes_do_template(TEMPLATES / rel)
        permitidas = prototipo | set(PENDENTES.get(rel, frozenset()))
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
