"""Endpoints de mercado: recorte municipal e market share."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from panorama_api.api.v1.deps import (
    PROBLEM_RESPONSES,
    get_app_settings,
    get_repository,
    unknown_params_guard,
)
from panorama_api.config import Settings
from panorama_api.core import validation
from panorama_api.repositories.serving import ServingRepository
from panorama_api.schemas.markets import MarketsResponse, ShareResponse
from panorama_api.services import markets as service

router = APIRouter(tags=["mercados"])

MARKET_PARAMS = frozenset({"ano", "etapa"})
SHARE_PARAMS = frozenset({"ano", "etapa", "entidade_tipo", "limit", "offset"})


@router.get(
    "/markets/{co_municipio}",
    response_model=MarketsResponse,
    responses=PROBLEM_RESPONSES,
    summary="Mercado municipal por etapa (mart_mercado + mart_concentracao)",
    dependencies=[Depends(unknown_params_guard(MARKET_PARAMS))],
)
def market(
    co_municipio: str,
    ano: int = Query(description="Ano do censo (obrigatório; sem default)"),
    etapa: str | None = Query(None, description="Etapa; omitida devolve as 9 etapas do ano"),
    repository: ServingRepository = Depends(get_repository),
    settings: Settings = Depends(get_app_settings),
) -> MarketsResponse:
    municipio = validation.co_municipio(co_municipio)
    ano_ref = validation.ano(ano, required=True)
    etapa_ref = validation.etapa(etapa)
    return service.market(
        repository,
        settings,
        co_municipio=municipio,
        ano=ano_ref,
        etapa=etapa_ref,
    )


@router.get(
    "/markets/{co_municipio}/share",
    response_model=ShareResponse,
    responses=PROBLEM_RESPONSES,
    summary="Market share por entidade no município/ano/etapa",
    dependencies=[Depends(unknown_params_guard(SHARE_PARAMS))],
)
def market_share(
    co_municipio: str,
    ano: int = Query(description="Ano do censo (obrigatório)"),
    etapa: str = Query(description="Etapa (obrigatória; inclui `bas`)"),
    entidade_tipo: str | None = Query(None, description="`escola` (default) ou `mantenedora`"),
    limit: int | None = Query(None),
    offset: int | None = Query(None),
    repository: ServingRepository = Depends(get_repository),
    settings: Settings = Depends(get_app_settings),
) -> ShareResponse:
    municipio = validation.co_municipio(co_municipio)
    ano_ref = validation.ano(ano, required=True)
    etapa_ref = validation.etapa(etapa, required=True)
    tipo = validation.entidade_tipo(entidade_tipo)
    limite = validation.limit(limit, default=50, maximum=200)
    deslocamento = validation.offset(offset)

    return service.market_share(
        repository,
        settings,
        co_municipio=municipio,
        ano=ano_ref,
        etapa=etapa_ref,
        entidade_tipo=tipo,
        limit=limite,
        offset=deslocamento,
    )
