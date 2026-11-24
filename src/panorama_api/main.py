"""Aplicação FastAPI da API v1 (read-only) do Panorama Escola."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
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
from panorama_api.core.http_cache import (
    CACHE_CONTROL_PAGINA,
    HttpCacheMiddleware,
)
from panorama_api.core.logging_config import configure_logging
from panorama_api.core.startup import validate_schema
from panorama_api.repositories.bigquery_repo import BigQueryServingRepository
from panorama_api.repositories.serving import ServingRepository
from panorama_api.web import PREFIXO_WEB, e_caminho_web
from panorama_api.web.middleware import WebGZipMiddleware
from panorama_api.web.observability import PageViewMiddleware
from panorama_api.web.routes import RETRY_AFTER_SEGUNDOS, pagina_erro, pagina_inexistente
from panorama_api.web.routes import router as web_router
from panorama_api.web.routes import router_inicio

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
    # Log estruturado (JSON no stdout) em INFO: `bq_ms` e `cache` são campos
    # consumidos pelos alertas de custo. Idempotente.
    configure_logging()
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
    # Cache HTTP das respostas GET /v1/*: ETag por DATA_VERSION + APP_BUILD +
    # params, `Cache-Control` de 1 dia e LRU em memória (card t_817a670c; APP_BUILD
    # na chave desde F9/D7 — mudança de código que altera a representação também
    # precisa invalidar o corpo servido).
    app.add_middleware(HttpCacheMiddleware)
    # Cache das páginas SSR `/` e `/app` (cards t_68bd7615 e t_386b791c): mesma
    # mecânica e mesma chave, com `private, no-cache`, para que a revalidação do
    # navegador seja respondida por 304 sem executar o handler (logo sem tocar no
    # repositório/BigQuery). `e_caminho_web` é o mesmo predicado do erro HTML, do
    # gzip e do `page_view`: inclui a raiz `/` da landing e `/app` com segmentos.
    # Assets ficam de fora: são imutáveis por nome com hash e mantêm o próprio
    # `Cache-Control`.
    app.add_middleware(
        HttpCacheMiddleware,
        cache_control=CACHE_CONTROL_PAGINA,
        prefix=PREFIXO_WEB,
        pagina=True,
        exclude_prefix=f"{PREFIXO_WEB}/static/",
        match_root=True,
        predicado=e_caminho_web,
    )
    # gzip do HTML/CSS do front e das páginas de erro (egress, plano §3).
    # Restrito às páginas do front (`/` e `/app`): `/v1` é contrato público e não
    # pode ganhar headers novos. Fica fora da camada do cache: o LRU guarda o
    # corpo cru e cada requisição negocia a compressão pelo `Accept-Encoding`.
    app.add_middleware(WebGZipMiddleware, minimum_size=500)
    # Linha `page_view` por requisição de página do front (card F6, plano §7).
    # Fica por fora do cache de páginas para ler a decisão `hit`/`miss` que ele
    # publica em `request.scope` — e por fora do gzip, para medir a requisição
    # como um todo. Assets `/app/static/*` são ignorados: não são páginas.
    app.add_middleware(PageViewMiddleware)

    app.add_exception_handler(ProblemError, _handle_problem)
    app.add_exception_handler(RequestValidationError, _handle_validation)
    app.add_exception_handler(UpstreamUnavailable, _handle_upstream)
    app.add_exception_handler(StarletteHTTPException, _handle_http)
    app.add_exception_handler(Exception, _handle_unexpected)

    app.include_router(health.router)
    app.include_router(v1_router, prefix="/v1")
    # Front SSR sob `/app` (decisão D1 = A). Mesmo processo/serviço da API.
    app.include_router(web_router)
    # Entrada do sistema (cards t_0c84b91f e t_386b791c): `/` é a página de
    # entrada (landing) em HTML, sem prefixo de router — `/app/` continua sendo a
    # busca. GET e HEAD respondem 200; `include_in_schema=False` mantém o
    # contrato do `/v1`/OpenAPI como estava. Zero consultas ao repositório.
    app.include_router(router_inicio)

    return app


def _handle_problem(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, ProblemError)
    if _is_web(request):
        return pagina_erro(
            request,
            exc,
            retry_after=(
                RETRY_AFTER_SEGUNDOS
                if exc.status == 503
                else None
            ),
        )
    return problem_response(request, exc)


def _handle_validation(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RequestValidationError)
    erros = validation_errors(exc)
    if _is_web(request):
        return pagina_erro(
            request,
            ProblemError(
                ErrorCode.PARAMETRO_INVALIDO,
                "requisição inválida",
                errors=erros,
            ),
        )
    return JSONResponse(
        status_code=422,
        media_type="application/problem+json",
        content=problem_body(
            request,
            code=ErrorCode.PARAMETRO_INVALIDO,
            status=422,
            title="Parâmetro inválido",
            detail="requisição inválida",
            errors=erros,
        ),
    )


def _handle_upstream(request: Request, exc: Exception) -> Response:
    problem = ProblemError(ErrorCode.FONTE_INDISPONIVEL, "fonte de dados indisponível")
    if _is_web(request):
        return pagina_erro(request, problem, retry_after=RETRY_AFTER_SEGUNDOS)
    return problem_response(request, problem)


def _handle_http(request: Request, exc: Exception) -> Response:
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
    if _is_web(request):
        # 404 de **rota** não é recurso do recorte MG: a página diz "Página não
        # encontrada" e oferece a busca. Escola/município inexistente chega por
        # `ProblemError` (`_handle_problem`) e mantém o texto do recorte.
        if exc.status_code == 404:
            return pagina_inexistente(request, problem)
        return pagina_erro(
            request,
            problem,
            retry_after=RETRY_AFTER_SEGUNDOS if problem.status == 503 else None,
        )
    return problem_response(request, problem)


def _handle_unexpected(request: Request, exc: Exception) -> Response:
    logger.exception("erro não tratado em %s", request.url.path)
    problem = ProblemError(ErrorCode.ERRO_INTERNO, "erro interno")
    if _is_web(request):
        return pagina_erro(request, problem)
    return problem_response(request, problem)


def _is_web(request: Request) -> bool:
    """Páginas do front (`/` e `/app`) respondem HTML; `/v1` e `/health`, JSON."""
    return e_caminho_web(request.url.path)


app = create_app()
