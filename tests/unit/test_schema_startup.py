"""Validação de schema no startup (falha fechada — B1)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.core.startup import SchemaValidationError, validate_schema
from panorama_api.main import create_app
from tests.unit.conftest import FakeRepository, full_schema


def _schema_sem(table: str, column: str) -> dict[str, dict[str, str]]:
    schema = full_schema()
    del schema[table][column]
    return schema


def test_schema_completo_sobe(settings, repository):
    validate_schema(repository)  # não levanta


def test_coluna_ausente_derruba_o_startup(settings):
    schema = _schema_sem("dim_escola", "no_entidade")
    app = create_app(settings=settings, repository=FakeRepository(schema=schema))

    with pytest.raises(SchemaValidationError) as excinfo:
        with TestClient(app):
            pass

    assert "dim_escola.no_entidade: coluna ausente" in str(excinfo.value)


def test_tipo_divergente_derruba_o_startup(settings):
    schema = full_schema()
    schema["mart_mercado"]["etapa"] = "INTEGER"
    app = create_app(settings=settings, repository=FakeRepository(schema=schema))

    with pytest.raises(SchemaValidationError) as excinfo:
        with TestClient(app):
            pass

    mensagem = str(excinfo.value)
    assert "mart_mercado.etapa" in mensagem
    assert "INTEGER" in mensagem
    assert "STRING" in mensagem


def test_tabela_ausente_derruba_o_startup(settings):
    schema = full_schema()
    del schema["mart_market_share"]
    app = create_app(settings=settings, repository=FakeRepository(schema=schema))

    with pytest.raises(SchemaValidationError) as excinfo:
        with TestClient(app):
            pass

    assert "mart_market_share" in str(excinfo.value)


def test_validacao_pode_ser_desligada_por_env():
    settings = Settings(validate_schema_on_startup=False)
    schema = _schema_sem("dim_escola", "no_entidade")
    app = create_app(settings=settings, repository=FakeRepository(schema=schema))

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_informacao_schema_usa_tipo_normalizado():
    from panorama_api.repositories.bigquery_repo import normalize_type

    assert normalize_type("INT64") == "INTEGER"
    assert normalize_type("FLOAT64") == "FLOAT"
    assert normalize_type("BOOL") == "BOOLEAN"
    assert normalize_type("STRING") == "STRING"
