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

"""Fixtures hermética: repositório fake no lugar do BigQuery (sem rede, sem dataset)."""


from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.contract import OFERTA_ETAPAS
from panorama_api.main import create_app
from panorama_api.repositories.expected_schema import EXPECTED_COLUMNS


def null_row(table: str, **overrides: Any) -> dict[str, Any]:
    """Linha com todas as colunas do mart em NULL; overrides preenchem só o que importa."""
    row: dict[str, Any] = {column: None for column in EXPECTED_COLUMNS[table]}
    row.update(overrides)
    return row


def school_row(**overrides: Any) -> dict[str, Any]:
    row = null_row(
        "dim_escola",
        co_entidade="31000001",
        no_entidade="ESCOLA MODELO",
        co_municipio="3106200",
        no_municipio="BELO HORIZONTE",
        sg_uf="MG",
        tp_dependencia="4",
        tp_categoria_escola_privada="1",
        tp_localizacao="1",
        tp_situacao_funcionamento="1",
        cnpj_raiz_mantenedora="00012345",
        is_cnpj_generic=False,
        is_oferta_desconhecida=False,
        nu_ano_ultimo_registro=2025,
        n_anos_serie=6,
        ano_primeiro_registro=2020,
        ano_ultimo_registro=2025,
    )
    for etapa in OFERTA_ETAPAS:
        row[f"of_{etapa}"] = 1
    row.update(overrides)
    return row


def history_row(**overrides: Any) -> dict[str, Any]:
    row = null_row(
        "mart_escola",
        nu_ano_censo=2025,
        co_entidade="31000001",
        no_entidade="ESCOLA MODELO",
        co_municipio="3106200",
        no_municipio="BELO HORIZONTE",
        is_mg=True,
        tp_dependencia="4",
        is_cnpj_generic=False,
        is_oferta_desconhecida=False,
        qt_mat_bas=120,
        is_qt_mat_bas_missing=False,
        n_etapas_metodologia_incomparavel=0,
        latitude=-19.9,
        longitude=-43.9,
        geocode_precision="rua",
        confidence_score=0.95,
        needs_review=0,
    )
    for etapa in OFERTA_ETAPAS:
        row[f"of_{etapa}"] = 1
    row.update(overrides)
    return row


def indicator_row(**overrides: Any) -> dict[str, Any]:
    row = null_row(
        "mart_escola_indicadores",
        co_entidade="31000001",
        nu_ano_censo=2025,
        no_entidade="ESCOLA MODELO",
        co_municipio="3106200",
        no_municipio="BELO HORIZONTE",
        cnpj_raiz_mantenedora="00012345",
        is_cnpj_generic=False,
        is_oferta_desconhecida=False,
        qt_mat_bas=120,
        is_qt_mat_bas_missing=False,
        retencao_liquida_proxy_pct=98.5,
        is_abaixo_porte=False,
        n_etapas_metodologia_incomparavel=0,
    )
    row.update(overrides)
    return row


def competidor_row(**overrides: Any) -> dict[str, Any]:
    row = null_row(
        "mart_competidores",
        nu_ano_censo=2025,
        co_entidade="31000001",
        no_entidade="ESCOLA MODELO",
        co_municipio="3106200",
        qt_mat_bas=120,
        rank_mat_bas_municipio=3,
        n_concorrentes_privados_municipio=10,
        n_concorrentes_com_matricula_bas=8,
        lider_no_entidade="ESCOLA LIDER",
        lider_qt_mat_bas=300,
        gap_mat_bas_para_lider=-180,
    )
    row.update(overrides)
    return row


def market_row(**overrides: Any) -> dict[str, Any]:
    row = null_row(
        "mart_mercado",
        co_municipio="3106200",
        nu_ano_censo=2025,
        etapa="bas",
        n_escolas_ativas=100,
        n_escolas_publicas=70,
        n_escolas_privadas=30,
        n_escolas_mat_linha_missing=1,
        n_escolas_mat_valor_missing=2,
        n_escolas_mat_missing=3,
        n_escolas_com_linha_matricula=99,
        qt_mat_total=50000.0,
        qt_mat_publica=35000.0,
        qt_mat_privada=15000.0,
        pct_privada_no_total_pct=30.0,
        n_escolas_entraram=None,
        n_escolas_ativas_com_baseline=None,
        n_escolas_sairam=None,
    )
    row.update(overrides)
    return row


def concentracao_row(**overrides: Any) -> dict[str, Any]:
    row = null_row(
        "mart_concentracao",
        co_municipio="3106200",
        nu_ano_censo=2025,
        etapa="bas",
        recorte="privadas",
        nivel="municipio",
        n_competidores=30,
        hhi=1200.0,
        share_lider_pct=22.5,
        c4_pct=60.0,
        soma_share_pct=100.0,
    )
    row.update(overrides)
    return row


def share_row(**overrides: Any) -> dict[str, Any]:
    row = null_row(
        "mart_market_share",
        co_municipio="3106200",
        nu_ano_censo=2025,
        etapa="bas",
        entidade_tipo="escola",
        id_entidade="31000001",
        no_entidade="ESCOLA MODELO",
        n_unidades=None,
        mat_entidade=120.0,
        n_escolas_privadas=30,
        n_escolas_ativas=100,
        qt_mat_privada=15000.0,
        qt_mat_total=50000.0,
        share_privado_pct=0.8,
        share_total_pct=0.24,
        is_abaixo_porte=False,
        no_grupo=None,
    )
    row.update(overrides)
    return row


def municipio_row(**overrides: Any) -> dict[str, Any]:
    row = null_row(
        "dim_geografia",
        co_municipio="3106200",
        no_municipio="BELO HORIZONTE",
        co_uf="31",
        sg_uf="MG",
        is_mg=True,
    )
    row.update(overrides)
    return row


