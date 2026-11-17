"""Endpoints de escola: busca, histórico e indicadores."""

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
from panorama_api.core.errors import bad_request, invalid
from panorama_api.repositories.serving import ServingRepository
from panorama_api.schemas.indicators import IndicatorsResponse
from panorama_api.schemas.schools import HistoryResponse, SchoolsResponse
from panorama_api.services import schools as service

router = APIRouter(tags=["escolas"])

SCHOOLS_PARAMS = frozenset(
    {
        "q",
        "co_entidade",
        "co_municipio",
        "tp_dependencia",
        "apenas_ativas",
        "limit",
        "offset",
    }
)
HISTORY_PARAMS = frozenset({"ano_inicio", "ano_fim"})
INDICATORS_PARAMS = frozenset({"ano"})


@router.get(
    "/schools",
    response_model=SchoolsResponse,
    responses=PROBLEM_RESPONSES,
    summary="Busca escolas em MG",
    dependencies=[Depends(unknown_params_guard(SCHOOLS_PARAMS))],
)
def list_schools(
    q: str | None = Query(None, description="Nome (contém, case-insensitive), 3–100 chars"),
    co_entidade: str | None = Query(None, description="Código INEP (8 dígitos, string)"),
    co_municipio: str | None = Query(None, description="Código IBGE de MG (^31\\d{5}$)"),
    tp_dependencia: str | None = Query(None, description="Código INEP cru (ex. 4 = privada)"),
    apenas_ativas: bool = Query(False, description="Somente situacao_funcionamento = '1'"),
    limit: int | None = Query(None),
    offset: int | None = Query(None),
    repository: ServingRepository = Depends(get_repository),
    settings: Settings = Depends(get_app_settings),
) -> SchoolsResponse:
    """Ao menos um de `q`, `co_entidade` ou `co_municipio` é obrigatório (senão 400)."""
    termo = validation.search_term(q)
    entidade = (
        validation.co_entidade(co_entidade, loc="query")
        if co_entidade is not None
        else None
    )
    municipio = (
        validation.co_municipio(co_municipio, loc="query")
        if co_municipio is not None
        else None
    )
    dependencia = validation.tp_dependencia(tp_dependencia)
    limite = validation.limit(limit, default=20, maximum=100)
    deslocamento = validation.offset(offset)

    if termo is None and entidade is None and municipio is None:
        raise bad_request(
            "informe ao menos um critério de busca: q, co_entidade ou co_municipio",
            loc=("query", "q"),
        )

    return service.search_schools(
        repository,
        settings,
        q=termo,
        co_entidade=entidade,
        co_municipio=municipio,
        tp_dependencia=dependencia,
        apenas_ativas=apenas_ativas,
        limit=limite,
        offset=deslocamento,
    )


@router.get(
    "/schools/{co_entidade}/history",
    response_model=HistoryResponse,
    responses=PROBLEM_RESPONSES,
    summary="Série histórica da escola (mart_escola)",
    dependencies=[Depends(unknown_params_guard(HISTORY_PARAMS))],
)
def school_history(
    co_entidade: str,
    ano_inicio: int | None = Query(None),
    ano_fim: int | None = Query(None),
    repository: ServingRepository = Depends(get_repository),
    settings: Settings = Depends(get_app_settings),
) -> HistoryResponse:
    entidade = validation.co_entidade(co_entidade)
    inicio = validation.ano(ano_inicio)
    fim = validation.ano(ano_fim)
    if inicio is not None and fim is not None and inicio > fim:
        raise invalid("ano_inicio não pode ser maior que ano_fim", loc=("query", "ano_inicio"))

    return service.school_history(
        repository, settings, co_entidade=entidade, ano_inicio=inicio, ano_fim=fim
    )


@router.get(
    "/schools/{co_entidade}/indicators",
    response_model=IndicatorsResponse,
    responses=PROBLEM_RESPONSES,
    summary="Indicadores da escola privada ativa (mart_escola_indicadores)",
    dependencies=[Depends(unknown_params_guard(INDICATORS_PARAMS))],
)
def school_indicators(
    co_entidade: str,
    ano: int | None = Query(None),
    repository: ServingRepository = Depends(get_repository),
    settings: Settings = Depends(get_app_settings),
) -> IndicatorsResponse:
    entidade = validation.co_entidade(co_entidade)
    ano_ref = validation.ano(ano)
    return service.school_indicators(
        repository, settings, co_entidade=entidade, ano=ano_ref
    )
