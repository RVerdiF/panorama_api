"""Contrato de tokens do front — fundação D1-E0 (card `t_686b363e`, plano §3).

Fonte única: os tokens são as custom properties do `:root` de
`static/prototipo/panorama.css`. O que este teste trava:

* os dois arquivos vendorizados são byte a byte os do design — o `sha256`
  esperado está fixo aqui, então mudar o design passa a ser um commit
  explícito de sincronização, nunca uma edição local;
* zero literal de cor fora do `:root`: em `static/app.css` (app-only) e nos
  templates, nada de `#[0-9a-f]{3,8}`, `rgb(`, `hsl(` ou `oklch(` — só
  `var(--…)` e `color-mix()` sobre `var`. Zero `style=` em template;
* toda `var(--x)` usada em `app.css` e nos templates existe no `:root`
  vendorizado — citar token inexistente quebra aqui, não no navegador.

Nada aqui toca rede ou dataset: os hashes são constantes e os arquivos são
lidos do checkout.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

STATIC = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "panorama_api"
    / "web"
    / "static"
)
TEMPLATES = STATIC.parent / "templates"

PROTOTIPO = STATIC / "prototipo" / "panorama.css"
PROTOTIPO_TELAS = STATIC / "prototipo" / "panorama-telas.css"
APP_CSS = STATIC / "app.css"

#: `sha256` dos arquivos do design (`panorama-design/assets/css/`) no commit
#: da sincronização. Trocar o design = trocar estas constantes + os arquivos,
#: num commit só de sincronização.
SHA_PROTOTIPO = "63aedfc25270cd581213d46bb7c4cd86ee459b6ca49c656a74a73918f441ea2f"
SHA_PROTOTIPO_TELAS = (
    "d281970bb02741a06e5336379b4e13e3da1528b7812e2f52f671f043d1c46605"
)

#: Literal de cor proibido fora do `:root` (plano §3, item 3).
COR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(|oklch\(")
#: Blocos `:root { … }` — inclusive o de derivados e o do breakpoint.
BLOCO_ROOT = re.compile(r":root\s*\{(.*?)\}", re.S)
#: Definição `--nome:` dentro do `:root`.
TOKEN_DEFINIDO = re.compile(r"--([A-Za-z0-9-]+)\s*:")
#: Uso `var(--nome)`.
TOKEN_USADO = re.compile(r"var\(--([A-Za-z0-9-]+)\)")


def _sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def _tokens_do_root(css: str) -> set[str]:
    definidos: set[str] = set()
    for bloco in BLOCO_ROOT.findall(css):
        definidos.update(TOKEN_DEFINIDO.findall(bloco))
    assert definidos, "nenhum token no :root vendorizado?"
    return definidos


def _fora_do_root(css: str) -> str:
    """O CSS sem os blocos `:root` — onde literal de cor é proibido."""
    return BLOCO_ROOT.sub("", css)


# -- byte a byte com o design (plano §3, item 2) ------------------------------


def test_prototipo_panorama_css_e_byte_a_byte_com_o_design():
    assert _sha256(PROTOTIPO) == SHA_PROTOTIPO


def test_prototipo_telas_css_e_byte_a_byte_com_o_design():
    assert _sha256(PROTOTIPO_TELAS) == SHA_PROTOTIPO_TELAS


# -- sem literal de cor fora do `:root` (plano §3, item 3) --------------------


def test_app_css_app_only_nao_tem_literal_de_cor():
    resto = _fora_do_root(APP_CSS.read_text(encoding="utf-8"))
    achado = COR_LITERAL.search(resto)
    assert achado is None, f"literal de cor no app-only: {achado.group(0)!r}"


def test_templates_nao_tem_literal_de_cor_nem_style_inline():
    for caminho in sorted(TEMPLATES.rglob("*.html")):
        texto = caminho.read_text(encoding="utf-8")
        achado = COR_LITERAL.search(texto)
        assert achado is None, f"{caminho.name}: literal {achado.group(0)!r}"
        assert "style=" not in texto, f"{caminho.name}: style= inline"


# -- var referenciada existe (plano §3, item 4) --------------------------------


def test_toda_var_usada_existe_no_root_vendorizado():
    tokens = _tokens_do_root(PROTOTIPO.read_text(encoding="utf-8"))
    telas = PROTOTIPO_TELAS.read_text(encoding="utf-8")
    assert BLOCO_ROOT.search(telas) is None, "panorama-telas.css não define :root"

    usados: set[str] = set(TOKEN_USADO.findall(APP_CSS.read_text(encoding="utf-8")))
    for caminho in sorted(TEMPLATES.rglob("*.html")):
        usados.update(TOKEN_USADO.findall(caminho.read_text(encoding="utf-8")))

    assert usados, "nenhuma var(--…) em uso?"
    desconhecidos = sorted(usados - tokens)
    assert desconhecidos == [], f"tokens sem definição no :root: {desconhecidos}"
