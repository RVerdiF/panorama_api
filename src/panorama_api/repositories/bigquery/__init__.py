"""Camada de consulta ao BigQuery do Panorama API.

Uso típico::

    settings = BigQuerySettings.from_env()
    executor = QueryExecutor(
        settings=settings,
        client=GoogleBigQueryClient(settings),
        rate_limiter=InProcessRateLimiter(limit=60, window_s=60.0),
    )
    result = executor.execute(
        "market_share",
        {"co_municipio": "3106200", "nu_ano_censo": 2024, "etapa": "fund_ai"},
        PageRequest(page_size=50),
        client_ip=request.client.host,
    )

Garantias da camada:

* SQL só de templates fixos; valores sempre em ``ScalarQueryParameter``;
* filtros obrigatórios validados antes de criar job (400 sem custo);
* ``maximum_bytes_billed``, labels e timeout em todo job;
* paginação ``LIMIT n+1`` (keyset ou offset), sem ``COUNT(*)``.
"""

from .client import GoogleBigQueryClient, QueryClient, sanitize_label
from .config import (
    DEFAULT_LOCATION,
    DEFAULT_MAX_BYTES_BILLED,
    BigQuerySettings,
)
from .errors import (
    BytesBudgetExceeded,
    ConfigurationError,
    InvalidQueryRequest,
    QueryExecutionError,
    QueryLayerError,
    QueryTimeout,
    RateLimited,
    TemplateError,
)
from .executor import QueryExecutor, QueryResult
from .pagination import (
    KeysetColumn,
    PageInfo,
    PageRequest,
    PaginationMode,
    encode_cursor,
)
from .parameters import ETAPAS, ParamSpec, ParamType
from .ratelimit import InProcessRateLimiter, RateLimitDecision
from .templates import TEMPLATES, QueryTemplate, get_template

__all__ = [
    "BigQuerySettings",
    "BytesBudgetExceeded",
    "ConfigurationError",
    "DEFAULT_LOCATION",
    "DEFAULT_MAX_BYTES_BILLED",
    "ETAPAS",
    "GoogleBigQueryClient",
    "InProcessRateLimiter",
    "InvalidQueryRequest",
    "KeysetColumn",
    "PageInfo",
    "PageRequest",
    "PaginationMode",
    "ParamSpec",
    "ParamType",
    "QueryClient",
    "QueryExecutionError",
    "QueryExecutor",
    "QueryLayerError",
    "QueryResult",
    "QueryTemplate",
    "QueryTimeout",
    "RateLimitDecision",
    "RateLimited",
    "TEMPLATES",
    "TemplateError",
    "encode_cursor",
    "get_template",
    "sanitize_label",
]
