"""Implementação do repositório sobre BigQuery (views estáveis do contrato mvp-1)."""

from __future__ import annotations

import logging
from typing import Any

from panorama_api.config import Settings
from panorama_api.core.errors import UpstreamUnavailable
from panorama_api.repositories import queries
from panorama_api.repositories.expected_schema import EXPECTED_COLUMNS
from panorama_api.repositories.queries import Params

logger = logging.getLogger(__name__)

#: `INFORMATION_SCHEMA.COLUMNS` usa tipos do Standard SQL; normaliza para os do
#: contrato (`tables.get`): INT64→INTEGER, FLOAT64→FLOAT, BOOL→BOOLEAN.
_TYPE_ALIASES = {
    "INT64": "INTEGER",
    "FLOAT64": "FLOAT",
    "BOOL": "BOOLEAN",
}


def normalize_type(data_type: str) -> str:
    return _TYPE_ALIASES.get(data_type.upper(), data_type.upper())


class BigQueryServingRepository:
    """Consultas parametrizadas de allowlist contra `${BQ_PROJECT}.${BQ_DATASET}`."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client

    # -- infraestrutura -------------------------------------------------
    def _bq(self) -> Any:
        if self._client is None:
            from google.cloud import bigquery  # import tardio: caro e desnecessário em teste

            self._client = bigquery.Client(
                project=self._settings.bq_project, location=self._settings.bq_location
            )
        return self._client

    def _fq(self, table: str) -> str:
        return f"`{self._settings.bq_project}.{self._settings.bq_dataset}.{table}`"

    def _run(self, sql: str, params: Params) -> list[dict[str, Any]]:
        from google.api_core import exceptions as gexc
        from google.cloud import bigquery

        job_config = bigquery.QueryJobConfig(
            maximum_bytes_billed=self._settings.max_bytes_billed,
            query_parameters=[
                bigquery.ScalarQueryParameter(name, type_, value)
                for name, type_, value in params
            ],
        )
        try:
            job = self._bq().query(
                sql, job_config=job_config, location=self._settings.bq_location
            )
            result = job.result()
            return [dict(row.items()) for row in result]
        except (
            gexc.GoogleAPIError,
            TimeoutError,
            OSError,
        ) as exc:  # falha/timeout/teto de bytes: 503, sem SQL no corpo
            logger.warning("bigquery indisponível: %s", type(exc).__name__)
            raise UpstreamUnavailable("fonte de dados indisponível") from exc

    # -- leituras -------------------------------------------------------
    def search_schools(
        self,
        *,
        q: str | None,
        co_entidade: str | None,
        co_municipio: str | None,
        tp_dependencia: str | None,
        apenas_ativas: bool,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        sql, params = queries.search_schools(
            self._fq,
            q=q,
            co_entidade=co_entidade,
            co_municipio=co_municipio,
            tp_dependencia=tp_dependencia,
            apenas_ativas=apenas_ativas,
            limit=limit,
            offset=offset,
        )
        return self._run(sql, params)

    def get_school(self, co_entidade: str) -> dict[str, Any] | None:
        rows = self.search_schools(
            q=None,
            co_entidade=co_entidade,
            co_municipio=None,
            tp_dependencia=None,
            apenas_ativas=False,
            limit=1,
            offset=0,
        )
        return rows[0] if rows else None

    def get_school_history(
        self, *, co_entidade: str, ano_inicio: int | None, ano_fim: int | None
    ) -> list[dict[str, Any]]:
        sql, params = queries.school_history(
            self._fq, co_entidade=co_entidade, ano_inicio=ano_inicio, ano_fim=ano_fim
        )
        return self._run(sql, params)

    def get_school_indicators(
        self, *, co_entidade: str, ano: int | None
    ) -> list[dict[str, Any]]:
        sql, params = queries.school_indicators(self._fq, co_entidade=co_entidade, ano=ano)
        return self._run(sql, params)

    def get_school_competidores(self, *, co_entidade: str) -> list[dict[str, Any]]:
        sql, params = queries.school_competidores(self._fq, co_entidade=co_entidade)
        return self._run(sql, params)

    def get_municipio(self, co_municipio: str) -> dict[str, Any] | None:
        sql, params = queries.municipio(self._fq, co_municipio=co_municipio)
        rows = self._run(sql, params)
        return rows[0] if rows else None

    def get_market(
        self, *, co_municipio: str, ano: int, etapa: str | None
    ) -> list[dict[str, Any]]:
        sql, params = queries.market(
            self._fq, co_municipio=co_municipio, ano=ano, etapa=etapa
        )
        return self._run(sql, params)

    def get_concentracao(
        self, *, co_municipio: str, ano: int, etapa: str | None
    ) -> list[dict[str, Any]]:
        sql, params = queries.concentracao(
            self._fq, co_municipio=co_municipio, ano=ano, etapa=etapa
        )
        return self._run(sql, params)

    def get_market_share(
        self,
        *,
        co_municipio: str,
        ano: int,
        etapa: str,
        entidade_tipo: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        sql, params = queries.market_share(
            self._fq,
            co_municipio=co_municipio,
            ano=ano,
            etapa=etapa,
            entidade_tipo=entidade_tipo,
            limit=limit,
            offset=offset,
        )
        return self._run(sql, params)

    def get_table_columns(self) -> dict[str, dict[str, str]]:
        tables = ", ".join(f"'{name}'" for name in EXPECTED_COLUMNS)
        sql = queries.INFORMATION_SCHEMA_SQL.format(
            project=self._settings.bq_project,
            dataset=self._settings.bq_dataset,
            tables=tables,
        )
        columns: dict[str, dict[str, str]] = {}
        for row in self._run(sql, []):
            columns.setdefault(row["table_name"], {})[row["column_name"]] = normalize_type(
                row["data_type"]
            )
        return columns
