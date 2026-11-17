"""Configuração por ambiente: defaults da decisão de 2026-11-17 e falha fechada."""

from __future__ import annotations

import pytest

from panorama_api.repositories.bigquery import BigQuerySettings
from panorama_api.repositories.bigquery.config import (
    DEFAULT_LOCATION,
    DEFAULT_MAX_BYTES_BILLED,
    DEFAULT_TIMEOUT_S,
)
from panorama_api.repositories.bigquery.errors import ConfigurationError


def test_teto_provisorio_de_256_mb() -> None:
    # Decisão 2026-11-17: 256 MB provisório até a clusterização (t_cfe70dd5).
    assert DEFAULT_MAX_BYTES_BILLED == 268_435_456
    settings = BigQuerySettings.from_env({"GCP_PROJECT": "p", "BQ_SERVING_DATASET": "d"})
    assert settings.max_bytes_billed == 268_435_456


def test_defaults_operacionais() -> None:
    settings = BigQuerySettings.from_env({"GCP_PROJECT": "p", "BQ_SERVING_DATASET": "d"})
    assert settings.location == DEFAULT_LOCATION == "us-central1"
    assert settings.timeout_s == DEFAULT_TIMEOUT_S == 10.0
    assert settings.page_size_default == 50
    assert settings.page_size_max == 500
    assert settings.offset_max == 1000


def test_ambiente_sobrescreve_todos_os_campos() -> None:
    settings = BigQuerySettings.from_env(
        {
            "GCP_PROJECT": "projeto",
            "BQ_SERVING_DATASET": "serving",
            "BQ_LOCATION": "southamerica-east1",
            "BQ_MAX_BYTES_BILLED": "104857600",
            "BQ_TIMEOUT_S": "5",
            "API_PAGE_DEFAULT": "20",
            "API_PAGE_MAX": "100",
            "API_OFFSET_MAX": "10",
            "DATA_VERSION": "2026.1",
            "SERVICE_NAME": "panorama-api",
        }
    )
    assert settings.project == "projeto"
    assert settings.dataset == "serving"
    assert settings.location == "southamerica-east1"
    assert settings.max_bytes_billed == 104_857_600
    assert settings.timeout_s == 5.0
    assert settings.page_size_default == 20
    assert settings.page_size_max == 100
    assert settings.offset_max == 10
    assert settings.data_version == "2026.1"


@pytest.mark.parametrize(
    "env",
    [
        {"BQ_SERVING_DATASET": "d"},
        {"GCP_PROJECT": "p"},
        {"GCP_PROJECT": "p", "BQ_SERVING_DATASET": "serving; DROP TABLE x"},
        {"GCP_PROJECT": "p", "BQ_SERVING_DATASET": "d", "BQ_MAX_BYTES_BILLED": "256MB"},
        {"GCP_PROJECT": "p", "BQ_SERVING_DATASET": "d", "BQ_MAX_BYTES_BILLED": "0"},
        {"GCP_PROJECT": "p", "BQ_SERVING_DATASET": "d", "BQ_TIMEOUT_S": "0"},
        {"GCP_PROJECT": "p", "BQ_SERVING_DATASET": "d", "BQ_LOCATION": "us central"},
        {"GCP_PROJECT": "p", "BQ_SERVING_DATASET": "d", "API_PAGE_MAX": "10"},
    ],
)
def test_configuracao_invalida_falha_no_startup(env: dict[str, str]) -> None:
    with pytest.raises(ConfigurationError):
        BigQuerySettings.from_env(env)


def test_dataset_interpolado_apenas_na_relacao() -> None:
    settings = BigQuerySettings(project="p", dataset="serving")
    assert settings.render_table("dim_escola") == "serving.dim_escola"
    assert settings.render_relation("{dataset}.dim_escola") == "serving.dim_escola"
    assert (
        settings.render_relation("{dataset}.a AS x LEFT JOIN {dataset}.b AS y ON x.k = y.k")
        == "serving.a AS x LEFT JOIN serving.b AS y ON x.k = y.k"
    )
    with pytest.raises(ConfigurationError):
        settings.render_table("dim_escola; DROP TABLE")
