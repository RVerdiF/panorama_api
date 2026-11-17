"""Consultas da v1 — allowlist fixa no código.

Regras (contrato §0):
- nenhum nome de tabela/coluna/ordenação vem do cliente;
- todo valor vindo do cliente entra como parâmetro (`@nome`);
- `LIMIT`/`OFFSET` são inteiros já validados (`int` computado, nunca texto do cliente);
- `has_more` via `LIMIT L+1` — sem `COUNT(*)`.
"""

from __future__ import annotations

from typing import Any, Callable, Final

from panorama_api.repositories.expected_schema import EXPECTED_COLUMNS

TableRef = Callable[[str], str]
Params = list[tuple[str, str, Any]]


def _columns(table: str, *, exclude: frozenset[str] = frozenset()) -> str:
    return ", ".join(col for col in EXPECTED_COLUMNS[table] if col not in exclude)


DIM_ESCOLA_SELECT: Final = _columns("dim_escola")
MART_ESCOLA_SELECT: Final = _columns("mart_escola", exclude=frozenset({"is_mg"}))
MART_ESCOLA_INDICADORES_SELECT: Final = _columns("mart_escola_indicadores")
MART_COMPETIDORES_SELECT: Final = _columns("mart_competidores")
MART_MERCADO_SELECT: Final = _columns("mart_mercado")
MART_CONCENTRACAO_SELECT: Final = _columns("mart_concentracao")
SHARE_SELECT: Final = (
    ", ".join(f"s.{col}" for col in EXPECTED_COLUMNS["mart_market_share"]) + ", m.no_grupo"
)


def search_schools(
    fq: TableRef,
    *,
    q: str | None,
    co_entidade: str | None,
    co_municipio: str | None,
    tp_dependencia: str | None,
    apenas_ativas: bool,
    limit: int,
    offset: int,
) -> tuple[str, Params]:
    clauses = ["sg_uf = 'MG'"]
    params: Params = []

    if q is not None:
        # BigQuery Standard SQL não aceita a cláusula ESCAPE do LIKE; `STRPOS`
        # faz busca literal de substring ("contém") sem curingas — `%` e `_` do
        # termo são tratados como texto, não como wildcard.
        clauses.append("STRPOS(LOWER(no_entidade), @q) > 0")
        params.append(("q", "STRING", q.lower()))
    if co_entidade is not None:
        clauses.append("co_entidade = @co_entidade")
        params.append(("co_entidade", "STRING", co_entidade))
    if co_municipio is not None:
        clauses.append("co_municipio = @co_municipio")
        params.append(("co_municipio", "STRING", co_municipio))
    if tp_dependencia is not None:
        clauses.append("tp_dependencia = @tp_dependencia")
        params.append(("tp_dependencia", "STRING", tp_dependencia))
    if apenas_ativas:
        clauses.append("tp_situacao_funcionamento = '1'")

    sql = (
        f"SELECT {DIM_ESCOLA_SELECT}\n"
        f"FROM {fq('dim_escola')}\n"
        f"WHERE {' AND '.join(clauses)}\n"
        "ORDER BY (no_entidade IS NULL), no_entidade, co_entidade\n"
        f"LIMIT {limit + 1} OFFSET {offset}"
    )
    return sql, params


def school_history(
    fq: TableRef,
    *,
    co_entidade: str,
    ano_inicio: int | None,
    ano_fim: int | None,
) -> tuple[str, Params]:
    clauses = ["co_entidade = @co_entidade", "is_mg = TRUE"]
    params: Params = [("co_entidade", "STRING", co_entidade)]
    if ano_inicio is not None:
        clauses.append("nu_ano_censo >= @ano_inicio")
        params.append(("ano_inicio", "INT64", ano_inicio))
    if ano_fim is not None:
        clauses.append("nu_ano_censo <= @ano_fim")
        params.append(("ano_fim", "INT64", ano_fim))

    sql = (
        f"SELECT {MART_ESCOLA_SELECT}\n"
        f"FROM {fq('mart_escola')}\n"
        f"WHERE {' AND '.join(clauses)}\n"
        "ORDER BY nu_ano_censo ASC"
    )
    return sql, params


