"""Injeção de SQL: valor vira literal parametrizado, SQL não muda."""

from __future__ import annotations

import pytest

from panorama_api.repositories.bigquery import (
    BigQuerySettings,
    InvalidQueryRequest,
    PageRequest,
    QueryExecutor,
)

from conftest import FakeQueryClient

MUNICIPIO = {"co_municipio": "3106200"}
PAYLOADS = [
    "1' OR '1'='1",
    "'; DROP TABLE dim_escola; --",
    "x%' OR no_entidade IS NOT NULL --",
    "ESCOLA') UNION ALL SELECT * FROM `panorama_serving.mart_escola` --",
]


def _executor() -> tuple[QueryExecutor, FakeQueryClient]:
    client = FakeQueryClient()
    return (
        QueryExecutor(settings=BigQuerySettings(project="p", dataset="d"), client=client),
        client,
    )


def test_valor_de_busca_nao_altera_o_sql() -> None:
    executor, client = _executor()

    executor.execute("schools", {**MUNICIPIO, "no_entidade_prefix": "Escola Sacre"})
    sql_limpo = client.last_sql

    executor.execute("schools", {**MUNICIPIO, "no_entidade_prefix": PAYLOADS[0]})
    sql_injetado = client.last_sql

    assert sql_limpo == sql_injetado
    assert PAYLOADS[0] not in sql_injetado
    assert client.last_params["no_entidade_prefix"] == PAYLOADS[0].upper()


@pytest.mark.parametrize("payload", PAYLOADS)
def test_valor_permanece_literal_no_parametro(payload: str) -> None:
    executor, client = _executor()

    executor.execute("schools", {**MUNICIPIO, "no_entidade_prefix": payload})

    assert client.last_params["no_entidade_prefix"] == payload.upper()
    assert payload not in client.last_sql


@pytest.mark.parametrize("payload", PAYLOADS)
def test_codigo_geografico_com_injecao_e_rejeitado(payload: str) -> None:
    executor, client = _executor()

    with pytest.raises(InvalidQueryRequest):
        executor.execute("schools", {"co_municipio": payload})

    with pytest.raises(InvalidQueryRequest):
        executor.execute("school", {"co_entidade": payload})

    assert client.calls == []


def test_cursor_vira_parametro_e_nao_texto_sql() -> None:
    from panorama_api.repositories.bigquery.pagination import encode_cursor

    executor, client = _executor()
    cursor = encode_cursor(["x' OR 1=1 --", "31000049"])

    executor.execute("schools", MUNICIPIO, PageRequest(cursor=cursor))

    assert "x' OR 1=1 --" not in client.last_sql
    assert client.last_params["cursor_0"] == "x' OR 1=1 --"


def test_sql_nao_contem_valores_do_cliente_para_outros_templates() -> None:
    executor, client = _executor()

    executor.execute(
        "market_share",
        {"co_municipio": "3106200", "nu_ano_censo": 2024, "etapa": "fund_ai"},
    )

    sql = client.last_sql
    for valor in ("3106200", "2024", "fund_ai"):
        assert valor not in sql
    assert client.last_params["co_municipio"] == "3106200"
    assert client.last_params["nu_ano_censo"] == 2024
