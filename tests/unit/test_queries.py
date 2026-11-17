"""Allowlist e parametrização das consultas (sem SQL do cliente)."""

from __future__ import annotations

import pytest

from panorama_api.repositories import queries
from panorama_api.repositories.expected_schema import EXPECTED_COLUMNS


def _fq(table: str) -> str:
    return f"`panorama-escola-staging.panorama_serving.{table}`"


def test_busca_parametriza_o_termo_e_trata_curinga_como_texto():
    sql, params = queries.search_schools(
        _fq,
        q="50%_a\\b",
        co_entidade=None,
        co_municipio=None,
        tp_dependencia=None,
        apenas_ativas=False,
        limit=20,
        offset=0,
    )

    valor = next(value for name, _, value in params if name == "q")
    # STRPOS: substring literal — `%` e `_` não são wildcard
    assert valor == "50%_a\\b"
    assert "STRPOS(LOWER(no_entidade), @q) > 0" in sql
    assert "LIKE" not in sql
    assert "50%" not in sql


def test_busca_nao_interpola_valor_do_cliente():
    tentativa = "x' OR 1=1 --"
    sql, _ = queries.search_schools(
        _fq,
        q=tentativa,
        co_entidade=None,
        co_municipio=None,
        tp_dependencia=None,
        apenas_ativas=False,
        limit=20,
        offset=0,
    )

    assert tentativa not in sql
    assert "OR 1=1" not in sql


def test_busca_tem_filtro_mg_e_ordenacao_fixa():
    sql, _ = queries.search_schools(
        _fq,
        q="modelo",
        co_entidade=None,
        co_municipio=None,
        tp_dependencia=None,
        apenas_ativas=False,
        limit=20,
        offset=0,
    )

    assert "sg_uf = 'MG'" in sql
    assert "ORDER BY (no_entidade IS NULL), no_entidade, co_entidade" in sql
    assert "LIMIT 21 OFFSET 0" in sql  # L+1 para has_more


def test_busca_nao_expoe_cnpj_completo_nem_geom():
    sql, _ = queries.search_schools(
        _fq,
        q="modelo",
        co_entidade=None,
        co_municipio=None,
        tp_dependencia=None,
        apenas_ativas=False,
        limit=20,
        offset=0,
    )

    assert "nu_cnpj_escola_privada" not in sql
    assert "cnpj_completo_mantenedora" not in sql
    assert "geom" not in sql


def test_historico_por_escola_ordenado_asc():
    sql, params = queries.school_history(
        _fq, co_entidade="31000001", ano_inicio=2020, ano_fim=2025
    )

    assert "FROM `panorama-escola-staging.panorama_serving.mart_escola`" in sql
    assert "WHERE co_entidade = @co_entidade AND is_mg = TRUE" in sql
    assert "nu_ano_censo >= @ano_inicio" in sql
    assert "nu_ano_censo <= @ano_fim" in sql
    assert "ORDER BY nu_ano_censo ASC" in sql
    assert "is_mg" not in sql.split("SELECT", 1)[1].split("FROM", 1)[0]
    assert [(name, type_) for name, type_, _ in params] == [
        ("co_entidade", "STRING"),
        ("ano_inicio", "INT64"),
        ("ano_fim", "INT64"),
    ]


def test_share_join_com_mantenedora_e_ordenacao_declarada():
    sql, params = queries.market_share(
        _fq,
        co_municipio="3106200",
        ano=2025,
        etapa="bas",
        entidade_tipo="mantenedora",
        limit=50,
        offset=0,
    )

    assert "LEFT JOIN `panorama-escola-staging.panorama_serving.dim_mantenedora` AS m" in sql
    assert "m.cnpj_raiz_mantenedora = s.id_entidade" in sql
    assert "ORDER BY (s.mat_entidade IS NULL), s.mat_entidade DESC, s.id_entidade ASC" in sql
    assert "LIMIT 51 OFFSET 0" in sql
    assert [name for name, _, _ in params] == [
        "co_municipio",
        "ano",
        "etapa",
        "entidade_tipo",
    ]


@pytest.mark.parametrize(
    "builder",
    [
        lambda: queries.search_schools(
            _fq,
            q=None,
            co_entidade="31000001",
            co_municipio=None,
            tp_dependencia=None,
            apenas_ativas=False,
            limit=20,
            offset=0,
        ),
        lambda: queries.school_history(
            _fq, co_entidade="31000001", ano_inicio=None, ano_fim=None
        ),
        lambda: queries.school_indicators(_fq, co_entidade="31000001", ano=None),
        lambda: queries.school_competidores(_fq, co_entidade="31000001"),
        lambda: queries.municipio(_fq, co_municipio="3106200"),
        lambda: queries.market(_fq, co_municipio="3106200", ano=2025, etapa=None),
        lambda: queries.concentracao(_fq, co_municipio="3106200", ano=2025, etapa=None),
        lambda: queries.market_share(
            _fq,
            co_municipio="3106200",
            ano=2025,
            etapa="bas",
            entidade_tipo="escola",
            limit=50,
            offset=0,
        ),
    ],
)
def test_nenhuma_consulta_usa_count_total(builder):
    sql, _ = builder()

    # `has_more` vem de LIMIT L+1; COUNT(*) seria um scan extra no BigQuery.
    assert "COUNT(" not in sql.upper()


def test_colunas_selecionadas_existem_no_schema_esperado():
    selecionadas = {
        "dim_escola": queries.DIM_ESCOLA_SELECT,
        "mart_escola": queries.MART_ESCOLA_SELECT,
        "mart_escola_indicadores": queries.MART_ESCOLA_INDICADORES_SELECT,
        "mart_competidores": queries.MART_COMPETIDORES_SELECT,
        "mart_mercado": queries.MART_MERCADO_SELECT,
        "mart_concentracao": queries.MART_CONCENTRACAO_SELECT,
    }
    for table, select in selecionadas.items():
        for coluna in select.split(", "):
            assert coluna in EXPECTED_COLUMNS[table], f"{table}.{coluna} não validada"


def test_information_schema_cobre_todas_as_tabelas_usadas():
    sql = queries.INFORMATION_SCHEMA_SQL.format(
        project="panorama-escola-staging",
        dataset="panorama_serving",
        tables=", ".join(f"'{name}'" for name in EXPECTED_COLUMNS),
    )

    assert "INFORMATION_SCHEMA.COLUMNS" in sql
    for table in EXPECTED_COLUMNS:
        assert f"'{table}'" in sql
