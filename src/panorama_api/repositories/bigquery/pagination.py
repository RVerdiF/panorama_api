"""Paginação por keyset (cursor opaco) e por offset, sem ``COUNT(*)``.

Contrato de custo (card ``t_ea2c4d84`` / decisão de 2026-11-17):
``LIMIT page_size + 1`` revela ``has_more`` sem varrer a tabela uma segunda
vez; ``COUNT(*)``/``total`` são proibidos.

O cursor é opaco para o cliente: base64url de um JSON com os valores da última
linha devolvida, na ordem declarada pelo template. Qualquer cursor inválido
vira 400 antes de tocar no BigQuery.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from .errors import InvalidQueryRequest
from .parameters import ParamType


class PaginationMode(str, Enum):
    NONE = "none"
    OFFSET = "offset"
    KEYSET = "keyset"


@dataclass(frozen=True, slots=True)
class KeysetColumn:
    """Coluna de ordenação usada como chave de paginação."""

    name: str
    type: ParamType = ParamType.STRING
    nullable: bool = False


@dataclass(frozen=True, slots=True)
class PageRequest:
    """Pedido de página; valores crus, normalizados em ``plan_page``."""

    page_size: int | None = None
    offset: int | None = None
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class PageInfo:
    """Bloco ``page`` da resposta (sem ``total``, por decisão de custo)."""

    limit: int
    offset: int
    returned: int
    has_more: bool
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class PagePlan:
    """Sufixo SQL + parâmetros derivados da paginação escolhida."""

    mode: PaginationMode
    parameters: tuple[tuple[str, ParamType, Any], ...] = ()
    keyset_predicate: str | None = None
    order_by: str | None = None
    limit_sql: str | None = None
    page_size: int = 0
    offset: int = 0
    keyset_columns: tuple[KeysetColumn, ...] = ()
    keyset_values: tuple[Any, ...] | None = None


def encode_cursor(values: Sequence[Any]) -> str:
    payload = json.dumps(list(values), separators=(",", ":"), ensure_ascii=False)
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str, columns: Sequence[KeysetColumn]) -> tuple[Any, ...]:
    """Decodifica o cursor e valida aridade e tipo de cada componente."""
    text = (cursor or "").strip()
    if not text:
        raise InvalidQueryRequest("cursor vazio", field="cursor")
    padded = text + "=" * (-len(text) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        values = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidQueryRequest("cursor inválido", field="cursor") from exc
    if not isinstance(values, list) or len(values) != len(columns):
        raise InvalidQueryRequest("cursor não corresponde à ordenação", field="cursor")
    normalized: list[Any] = []
    for column, value in zip(columns, values):
        if value is None:
            if not column.nullable:
                raise InvalidQueryRequest("cursor inválido para a coluna", field="cursor")
            normalized.append(None)
            continue
        if column.type is ParamType.INT64:
            if isinstance(value, bool) or not isinstance(value, int):
                raise InvalidQueryRequest("cursor inválido para a coluna", field="cursor")
        elif not isinstance(value, str):
            raise InvalidQueryRequest("cursor inválido para a coluna", field="cursor")
        normalized.append(value)
    return tuple(normalized)


def plan_page(
    *,
    mode: PaginationMode,
    request: PageRequest,
    page_size_default: int,
    page_size_max: int,
    offset_max: int,
    row_cap: int,
    keyset_columns: Sequence[KeysetColumn] = (),
) -> PagePlan:
    """Normaliza a página pedida e produz sufixo SQL + parâmetros."""
    if mode is PaginationMode.NONE:
        if request.cursor:
            raise InvalidQueryRequest("este recurso não aceita cursor", field="cursor")
        if request.offset not in (None, 0):
            raise InvalidQueryRequest("este recurso não é paginado", field="offset")
        return PagePlan(
            mode=mode,
            parameters=(("row_cap", ParamType.INT64, row_cap),),
            limit_sql="LIMIT @row_cap",
        )

    size = _page_size(request.page_size, page_size_default, page_size_max)

    if mode is PaginationMode.OFFSET:
        if request.cursor:
            raise InvalidQueryRequest("este recurso usa offset, não cursor", field="cursor")
        offset = 0 if request.offset in (None, "") else _as_int(request.offset, "offset")
        if offset < 0:
            raise InvalidQueryRequest("offset não pode ser negativo", field="offset")
        if offset > offset_max:
            raise InvalidQueryRequest(
                f"offset máximo é {offset_max}", field="offset"
            )
        return PagePlan(
            mode=mode,
            parameters=(
                ("page_limit", ParamType.INT64, size + 1),
                ("page_offset", ParamType.INT64, offset),
            ),
            order_by=None,
            limit_sql="LIMIT @page_limit OFFSET @page_offset",
            page_size=size,
            offset=offset,
        )

    # KEYSET
    if request.offset not in (None, 0):
        raise InvalidQueryRequest("este recurso usa cursor, não offset", field="offset")
    if not keyset_columns:
        raise InvalidQueryRequest("recurso sem chave de paginação", field="cursor")

    parameters: list[tuple[str, ParamType, Any]] = [("page_limit", ParamType.INT64, size + 1)]
    predicate: str | None = None
    values: tuple[Any, ...] | None = None
    if request.cursor:
        values = decode_cursor(request.cursor, keyset_columns)
        predicate = _keyset_predicate(keyset_columns)
        for index, (column, value) in enumerate(zip(keyset_columns, values)):
            parameters.append((f"cursor_{index}", column.type, value))

    # A ordenação é derivada das colunas do cursor para não divergir do predicado.
    order_by = ", ".join(
        f"{column.name} ASC" + (" NULLS LAST" if column.nullable else "")
        for column in keyset_columns
    )
    return PagePlan(
        mode=mode,
        parameters=tuple(parameters),
        keyset_predicate=predicate,
        order_by=order_by,
        limit_sql="LIMIT @page_limit",
        page_size=size,
        keyset_columns=tuple(keyset_columns),
        keyset_values=values,
    )


def _page_size(requested: Any, default: int, maximum: int) -> int:
    if requested in (None, ""):
        return min(default, maximum)
    size = _as_int(requested, "page_size")
    if size <= 0:
        raise InvalidQueryRequest("page_size deve ser positivo", field="page_size")
    if size > maximum:
        raise InvalidQueryRequest(f"page_size máximo é {maximum}", field="page_size")
    return size


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise InvalidQueryRequest(f"{field} deve ser inteiro", field=field)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise InvalidQueryRequest(f"{field} deve ser inteiro", field=field)


def _keyset_predicate(columns: Sequence[KeysetColumn]) -> str:
    """Predicado "depois do cursor" para ordenação ASC com NULLs por último.

    Para cada coluna ``k``: igualdade em todas as anteriores e "maior" em ``k``.
    "Maior" inclui ``NULL`` quando o cursor é não nulo, porque em ``NULLS LAST``
    ``NULL`` é o maior valor da ordenação.
    """
    terms: list[str] = []
    for index, column in enumerate(columns):
        prefix = [f"({_equals(prev, pos)})" for pos, prev in enumerate(columns[:index])]
        prefix.append(_greater(column, index))
        terms.append("(" + " AND ".join(prefix) + ")")
    return "(" + " OR ".join(terms) + ")"


def _equals(column: KeysetColumn, index: int) -> str:
    if column.nullable:
        return f"{column.name} = @cursor_{index} OR ({column.name} IS NULL AND @cursor_{index} IS NULL)"
    return f"{column.name} = @cursor_{index}"


def _greater(column: KeysetColumn, index: int) -> str:
    if column.nullable:
        return f"{column.name} > @cursor_{index} OR ({column.name} IS NULL AND @cursor_{index} IS NOT NULL)"
    return f"{column.name} > @cursor_{index}"


def split_page(
    *,
    mode: PaginationMode,
    plan: PagePlan,
    rows: Iterable[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], PageInfo | None]:
    """Aplica ``LIMIT + 1`` e deriva ``has_more``/``next_cursor``."""
    materialized = list(rows)
    if mode is PaginationMode.NONE:
        return materialized, None

    has_more = len(materialized) > plan.page_size
    items = materialized[: plan.page_size]
    next_cursor: str | None = None
    if has_more and plan.keyset_columns and items:
        last = items[-1]
        next_cursor = encode_cursor([last[column.name] for column in plan.keyset_columns])
    return items, PageInfo(
        limit=plan.page_size,
        offset=plan.offset,
        returned=len(items),
        has_more=has_more,
        next_cursor=next_cursor,
    )
