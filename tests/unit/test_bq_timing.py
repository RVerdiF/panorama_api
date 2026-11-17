"""Log estruturado `bq_ms` da camada de consulta (card `t_817a670c`)."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from google.api_core.exceptions import BadRequest

from panorama_api.config import Settings
from panorama_api.core.errors import UpstreamUnavailable
from panorama_api.repositories.bigquery_repo import BigQueryServingRepository


class _FakeJob:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def result(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeClient:
    """Client mínimo: registra a consulta e devolve linhas ou um erro."""

    def __init__(
        self, rows: list[dict[str, Any]] | None = None, error: Exception | None = None
    ) -> None:
        self.rows = rows or []
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def query(self, sql: str, *, job_config: Any = None, location: str | None = None):
        self.calls.append({"sql": sql, "job_config": job_config, "location": location})
        if self.error is not None:
            raise self.error
        return _FakeJob(self.rows)


def _settings() -> Settings:
    return Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        validate_schema_on_startup=False,
    )


def _repo(client: _FakeClient) -> BigQueryServingRepository:
    return BigQueryServingRepository(_settings(), client=client)


def _registros(caplog, chamada: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage() == chamada]


def test_consulta_bem_sucedida_loga_bq_ms_e_endpoint(caplog):
    client = _FakeClient(
        rows=[{"co_municipio": "3106200", "no_municipio": "BH", "is_mg": True}]
    )

    with caplog.at_level(
        logging.INFO, logger="panorama_api.repositories.bigquery_repo"
    ):
        linha = _repo(client).get_municipio("3106200")

    assert linha["co_municipio"] == "3106200"
    (registro,) = _registros(caplog, "bq_query")
    assert registro.endpoint == "municipio"
    assert registro.status == "ok"
    assert isinstance(registro.bq_ms, float)
    assert registro.bq_ms >= 0.0


def test_consulta_com_erro_loga_bq_ms_e_status_error(caplog):
    client = _FakeClient(error=BadRequest("teto de bytes estourado"))

    with caplog.at_level(
        logging.INFO, logger="panorama_api.repositories.bigquery_repo"
    ):
        with pytest.raises(UpstreamUnavailable):
            _repo(client).get_market(co_municipio="3106200", ano=2025, etapa="bas")

    (registro,) = _registros(caplog, "bq_query")
    assert registro.endpoint == "market"
    assert registro.status == "error"
    assert registro.bq_ms >= 0.0


def test_cada_endpoint_leva_seu_proprio_label(caplog):
    client = _FakeClient(rows=[{"co_entidade": "31000001"}])

    with caplog.at_level(
        logging.INFO, logger="panorama_api.repositories.bigquery_repo"
    ):
        repo = _repo(client)
        repo.get_school_history(co_entidade="31000001", ano_inicio=None, ano_fim=None)
        repo.get_school_indicators(co_entidade="31000001", ano=None)
        repo.get_school_competidores(co_entidade="31000001")

    endpoints = [r.endpoint for r in _registros(caplog, "bq_query")]
    assert endpoints == ["school_history", "school_indicators", "school_competidores"]
