"""Logging estruturado em JSON no stdout (revisão 2 do card `t_817a670c`).

Estes testes não usam `caplog`: capturam o **stdout** do logger já configurado
como o processo configura em produção, que é o que o Cloud Logging consome.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from panorama_api.config import Settings
from panorama_api.core.logging_config import _HANDLER_FLAG, configure_logging
from panorama_api.repositories.bigquery_repo import BigQueryServingRepository
from tests.unit.conftest import concentracao_row, market_row, municipio_row

MARKET_URL = "/v1/markets/3106200"


class _FakeJob:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def result(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeClient:
    """Client mínimo do BigQuery: devolve as linhas e não fala com a rede."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    def query(self, sql: str, *, job_config: Any = None, location: str | None = None):
        return _FakeJob(self.rows)


def _json_lines(out: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in out.splitlines() if line.startswith("{")]


def _nosso_handler() -> list[logging.Handler]:
    return [
        handler
        for handler in logging.getLogger("panorama_api").handlers
        if getattr(handler, _HANDLER_FLAG, False)
    ]


def test_app_configura_info_para_os_loggers_do_app_sem_caplog():
    configure_logging(force=True)

    for name in (
        "panorama_api.core.http_cache",
        "panorama_api.repositories.bigquery_repo",
    ):
        assert logging.getLogger(name).isEnabledFor(logging.INFO)


def test_configure_logging_e_idempotente():
    configure_logging(force=True)
    configure_logging()
    configure_logging(force=True)

    assert len(_nosso_handler()) == 1


def test_cache_hit_e_miss_saem_no_stdout_em_json(capsys, client, repository):
    configure_logging(force=True)
    repository.municipios = [municipio_row()]
    repository.markets = [market_row(etapa="bas")]
    repository.concentracao = [concentracao_row(etapa="bas")]
    capsys.readouterr()  # o que veio da montagem do app não interessa

    client.get(MARKET_URL, params={"ano": 2025})
    client.get(MARKET_URL, params={"ano": 2025})

    linhas = _json_lines(capsys.readouterr().out)
    cache = [linha for linha in linhas if linha.get("message") == "http_cache"]

    assert [linha["cache"] for linha in cache] == ["miss", "hit"]
    assert {linha["severity"] for linha in cache} == {"INFO"}
    assert {linha["logger"] for linha in cache} == {"panorama_api.core.http_cache"}
    assert cache[0]["path"] == MARKET_URL
    assert cache[0]["status"] == 200
    assert cache[0]["timestamp"].endswith("Z")


def test_bq_ms_sai_no_stdout_pelo_repositorio_real(capsys):
    configure_logging(force=True)
    settings = Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        validate_schema_on_startup=False,
    )
    repo = BigQueryServingRepository(
        settings, client=_FakeClient(rows=[{"co_municipio": "3106200"}])
    )
    capsys.readouterr()

    repo.get_municipio("3106200")

    (linha,) = [
        item for item in _json_lines(capsys.readouterr().out)
        if item.get("message") == "bq_query"
    ]
    assert linha["endpoint"] == "municipio"
    assert linha["status"] == "ok"
    assert isinstance(linha["bq_ms"], float)
    assert linha["bq_ms"] >= 0.0
