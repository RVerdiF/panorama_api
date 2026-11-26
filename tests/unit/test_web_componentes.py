"""Guarda de markup dos componentes de ausência — rodada 3 do reviewer (item 84).

Regras (protótipo `panorama-design`, CSS verbatim):

* `.aviso` é um bloco (`div.aviso` com svg + `p` interno): nenhum template
  pode ter `<p class="aviso">` — o CSS espera o `svg` filho e o `p` sem
  margem própria;
* `.sem-dado` é SÓ marcador curto inline (`<span>` em `td`, ou `<p>` com no
  máximo 3 palavras, ex. "sem dado"): frase longa com essa classe transborda
  (a classe tem `white-space: nowrap`) e deve ser outro componente do
  protótipo (`div.estado-vazio` ou `div.nota-metodo`).

O teste lê os `.html` crus (não o render): falha apontando arquivo e trecho.
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

RE_P_AVISO = re.compile(r'<p\s+class="aviso[\s"]')
RE_P_SEM_DADO = re.compile(
    r'<p\s+class="sem-dado[^"]*"(?:\s[^>]*)?>(.*?)</p>', re.S
)
RE_JINJA = re.compile(r"{{.*?}}|{%.*?%}", re.S)
RE_TAG = re.compile(r"<[^>]+>")
MAX_PALAVRAS_SEM_DADO = 3


def _templates() -> list[Path]:
    return sorted(TEMPLATES.rglob("*.html"))


def _texto_sem_marcacao(trecho: str) -> str:
    sem_jinja = RE_JINJA.sub(" ", trecho)
    sem_tags = RE_TAG.sub(" ", sem_jinja)
    return " ".join(sem_tags.split())


def test_nenhum_template_usa_p_classe_aviso():
    assert _templates(), f"nenhum .html em {TEMPLATES}"
    ocorrencias = []
    for caminho in _templates():
        html = caminho.read_text(encoding="utf-8")
        for match in RE_P_AVISO.finditer(html):
            linha = html.count("\n", 0, match.start()) + 1
            ocorrencias.append(f"{caminho.name}:{linha}")
    assert not ocorrencias, (
        "Todo <p class=\"aviso\"> deve virar <div class=\"aviso\"> com svg + "
        f"<p> interno — encontrado em: {', '.join(ocorrencias)}"
    )


def test_p_sem_dado_tem_no_maximo_3_palavras():
    assert _templates(), f"nenhum .html em {TEMPLATES}"
    ocorrencias = []
    for caminho in _templates():
        html = caminho.read_text(encoding="utf-8")
        for match in RE_P_SEM_DADO.finditer(html):
            texto = _texto_sem_marcacao(match.group(1))
            palavras = len(texto.split())
            if palavras > MAX_PALAVRAS_SEM_DADO:
                linha = html.count("\n", 0, match.start()) + 1
                ocorrencias.append(
                    f"{caminho.name}:{linha} ({palavras} palavras: {texto[:60]!r})"
                )
    assert not ocorrencias, (
        ".sem-dado SÓ como marcador curto (máx. 3 palavras); frase longa "
        "vira div.estado-vazio ou div.nota-metodo — encontrado em: "
        f"{', '.join(ocorrencias)}"
    )
