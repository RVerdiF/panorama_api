"""Conversão de linha do mart para o schema de resposta (NULL ≠ 0)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from panorama_api.contract import OFERTA_ETAPAS
from panorama_api.schemas.schools import Oferta


def tri_state(value: Any) -> bool | None:
    """Oferta tri-estado: `1` → true, `0` → false, NULL → null (desconhecido)."""
    if value is None:
        return None
    return bool(value)


def oferta(row: Mapping[str, Any]) -> Oferta:
    return Oferta(**{etapa: tri_state(row.get(f"of_{etapa}")) for etapa in OFERTA_ETAPAS})


def flags_abaixo_porte(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    if any(row.get("is_abaixo_porte") for row in rows):
        return ["IS_ABAIXO_PORTE"]
    return []
