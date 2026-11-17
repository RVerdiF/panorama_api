"""Filtros obrigatórios e paginação recusados com 400 antes de criar job."""

from __future__ import annotations

import pytest

from panorama_api.repositories.bigquery import (
    BigQuerySettings,
    InvalidQueryRequest,
    PageRequest,
    QueryExecutor,
)

from conftest import FakeQueryClient

SHARE_OK = {"co_municipio": "3106200", "nu_ano_censo": 2024, "etapa": "fund_ai"}


def _executor(client: FakeQueryClient, settings: BigQuerySettings) -> QueryExecutor:
    return QueryExecutor(settings=settings, client=client)


CASES = [
    # (template, filtros, campo esperado)
    ("market_share", {}, "co_municipio"),
    ("market_share", {"co_municipio": "3106200"}, "nu_ano_censo"),
    ("market_share", {"co_municipio": "3106200", "nu_ano_censo": 2024}, "etapa"),
    ("market_share", {**SHARE_OK, "etapa": None}, "etapa"),
    ("market_share", {**SHARE_OK, "etapa": ""}, "etapa"),
    ("market_concentration", {"co_municipio": "3106200"}, "nu_ano_censo"),
    ("market", {"co_municipio": "3106200"}, "nu_ano_censo"),
    ("market", {"nu_ano_censo": 2024}, "co_municipio"),
    ("schools", {}, "co_municipio"),
    ("schools", {"co_municipio": "3106200", "no_entidade_prefix": "ab"}, "no_entidade_prefix"),
    ("school", {}, "co_entidade"),
    ("school_history", {}, "co_entidade"),
    ("school_indicators", {}, "co_entidade"),
    ("template_inexistente", {}, "endpoint"),
]


@pytest.mark.parametrize("template,filtros,campo", CASES)
def test_filtro_obrigatorio_ausente_gera_400_sem_job(
    template: str, filtros: dict[str, object], campo: str
) -> None:
    client = FakeQueryClient()
    executor = _executor(client, BigQuerySettings(project="p", dataset="d"))

    with pytest.raises(InvalidQueryRequest) as exc:
        executor.execute(template, filtros)

    assert exc.value.http_status == 400
    assert exc.value.code == "PARAMETRO_INVALIDO"
    assert exc.value.field == campo
    assert client.calls == [], "nenhum job pode ser criado quando a requisição é inválida"


INVALID_VALUES = [
    ("market_share", {**SHARE_OK, "co_municipio": "1' OR '1'='1"}),
    ("market_share", {**SHARE_OK, "co_municipio": "3206200"}),
    ("market_share", {**SHARE_OK, "co_municipio": "310620"}),
    ("market_share", {**SHARE_OK, "nu_ano_censo": 1999}),
    ("market_share", {**SHARE_OK, "nu_ano_censo": "dois mil"}),
    ("market_share", {**SHARE_OK, "etapa": "superior"}),
    ("market_share", {**SHARE_OK, "entidade_tipo": "rede"}),
    ("school", {"co_entidade": "1234"}),
    ("school", {"co_entidade": "ABCDEFGH"}),
    ("school_history", {"co_entidade": "31000000", "ano_inicio": 2025, "ano_fim": 2020}),
    ("school_history", {"co_entidade": "31000000", "ano_inicio": "x"}),
    ("schools", {"co_municipio": "3106200", "campo_desconhecido": "1"}),
]


@pytest.mark.parametrize("template,filtros", INVALID_VALUES)
def test_valor_invalido_gera_400_sem_job(
    template: str, filtros: dict[str, object]
) -> None:
    client = FakeQueryClient()
    executor = _executor(client, BigQuerySettings(project="p", dataset="d"))

    with pytest.raises(InvalidQueryRequest) as exc:
        executor.execute(template, filtros)

    assert exc.value.http_status == 400
    assert client.calls == []


PAGE_CASES = [
    # page_size acima do máximo do template (share = 200) ou global (500)
    ("market_share", SHARE_OK, PageRequest(page_size=201)),
    ("market_share", SHARE_OK, PageRequest(page_size=5000)),
    ("schools", {"co_municipio": "3106200"}, PageRequest(page_size=101)),
    # offset acima do limite global
    ("market_share", SHARE_OK, PageRequest(offset=1001)),
    # recurso não paginado recusando cursor/offset
    ("market", {"co_municipio": "3106200", "nu_ano_censo": 2024}, PageRequest(cursor="abc")),
    ("market", {"co_municipio": "3106200", "nu_ano_censo": 2024}, PageRequest(offset=10)),
    # cursor inválido
    ("schools", {"co_municipio": "3106200"}, PageRequest(cursor="não-é-base64")),
]


@pytest.mark.parametrize("template,filtros,page", PAGE_CASES)
def test_paginacao_invalida_gera_400_sem_job(
    template: str, filtros: dict[str, object], page: PageRequest
) -> None:
    client = FakeQueryClient()
    executor = _executor(client, BigQuerySettings(project="p", dataset="d"))

    with pytest.raises(InvalidQueryRequest) as exc:
        executor.execute(template, filtros, page)

    assert exc.value.http_status == 400
    assert client.calls == []


def test_page_size_acima_do_global_tambem_e_400() -> None:
    client = FakeQueryClient()
    settings = BigQuerySettings(project="p", dataset="d", page_size_max=500)
    executor = _executor(client, settings)

    with pytest.raises(InvalidQueryRequest) as exc:
        executor.execute("market_share", SHARE_OK, PageRequest(page_size=5000))

    assert "page_size" in exc.value.detail
    assert client.calls == []
