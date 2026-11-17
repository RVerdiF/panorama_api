"""Aplicação FastAPI da API v1 (read-only) do Panorama Escola."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from panorama_api import __version__
from panorama_api.api.v1 import health
from panorama_api.api.v1.router import router as v1_router
from panorama_api.config import Settings, get_settings
from panorama_api.core.errors import (
    ErrorCode,
    ProblemError,
    UpstreamUnavailable,
    problem_body,
    problem_response,
    validation_errors,
)
from panorama_api.core.startup import validate_schema
from panorama_api.repositories.bigquery_repo import BigQueryServingRepository
from panorama_api.repositories.serving import ServingRepository

logger = logging.getLogger(__name__)

DESCRIPTION = """
API de leitura do Panorama Escola (contrato `serving-marts` / `mvp-1`).

- Escopo geográfico: **MG**.
- NULL nunca vira zero: métricas ausentes saem como `null` junto da flag `is_*_missing`.
- Oferta é tri-estado: `true` (matrícula > 0), `false` (zero declarado), `null` (desconhecido).
- `retencao_liquida_proxy_pct` é proxy de saldo de série — **não** é taxa de evasão.
- Erros seguem RFC 9457 (`application/problem+json`) com campo `code`.
"""


def create_app(
    settings: Settings | None = None, repository: ServingRepository | None = None
) -> FastAPI:
    """Monta o app. `repository` é injetável para testes herméticos (BQ fake)."""
    settings = settings or get_settings()
    repository = repository or BigQueryServingRepository(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # B1: validação de nome+tipo das colunas no startup — falha fechada.
        if settings.validate_schema_on_startup:
            validate_schema(app.state.repo)
        yield

    app = FastAPI(
        title="Panorama Escola API",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.repo = repository

    app.add_exception_handler(ProblemError, _handle_problem)
    app.add_exception_handler(RequestValidationError, _handle_validation)
    app.add_exception_handler(UpstreamUnavailable, _handle_upstream)
    app.add_exception_handler(StarletteHTTPException, _handle_http)
    app.add_exception_handler(Exception, _handle_unexpected)

    app.include_router(health.router)
    app.include_router(v1_router, prefix="/v1")
    return app


def _handle_problem(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProblemError)
    return problem_response(request, exc)


def _handle_validation(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=422,
        media_type="application/problem+json",
        content=problem_body(
            request,
            code=ErrorCode.PARAMETRO_INVALIDO,
            status=422,
            title="Parâmetro inválido",
            detail="requisição inválida",
            errors=validation_errors(exc),
        ),
    )


def _handle_upstream(request: Request, exc: Exception) -> JSONResponse:
    return problem_response(
        request,
        ProblemError(ErrorCode.FONTE_INDISPONIVEL, "fonte de dados indisponível"),
    )


def _handle_http(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    if exc.status_code == 404:
        problem = ProblemError(ErrorCode.NAO_ENCONTRADO, "recurso não encontrado")
    elif exc.status_code in (400, 422):
        problem = ProblemError(
            ErrorCode.PARAMETRO_INVALIDO, str(exc.detail), status=exc.status_code
        )
    else:
        problem = ProblemError(
            ErrorCode.ERRO_INTERNO, str(exc.detail), status=exc.status_code
        )
    return problem_response(request, problem)


def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("erro não tratado em %s", request.url.path)
    return problem_response(
        request,
        ProblemError(ErrorCode.ERRO_INTERNO, "erro interno"),
    )


app = create_app()
