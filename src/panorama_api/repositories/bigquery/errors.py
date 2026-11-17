"""Exceções da camada de consulta ao BigQuery.

A camada é framework-agnóstica: cada erro carrega ``http_status`` e ``code``
para que a borda HTTP (FastAPI ou outra) traduza o erro sem recalcular a
política. Nenhuma mensagem carrega SQL, parâmetros de usuário ou credenciais.
"""

from __future__ import annotations


class QueryLayerError(Exception):
    """Base de todos os erros da camada de consulta."""

    http_status: int = 500
    code: str = "INTERNAL_ERROR"
    title: str = "Erro interno"

    def __init__(self, detail: str, *, field: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.field = field


class ConfigurationError(QueryLayerError):
    """Configuração ausente ou inválida; deve falhar no startup, não por request."""

    http_status = 500
    code = "CONFIGURACAO_INVALIDA"
    title = "Configuração inválida"


class InvalidQueryRequest(QueryLayerError):
    """Requisição recusada antes de qualquer job do BigQuery (HTTP 400)."""

    http_status = 400
    code = "PARAMETRO_INVALIDO"
    title = "Parâmetro inválido"


class RateLimited(QueryLayerError):
    """Limite de requisições por IP excedido (HTTP 429)."""

    http_status = 429
    code = "RATE_LIMITED"
    title = "Requisições excessivas"

    def __init__(self, detail: str, *, retry_after_s: float) -> None:
        super().__init__(detail)
        self.retry_after_s = retry_after_s


class QueryExecutionError(QueryLayerError):
    """Falha ao executar a consulta no BigQuery (HTTP 503)."""

    http_status = 503
    code = "FONTE_INDISPONIVEL"
    title = "Fonte de dados indisponível"


class QueryTimeout(QueryExecutionError):
    """Consulta excedeu o timeout configurado."""


class BytesBudgetExceeded(QueryExecutionError):
    """Consulta abortada por ``maximum_bytes_billed`` (bytesBilledLimitExceeded)."""


class TemplateError(QueryLayerError):
    """Erro de programação no registro de templates (nunca causado pelo cliente)."""

    http_status = 500
    code = "TEMPLATE_INVALIDO"
    title = "Template de consulta inválido"
