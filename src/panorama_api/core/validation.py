"""Validação de entrada (422 antes de consultar o BigQuery).

Nenhum valor vindo do cliente chega ao SQL sem passar por aqui.
"""

from __future__ import annotations

import re
from typing import Any, Literal, overload

from panorama_api.contract import ENTIDADES_TIPO, ETAPAS, EntidadeTipo, Etapa
from panorama_api.core.errors import bad_request, invalid

CO_ENTIDADE_RE = re.compile(r"^\d{8}$")
CO_MUNICIPIO_RE = re.compile(r"^31\d{5}$")

ANO_MIN = 2000
ANO_MAX = 2100

MAX_OFFSET = 1000


def co_entidade(value: str, *, loc: str = "path") -> str:
    value = (value or "").strip()
    if not CO_ENTIDADE_RE.match(value):
        raise invalid(
            "co_entidade deve ter 8 dígitos (código INEP como string)",
            loc=(loc, "co_entidade"),
        )
    return value


def co_municipio(value: str, *, loc: str = "path") -> str:
    value = (value or "").strip()
    if not CO_MUNICIPIO_RE.match(value):
        raise invalid(
            "co_municipio deve ter 7 dígitos e pertencer a MG (prefixo 31)",
            loc=(loc, "co_municipio"),
        )
    return value


@overload
def etapa(value: str | None, *, required: Literal[True]) -> Etapa: ...


@overload
def etapa(value: str | None, *, required: Literal[False] = False) -> Etapa | None: ...


def etapa(value: str | None, *, required: bool = False) -> Etapa | None:
    if value is None:
        if required:
            raise invalid("etapa é obrigatória", loc=("query", "etapa"))
        return None
    if value not in ETAPAS:
        raise invalid(
            f"etapa {value!r} não pertence a {{{','.join(ETAPAS)}}}",
            loc=("query", "etapa"),
        )
    return value  # type: ignore[return-value]


def entidade_tipo(value: str | None) -> EntidadeTipo:
    if value is None:
        return "escola"
    if value not in ENTIDADES_TIPO:
        raise invalid(
            f"entidade_tipo {value!r} não pertence a {{{','.join(ENTIDADES_TIPO)}}}",
            loc=("query", "entidade_tipo"),
        )
    return value  # type: ignore[return-value]


@overload
def ano(value: int | None, *, required: Literal[True], loc: str = "query") -> int: ...


@overload
def ano(value: int | None, *, required: Literal[False] = False, loc: str = "query") -> int | None: ...


def ano(value: int | None, *, required: bool = False, loc: str = "query") -> int | None:
    if value is None:
        if required:
            raise invalid("ano é obrigatório", loc=(loc, "ano"))
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise invalid("ano deve ser inteiro", loc=(loc, "ano"))
    if not ANO_MIN <= value <= ANO_MAX:
        raise invalid(
            f"ano deve estar entre {ANO_MIN} e {ANO_MAX}", loc=(loc, "ano")
        )
    return value


def limit(value: int | None, *, default: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("limit deve ser inteiro", loc=("query", "limit"))
    if value < 1 or value > maximum:
        raise invalid(
            f"limit deve estar entre 1 e {maximum}", loc=("query", "limit")
        )
    return value


def offset(value: int | None) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("offset deve ser inteiro", loc=("query", "offset"))
    if value < 0 or value > MAX_OFFSET:
        raise invalid(
            f"offset deve estar entre 0 e {MAX_OFFSET}", loc=("query", "offset")
        )
    return value


def search_term(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not 3 <= len(value) <= 100:
        raise invalid(
            "q deve ter entre 3 e 100 caracteres", loc=("query", "q")
        )
    return value


def tp_dependencia(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value.isdigit() or len(value) > 2:
        raise invalid(
            "tp_dependencia deve ser o código INEP (dígitos, ex. 4 = privada)",
            loc=("query", "tp_dependencia"),
        )
    return value


def reject_unknown_params(params: dict[str, Any], allowed: frozenset[str]) -> None:
    """400 quando o cliente manda parâmetro fora da allowlist (`order`, `fields`...)."""
    unknown = sorted(set(params) - set(allowed))
    if unknown:
        raise bad_request(
            "parâmetros desconhecidos: " + ", ".join(unknown),
            loc=("query", unknown[0]),
        )