def school_indicators(
    fq: TableRef, *, co_entidade: str, ano: int | None
) -> tuple[str, Params]:
    clauses = ["co_entidade = @co_entidade"]
    params: Params = [("co_entidade", "STRING", co_entidade)]
    if ano is not None:
        clauses.append("nu_ano_censo = @ano")
        params.append(("ano", "INT64", ano))

    sql = (
        f"SELECT {MART_ESCOLA_INDICADORES_SELECT}\n"
        f"FROM {fq('mart_escola_indicadores')}\n"
        f"WHERE {' AND '.join(clauses)}\n"
        "ORDER BY nu_ano_censo ASC"
    )
    return sql, params


def school_competidores(fq: TableRef, *, co_entidade: str) -> tuple[str, Params]:
    sql = (
        f"SELECT {MART_COMPETIDORES_SELECT}\n"
        f"FROM {fq('mart_competidores')}\n"
        "WHERE co_entidade = @co_entidade\n"
        "ORDER BY nu_ano_censo ASC"
    )
    return sql, [("co_entidade", "STRING", co_entidade)]


def municipio(fq: TableRef, *, co_municipio: str) -> tuple[str, Params]:
    sql = (
        f"SELECT {_columns('dim_geografia')}\n"
        f"FROM {fq('dim_geografia')}\n"
        "WHERE co_municipio = @co_municipio AND is_mg = TRUE"
    )
    return sql, [("co_municipio", "STRING", co_municipio)]


def market(
    fq: TableRef, *, co_municipio: str, ano: int, etapa: str | None
) -> tuple[str, Params]:
    clauses = ["co_municipio = @co_municipio", "nu_ano_censo = @ano"]
    params: Params = [
        ("co_municipio", "STRING", co_municipio),
        ("ano", "INT64", ano),
    ]
    if etapa is not None:
        clauses.append("etapa = @etapa")
        params.append(("etapa", "STRING", etapa))

    sql = (
        f"SELECT {MART_MERCADO_SELECT}\n"
        f"FROM {fq('mart_mercado')}\n"
        f"WHERE {' AND '.join(clauses)}\n"
        "ORDER BY etapa ASC"
    )
    return sql, params


def concentracao(
    fq: TableRef, *, co_municipio: str, ano: int, etapa: str | None
) -> tuple[str, Params]:
    clauses = ["co_municipio = @co_municipio", "nu_ano_censo = @ano"]
    params: Params = [
        ("co_municipio", "STRING", co_municipio),
        ("ano", "INT64", ano),
    ]
    if etapa is not None:
        clauses.append("etapa = @etapa")
        params.append(("etapa", "STRING", etapa))

    sql = (
        f"SELECT {MART_CONCENTRACAO_SELECT}\n"
        f"FROM {fq('mart_concentracao')}\n"
        f"WHERE {' AND '.join(clauses)}\n"
        "ORDER BY etapa ASC, recorte ASC, nivel ASC"
    )
    return sql, params


def market_share(
    fq: TableRef,
    *,
    co_municipio: str,
    ano: int,
    etapa: str,
    entidade_tipo: str,
    limit: int,
    offset: int,
) -> tuple[str, Params]:
    params: Params = [
        ("co_municipio", "STRING", co_municipio),
        ("ano", "INT64", ano),
        ("etapa", "STRING", etapa),
        ("entidade_tipo", "STRING", entidade_tipo),
    ]
    sql = (
        f"SELECT {SHARE_SELECT}\n"
        f"FROM {fq('mart_market_share')} AS s\n"
        f"LEFT JOIN {fq('dim_mantenedora')} AS m\n"
        "  ON m.cnpj_raiz_mantenedora = s.id_entidade\n"
        "WHERE s.co_municipio = @co_municipio\n"
        "  AND s.nu_ano_censo = @ano\n"
        "  AND s.etapa = @etapa\n"
        "  AND s.entidade_tipo = @entidade_tipo\n"
        "ORDER BY (s.mat_entidade IS NULL), s.mat_entidade DESC, s.id_entidade ASC\n"
        f"LIMIT {limit + 1} OFFSET {offset}"
    )
    return sql, params


INFORMATION_SCHEMA_SQL = """
SELECT table_name, column_name, data_type
FROM `{project}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name IN ({tables})
ORDER BY table_name, ordinal_position
"""
