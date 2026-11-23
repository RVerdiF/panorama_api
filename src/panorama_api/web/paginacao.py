"""Paginação de telas do front: `has_more`, sem `total` (plano §5).

O contrato de serving não devolve `total` (um `COUNT(*)` seria scan extra no
BigQuery). A tela por isso nunca escreve "de N resultados": mostra a posição da
página ("Mostrando 1–20") e decide os links **apenas** por `page.has_more`.

Teto de paginação: `offset ≤ 1000` (`core.validation.MAX_OFFSET`). Quando a
próxima página passaria do teto, "Próxima" desaparece e a tela pede refinamento
da busca — em vez de oferecer um link que o contrato recusaria com 422.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlencode

from panorama_api.core.validation import MAX_OFFSET
from panorama_api.schemas.common import Page

#: Separador do intervalo "Mostrando N–M" (travessão, não hífen).
SEPARADOR_INTERVALO = "–"


@dataclass(frozen=True, slots=True)
class Paginacao:
    """Estado de navegação de uma página de lista, pronto para o template."""

    #: "1–20" (posições, não totais); `None` quando a página voltou vazia.
    mostrando: str | None
    #: Link "Anterior"; `None` na primeira página.
    url_anterior: str | None
    #: Link "Próxima"; `None` sem `has_more` **ou** quando o próximo offset
    #: passaria do teto `MAX_OFFSET`.
    url_proxima: str | None
    #: Há mais linhas, mas o próximo offset excede o teto: peça busca refinada.
    refinar: bool


def montar(
    page: Page,
    *,
    caminho: str,
    filtros: Mapping[str, str] | None = None,
) -> Paginacao:
    """Monta o estado de navegação a partir do `Page` do contrato."""
    filtros = filtros or {}
    proximo_offset = page.offset + page.limit
    proxima_permitida = page.has_more and proximo_offset <= MAX_OFFSET

    return Paginacao(
        mostrando=(
            f"{page.offset + 1}{SEPARADOR_INTERVALO}{page.offset + page.returned}"
            if page.returned
            else None
        ),
        url_anterior=(
            _url(caminho, filtros, offset=max(0, page.offset - page.limit))
            if page.offset > 0
            else None
        ),
        url_proxima=(
            _url(caminho, filtros, offset=proximo_offset) if proxima_permitida else None
        ),
        refinar=page.has_more and not proxima_permitida,
    )


def _url(caminho: str, filtros: Mapping[str, str], *, offset: int) -> str:
    parametros = {chave: valor for chave, valor in filtros.items() if valor}
    if offset:
        parametros["offset"] = str(offset)
    consulta = urlencode(parametros)
    return f"{caminho}?{consulta}" if consulta else caminho


__all__ = ["MAX_OFFSET", "Paginacao", "SEPARADOR_INTERVALO", "montar"]
