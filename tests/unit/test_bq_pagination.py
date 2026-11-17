"""Paginação: LIMIT n+1, keyset por co_escola, offset limitado, sem COUNT."""

from __future__ import annotations

import pytest

from panorama_api.repositories.bigquery import (
    BigQuerySettings,
    InvalidQueryRequest,
    KeysetColumn,
    PageRequest,
    PaginationMode,
    QueryExecutor,
)
from panorama_api.repositories.bigquery.pagination import (
    decode_cursor,
    encode_cursor,
    plan_page,
    split_page,
)
from panorama_api.repositories.bigquery.templates import TEMPLATES

from conftest import FakeQueryClient

MUNICIPIO = {"co_municipio": "3106200"}
SHARE = {"co_municipio": "3106200", "nu_ano_censo": 2024, "etapa": "fund_ai"}


def _executor(rows=()) -> tuple[QueryExecutor, FakeQueryClient]:
    client = FakeQueryClient(rows=rows)
    executor = QueryExecutor(
        settings=BigQuerySettings(project="p", dataset="d"), client=client
    )
    return executor, client


def _school_rows(total: int) -> list[dict[str, object]]:
    return [
        {"no_entidade": f"ESCOLA {i:03d}", "co_entidade": f"3100{i:04d}"}
        for i in range(total)
    ]


def test_page_size_padrao_e_50_e_limite_pede_51() -> None:
    executor, client = _executor()

    executor.execute("schools", MUNICIPIO)

    assert client.last_params["page_limit"] == 51
    assert "LIMIT @page_limit" in client.last_sql
    assert "COUNT(" not in client.last_sql.upper()


def test_page_size_explicito() -> None:
    executor, client = _executor()

    result = executor.execute("schools", MUNICIPIO, PageRequest(page_size=10))

    assert client.last_params["page_limit"] == 11
    assert result.page is not None and result.page.limit == 10


def test_limite_global_de_page_size_e_400() -> None:
    with pytest.raises(InvalidQueryRequest):
        plan_page(
            mode=PaginationMode.KEYSET,
            request=PageRequest(page_size=5000),
            page_size_default=50,
            page_size_max=500,
            offset_max=1000,
            row_cap=1000,
            keyset_columns=TEMPLATES["schools"].keyset_columns,
        )


def test_page_size_default_respeita_teto_do_template() -> None:
    plan = plan_page(
        mode=PaginationMode.OFFSET,
        request=PageRequest(),
        page_size_default=50,
        page_size_max=20,
        offset_max=1000,
        row_cap=1000,
    )
    assert plan.page_size == 20


def test_has_more_quando_vem_linha_extra() -> None:
    executor, _client = _executor(rows=_school_rows(51))

    result = executor.execute("schools", MUNICIPIO, PageRequest(page_size=50))

    assert result.page is not None
    assert result.page.returned == 50
    assert result.page.has_more is True
    assert len(result.rows) == 50
    # cursor aponta para a última linha devolvida
    assert result.page.next_cursor is not None
    assert decode_cursor(result.page.next_cursor, TEMPLATES["schools"].keyset_columns) == (
        "ESCOLA 049",
        "31000049",
    )


def test_sem_has_more_quando_cabe_na_pagina() -> None:
    executor, _client = _executor(rows=_school_rows(50))

    result = executor.execute("schools", MUNICIPIO, PageRequest(page_size=50))

    assert result.page is not None
    assert result.page.has_more is False
    assert result.page.next_cursor is None


def test_keyset_vira_predicado_e_parametros() -> None:
    executor, client = _executor()
    cursor = encode_cursor(["ESCOLA 049", "31000049"])

    executor.execute("schools", MUNICIPIO, PageRequest(page_size=50, cursor=cursor))

    sql = client.last_sql
    assert "no_entidade > @cursor_0" in sql
    assert "co_entidade > @cursor_1" in sql
    assert "ORDER BY no_entidade ASC NULLS LAST, co_entidade ASC" in sql
    assert client.last_params["cursor_0"] == "ESCOLA 049"
    assert client.last_params["cursor_1"] == "31000049"


