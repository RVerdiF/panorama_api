"""Executor ponta a ponta (client falso): linhas, NULL, timeout e falhas."""

from __future__ import annotations

import pytest

from panorama_api.repositories.bigquery import (
    BigQuerySettings,
    BytesBudgetExceeded,
    PageRequest,
    ParamType,
    QueryExecutionError,
    QueryExecutor,
    QueryTimeout,
)

from tests.unit.conftest import FakeQueryClient

SHARE = {"co_municipio": "3106200", "nu_ano_censo": 2024, "etapa": "fund_ai"}


def _executor(rows=(), error: Exception | None = None):
    client = FakeQueryClient(rows=rows, error=error)
    settings = BigQuerySettings(project="p", dataset="d")
    return QueryExecutor(settings=settings, client=client), client, settings


def test_resultado_preserva_null_e_nao_converte_para_zero() -> None:
    rows = [
        {
            "id_entidade": "31000001",
            "no_entidade": None,
            "mat_entidade": None,
            "share_privado_pct": 12.5,
            "is_abaixo_porte": True,
        }
    ]
    executor, _client, _settings = _executor(rows=rows)

    result = executor.execute("market_share", SHARE)

    assert result.rows[0]["no_entidade"] is None
    assert result.rows[0]["mat_entidade"] is None
    assert result.rows[0]["share_privado_pct"] == 12.5


def test_endpoint_e_parametros_chegam_ao_client() -> None:
    executor, client, settings = _executor()

    executor.execute("market_share", SHARE, PageRequest(page_size=25))

    call = client.calls[0]
    assert call["endpoint"] == "market_share"
    assert call["timeout_s"] == settings.timeout_s
    params = {name: (tipo, valor) for name, tipo, valor in call["parameters"]}
    assert params["co_municipio"] == (ParamType.STRING, "3106200")
    assert params["nu_ano_censo"] == (ParamType.INT64, 2024)
    assert params["etapa"] == (ParamType.STRING, "fund_ai")
    assert params["page_limit"] == (ParamType.INT64, 26)
    assert params["page_offset"] == (ParamType.INT64, 0)


def test_filtros_opcionais_ausentes_nao_viram_parametro() -> None:
    executor, client, _settings = _executor()

    executor.execute("market", {"co_municipio": "3106200", "nu_ano_censo": 2024})

    nomes = {name for name, _tipo, _valor in client.calls[0]["parameters"]}
    assert "etapa" not in nomes
    assert "@etapa" not in client.last_sql


def test_timeout_e_erro_do_client_propagam() -> None:
    executor, _client, _settings = _executor(error=QueryTimeout("estourou"))

    with pytest.raises(QueryTimeout):
        executor.execute("market_share", SHARE)


def test_teto_de_bytes_estourado_propaga_como_503() -> None:
    executor, _client, _settings = _executor(error=BytesBudgetExceeded("teto"))

    with pytest.raises(QueryExecutionError) as exc:
        executor.execute("market_share", SHARE)

    assert exc.value.http_status == 503
    assert exc.value.code == "FONTE_INDISPONIVEL"


def test_template_com_join_renderiza_dataset_nas_duas_tabelas() -> None:
    executor, client, _settings = _executor()

    executor.execute("school_indicators", {"co_entidade": "31000000"})

    sql = client.last_sql
    assert "d.mart_escola_indicadores" in sql
    assert "d.mart_competidores" in sql
    assert "LEFT JOIN" in sql


def test_resultado_e_imutavel() -> None:
    executor, _client, _settings = _executor(rows=[{"co_entidade": "1"}])

    result = executor.execute("school", {"co_entidade": "31000000"})

    assert isinstance(result.rows, tuple)
    with pytest.raises(TypeError):
        result.rows[0] = {}  # type: ignore[index]
