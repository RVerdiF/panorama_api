"""Config de job: teto de bytes, labels e timeout em toda consulta."""

from __future__ import annotations

import pytest

from panorama_api.repositories.bigquery import (
    BigQuerySettings,
    GoogleBigQueryClient,
    ParamType,
    sanitize_label,
)


def _client(**overrides) -> GoogleBigQueryClient:
    settings = BigQuerySettings(
        project="panorama-escola-staging",
        dataset="panorama_serving",
        **overrides,
    )
    return GoogleBigQueryClient(settings)


def test_job_config_com_teto_padrao_de_256_mb() -> None:
    client = _client()
    config = client.build_job_config(
        endpoint="market_share",
        parameters=[("co_municipio", ParamType.STRING, "3106200")],
    )

    assert config.maximum_bytes_billed == 268_435_456
    assert config.use_query_cache is True
    assert int(config.job_timeout_ms) == 10_000
    assert config.labels == {
        "service": "panorama-api",
        "endpoint": "market_share",
        "data_version": "dev",
    }


def test_teto_de_bytes_vem_do_ambiente() -> None:
    settings = BigQuerySettings.from_env(
        {
            "GCP_PROJECT": "p",
            "BQ_SERVING_DATASET": "d",
            "BQ_MAX_BYTES_BILLED": "134217728",
            "BQ_TIMEOUT_S": "3",
        }
    )
    config = GoogleBigQueryClient(settings).build_job_config(
        endpoint="schools", parameters=[]
    )

    assert config.maximum_bytes_billed == 134_217_728
    assert int(config.job_timeout_ms) == 3_000


def test_parametros_tipados_chegam_ao_sdk() -> None:
    config = _client().build_job_config(
        endpoint="market_share",
        parameters=[
            ("co_municipio", ParamType.STRING, "3106200"),
            ("nu_ano_censo", ParamType.INT64, 2024),
        ],
    )

    api = {param.name: param.to_api_repr() for param in config.query_parameters}
    assert api["co_municipio"]["parameterType"]["type"] == "STRING"
    assert api["co_municipio"]["parameterValue"]["value"] == "3106200"
    assert api["nu_ano_censo"]["parameterType"]["type"] == "INT64"
    assert api["nu_ano_censo"]["parameterValue"]["value"] == "2024"


def test_valor_de_injecao_vira_literal_no_parametro() -> None:
    payload = "1' OR '1'='1"
    config = _client().build_job_config(
        endpoint="schools", parameters=[("no_entidade_prefix", ParamType.STRING, payload)]
    )

    (param,) = config.query_parameters
    assert param.to_api_repr()["parameterValue"]["value"] == payload


def test_label_do_endpoint_e_normalizada() -> None:
    config = _client(data_version="2026.1", service_name="Panorama API").build_job_config(
        endpoint="market_share", parameters=[]
    )

    assert config.labels["service"] == "panorama_api"
    assert config.labels["data_version"] == "v_2026_1"
    assert config.labels["endpoint"] == "market_share"


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("panorama-api", "panorama-api"),
        ("Market Share", "market_share"),
        ("", "unknown"),
        ("-_-", "unknown"),
        ("2026.1", "v_2026_1"),
        ("x" * 100, "x" * 63),
    ],
)
def test_sanitize_label(entrada: str, esperado: str) -> None:
    assert sanitize_label(entrada) == esperado