def full_schema() -> dict[str, dict[str, str]]:
    return {table: dict(columns) for table, columns in EXPECTED_COLUMNS.items()}


class FakeRepository:
    """Implementação em memória do contrato de repositório (hermética)."""

    def __init__(
        self,
        *,
        schema: dict[str, dict[str, str]] | None = None,
        schools: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        indicators: list[dict[str, Any]] | None = None,
        competidores: list[dict[str, Any]] | None = None,
        municipios: list[dict[str, Any]] | None = None,
        markets: list[dict[str, Any]] | None = None,
        concentracao: list[dict[str, Any]] | None = None,
        share: list[dict[str, Any]] | None = None,
    ) -> None:
        self.schema = schema if schema is not None else full_schema()
        self.schools = schools or []
        self.history = history or []
        self.indicators = indicators or []
        self.competidores = competidores or []
        self.municipios = municipios or []
        self.markets = markets or []
        self.concentracao = concentracao or []
        self.share = share or []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.errors: dict[str, Exception] = {}

    # -- helpers --------------------------------------------------------
    def _record(self, name: str, kwargs: dict[str, Any]) -> None:
        self.calls.append((name, kwargs))
        if name in self.errors:
            raise self.errors[name]

    @staticmethod
    def _page(rows: list[dict[str, Any]], limit: int, offset: int) -> list[dict[str, Any]]:
        # Espelha o SQL: `LIMIT limit + 1 OFFSET offset`.
        return rows[offset : offset + limit + 1]

    def methods_called(self) -> list[str]:
        return [name for name, _ in self.calls]

    # -- leituras -------------------------------------------------------
    def search_schools(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._record("search_schools", kwargs)
        rows = self.schools
        if kwargs.get("co_entidade") is not None:
            rows = [r for r in rows if r["co_entidade"] == kwargs["co_entidade"]]
        if kwargs.get("co_municipio") is not None:
            rows = [r for r in rows if r["co_municipio"] == kwargs["co_municipio"]]
        if kwargs.get("q") is not None:
            termo = kwargs["q"].lower()
            rows = [r for r in rows if termo in (r.get("no_entidade") or "").lower()]
        if kwargs.get("tp_dependencia") is not None:
            rows = [r for r in rows if r["tp_dependencia"] == kwargs["tp_dependencia"]]
        if kwargs.get("apenas_ativas"):
            rows = [r for r in rows if r["tp_situacao_funcionamento"] == "1"]
        return self._page(rows, kwargs["limit"], kwargs["offset"])

    def get_school(self, co_entidade: str) -> dict[str, Any] | None:
        self._record("get_school", {"co_entidade": co_entidade})
        for row in self.schools:
            if row["co_entidade"] == co_entidade:
                return row
        return None

    def get_school_history(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._record("get_school_history", kwargs)
        rows = [r for r in self.history if r["co_entidade"] == kwargs["co_entidade"]]
        if kwargs.get("ano_inicio") is not None:
            rows = [r for r in rows if r["nu_ano_censo"] >= kwargs["ano_inicio"]]
        if kwargs.get("ano_fim") is not None:
            rows = [r for r in rows if r["nu_ano_censo"] <= kwargs["ano_fim"]]
        return sorted(rows, key=lambda r: r["nu_ano_censo"])

    def get_school_indicators(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._record("get_school_indicators", kwargs)
        rows = [r for r in self.indicators if r["co_entidade"] == kwargs["co_entidade"]]
        if kwargs.get("ano") is not None:
            rows = [r for r in rows if r["nu_ano_censo"] == kwargs["ano"]]
        return sorted(rows, key=lambda r: r["nu_ano_censo"])

    def get_school_competidores(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._record("get_school_competidores", kwargs)
        return [
            r for r in self.competidores if r["co_entidade"] == kwargs["co_entidade"]
        ]

    def get_municipio(self, co_municipio: str) -> dict[str, Any] | None:
        self._record("get_municipio", {"co_municipio": co_municipio})
        for row in self.municipios:
            if row["co_municipio"] == co_municipio:
                return row
        return None

    def get_market(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._record("get_market", kwargs)
        rows = [
            r
            for r in self.markets
            if r["co_municipio"] == kwargs["co_municipio"]
            and r["nu_ano_censo"] == kwargs["ano"]
        ]
        if kwargs.get("etapa") is not None:
            rows = [r for r in rows if r["etapa"] == kwargs["etapa"]]
        return sorted(rows, key=lambda r: r["etapa"])

    def get_concentracao(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._record("get_concentracao", kwargs)
        rows = [
            r
            for r in self.concentracao
            if r["co_municipio"] == kwargs["co_municipio"]
            and r["nu_ano_censo"] == kwargs["ano"]
        ]
        if kwargs.get("etapa") is not None:
            rows = [r for r in rows if r["etapa"] == kwargs["etapa"]]
        return rows

    def get_market_share(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._record("get_market_share", kwargs)
        rows = [
            r
            for r in self.share
            if r["co_municipio"] == kwargs["co_municipio"]
            and r["nu_ano_censo"] == kwargs["ano"]
            and r["etapa"] == kwargs["etapa"]
            and r["entidade_tipo"] == kwargs["entidade_tipo"]
        ]
        return self._page(rows, kwargs["limit"], kwargs["offset"])

    def get_table_columns(self) -> dict[str, dict[str, str]]:
        self._record("get_table_columns", {})
        return self.schema


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        max_bytes_billed=256 * 1024 * 1024,
        validate_schema_on_startup=True,
        contract_version="mvp-1",
    )


@pytest.fixture
def client(repository: FakeRepository, settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings=settings, repository=repository)
    with TestClient(app) as test_client:
        yield test_client
