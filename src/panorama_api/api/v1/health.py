"""`GET /health` — liveness, sem consulta analítica (não toca no BigQuery)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from panorama_api import __version__
from panorama_api.contract import CONTRACT, CONTRACT_VERSION_DEFAULT

router = APIRouter()


class Health(BaseModel):
    status: str
    version: str
    contract: str


@router.get(
    "/health",
    response_model=Health,
    tags=["health"],
    summary="Liveness da API (sem BigQuery)",
)
def health() -> Health:
    return Health(
        status="ok",
        version=__version__,
        contract=f"{CONTRACT}/{CONTRACT_VERSION_DEFAULT}",
    )