def test_keyset_com_nome_nulo_continua_dentro_dos_nulos() -> None:
    columns = TEMPLATES["schools"].keyset_columns
    cursor = encode_cursor([None, "31000049"])

    assert decode_cursor(cursor, columns) == (None, "31000049")

    executor, client = _executor()
    executor.execute("schools", MUNICIPIO, PageRequest(cursor=cursor))
    assert client.last_params["cursor_0"] is None


def test_offset_pagination_usa_limit_e_offset() -> None:
    executor, client = _executor()

    result = executor.execute("market_share", SHARE, PageRequest(page_size=50, offset=150))

    assert "LIMIT @page_limit OFFSET @page_offset" in client.last_sql
    assert client.last_params["page_limit"] == 51
    assert client.last_params["page_offset"] == 150
    assert result.page is not None
    assert result.page.offset == 150
    assert result.page.next_cursor is None


def test_offset_acima_do_maximo_e_400() -> None:
    with pytest.raises(InvalidQueryRequest):
        plan_page(
            mode=PaginationMode.OFFSET,
            request=PageRequest(offset=1001),
            page_size_default=50,
            page_size_max=200,
            offset_max=1000,
            row_cap=1000,
        )


def test_template_nao_paginado_usa_row_cap() -> None:
    executor, client = _executor()

    result = executor.execute("market", {"co_municipio": "3106200", "nu_ano_censo": 2024})

    assert client.last_params["row_cap"] == 1000
    assert result.page is None


def test_school_individual_limita_a_uma_linha() -> None:
    executor, client = _executor()

    executor.execute("school", {"co_entidade": "31000000"})

    assert client.last_params["row_cap"] == 1


def test_split_page_sem_paginacao_devolve_tudo() -> None:
    plan = plan_page(
        mode=PaginationMode.NONE,
        request=PageRequest(),
        page_size_default=50,
        page_size_max=500,
        offset_max=1000,
        row_cap=1000,
    )
    rows = [{"a": 1}, {"a": 2}]
    items, page = split_page(mode=PaginationMode.NONE, plan=plan, rows=rows)
    assert items == rows
    assert page is None


def test_keyset_exige_chave_no_plano() -> None:
    with pytest.raises(InvalidQueryRequest):
        plan_page(
            mode=PaginationMode.KEYSET,
            request=PageRequest(),
            page_size_default=50,
            page_size_max=500,
            offset_max=1000,
            row_cap=1000,
            keyset_columns=(),
        )


def test_cursor_de_aridade_errada_e_400() -> None:
    with pytest.raises(InvalidQueryRequest):
        decode_cursor(
            encode_cursor(["apenas-um"]),
            (KeysetColumn("no_entidade", nullable=True), KeysetColumn("co_entidade")),
        )


#: Strings que ``str.isdigit()`` aceita mas ``int()`` recusa (ou que não são
#: decimais ASCII). Nenhuma pode escapar como ``ValueError``/500.
NAO_DECIMAIS = ["²", "³", "１２", "٣", "1_000", "1e3", "0x10", "1.0", "--1", "-"]


@pytest.mark.parametrize("valor", NAO_DECIMAIS)
def test_page_size_nao_decimal_nunca_escapa_como_valueerror(valor: str) -> None:
    with pytest.raises(InvalidQueryRequest):
        plan_page(
            mode=PaginationMode.OFFSET,
            request=PageRequest(page_size=valor),
            page_size_default=50,
            page_size_max=200,
            offset_max=1000,
            row_cap=1000,
        )


@pytest.mark.parametrize("valor", NAO_DECIMAIS)
def test_offset_nao_decimal_nunca_escapa_como_valueerror(valor: str) -> None:
    with pytest.raises(InvalidQueryRequest):
        plan_page(
            mode=PaginationMode.OFFSET,
            request=PageRequest(offset=valor),
            page_size_default=50,
            page_size_max=200,
            offset_max=1000,
            row_cap=1000,
        )
