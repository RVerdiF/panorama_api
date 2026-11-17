"""Fixtures dos testes herméticos da camada BigQuery (sem rede/credencial)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pytest

from panorama_api.repositories.bigquery import BigQuerySettings
from panorama_api.repositories.bigquery.parameters import ParamType


class FakeQueryClient:
    """Client falso: registra as chamadas e devolve linhas pré-definidas."""

    def __init__(self, rows: Sequence[Mapping[str, Any]] = (), error: Exception | None = None):
        self.rows = [dict(row) for row in rows]
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def run_query(
        self,
        *,
        sql: str,
        endpoint: str,
        parameters: Sequence[tuple[str, ParamType, Any]],
        timeout_s: float,
    ) -> list[Mapping[str, Any]]:
        self.calls.append(
            {
                "sql": sql,
                "endpoint": endpoint,
                "parameters": tuple(parameters),
                "timeout_s": timeout_s,
            }
        )
        if self.error is not None:
            raise self.error
        return [dict(row) for row in self.rows]

    @property
    def last_sql(self) -> str:
        return self.calls[-1]["sql"]

    @property
    def last_params(self) -> dict[str, Any]:
        return {name: value for name, _type, value in self.calls[-1]["parameters"]}


@pytest.fixture
def settings() -> BigQuerySettings:
    return BigQuerySettings(project="panorama-escola-staging", dataset="panorama_serving")


@pytest.fixture
def fake_client() -> FakeQueryClient:
    return FakeQueryClient()
