"""Executor: valida a requisição antes de qualquer job, monta e pagina.

Ordem fixa (card ``t_ea2c4d84``):

1. rate limit por IP (se houver chave de cliente);
2. resolução do template na allowlist;
3. filtros obrigatórios e domínio → ``InvalidQueryRequest`` (400) **sem**
   chamar o BigQuery;
4. normalização de paginação → 400 sem job;
5. montagem do SQL a partir de constantes + parâmetros tipados;
6. execução com teto de bytes/labels/timeout (responsabilidade do client);
7. ``LIMIT page_size + 1`` → ``has_more``/``next_cursor``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .client import QueryClient
from .config import BigQuerySettings
from .errors import InvalidQueryRequest, RateLimited, TemplateError
from .pagination import PageInfo, PageRequest, plan_page, split_page
from .ratelimit import InProcessRateLimiter
from .templates import TEMPLATES, QueryTemplate


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Linhas já paginadas + metadados da página (``None`` se não paginado)."""

    endpoint: str
    rows: tuple[Mapping[str, Any], ...]
    page: PageInfo | None


class QueryExecutor:
    """Fachada da camada: uma chamada por consulta, com contrato único."""

    def __init__(
        self,
        *,
        settings: BigQuerySettings,
        client: QueryClient,
        templates: Mapping[str, QueryTemplate] | None = None,
        rate_limiter: InProcessRateLimiter | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._templates = dict(TEMPLATES if templates is None else templates)
        self._rate_limiter = rate_limiter

    @property
    def settings(self) -> BigQuerySettings:
        return self._settings

    def execute(
        self,
        template_name: str,
        filters: Mapping[str, Any] | None = None,
        page: PageRequest | None = None,
        *,
        client_ip: str | None = None,
    ) -> QueryResult:
        if client_ip is not None and self._rate_limiter is not None:
            decision = self._rate_limiter.check(client_ip)
            if not decision.allowed:
                raise RateLimited(
                    "limite de requisições por minuto excedido",
                    retry_after_s=decision.retry_after_s,
                )

        template = self._templates.get(template_name)
        if template is None:
            raise InvalidQueryRequest(
                f"template de consulta desconhecido: {template_name!r}", field="endpoint"
            )

        values = _normalize_filters(template, filters)

        max_page_size = min(
            self._settings.page_size_max,
            template.max_page_size or self._settings.page_size_max,
        )
        plan = plan_page(
            mode=template.pagination,
            request=page or PageRequest(),
            page_size_default=min(self._settings.page_size_default, max_page_size),
            page_size_max=max_page_size,
            offset_max=self._settings.offset_max,
            row_cap=template.row_cap or self._settings.row_cap,
            keyset_columns=template.keyset_columns,
        )

        parameters = tuple(
            (clause.spec.name, clause.spec.type, values[clause.name])
            for clause in template.clauses
            if clause.name in values
        ) + plan.parameters
        _assert_unique_params(template, parameters)

        sql = template.render(self._settings, plan, frozenset(values))
        rows = self._client.run_query(
            sql=sql,
            endpoint=template.name,
            parameters=parameters,
            timeout_s=self._settings.timeout_s,
        )
        items, page_info = split_page(mode=template.pagination, plan=plan, rows=rows)
        return QueryResult(endpoint=template.name, rows=tuple(items), page=page_info)


def _normalize_filters(
    template: QueryTemplate, raw: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Valida nomes, obrigatoriedade e domínio; devolve só valores normalizados."""
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise InvalidQueryRequest("filtros devem ser um mapa nome→valor")

    known = {clause.name: clause for clause in template.clauses}
    unknown = sorted(set(raw) - set(known))
    if unknown:
        raise InvalidQueryRequest(
            "filtros desconhecidos: " + ", ".join(unknown), field=unknown[0]
        )

    missing = [
        clause.name
        for clause in template.clauses
        if clause.required and _is_absent(raw.get(clause.name))
    ]
    if missing:
        raise InvalidQueryRequest(
            "filtros obrigatórios ausentes: " + ", ".join(missing), field=missing[0]
        )

    values: dict[str, Any] = {}
    for name, clause in known.items():
        value = raw.get(name)
        if _is_absent(value):
            continue
        values[name] = clause.spec.normalize(value)

    for check in template.cross_checks:
        check(values)
    return values


def _is_absent(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _assert_unique_params(
    template: QueryTemplate, parameters: Sequence[tuple[str, Any, Any]]
) -> None:
    names = [name for name, _, _ in parameters]
    if len(set(names)) != len(names):
        raise TemplateError(f"{template.name}: parâmetros duplicados na montagem")
