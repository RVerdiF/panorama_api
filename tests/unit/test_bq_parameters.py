"""Parâmetros tipados: validação de domínio antes de qualquer job."""

from __future__ import annotations

import pytest

from panorama_api.repositories.bigquery import ParamSpec, ParamType
from panorama_api.repositories.bigquery.errors import InvalidQueryRequest
from panorama_api.repositories.bigquery.parameters import (
    ANO_CENSO,
    CO_ENTIDADE,
    CO_MUNICIPIO,
    ENTIDADE_TIPO,
    ETAPA,
    PREFIXO_BUSCA,
)


@pytest.mark.parametrize(
    "spec,valor,esperado",
    [
        (CO_ENTIDADE, "31000000", "31000000"),
        (CO_MUNICIPIO, "3106200", "3106200"),
        (ANO_CENSO, 2024, 2024),
        (ANO_CENSO, "2024", 2024),
        (ETAPA, "fund_ai", "fund_ai"),
        (ENTIDADE_TIPO, "mantenedora", "mantenedora"),
        (PREFIXO_BUSCA, "  escola sacre  ", "ESCOLA SACRE"),
    ],
)
def test_normalizacao_valida(spec: ParamSpec, valor: object, esperado: object) -> None:
    assert spec.normalize(valor) == esperado


@pytest.mark.parametrize(
    "spec,valor",
    [
        (CO_ENTIDADE, "1234567"),
        (CO_ENTIDADE, "123456789"),
        (CO_ENTIDADE, "3100000a"),
        (CO_ENTIDADE, "1' OR '1'='1"),
        (CO_MUNICIPIO, "310620"),
        (CO_MUNICIPIO, "3206200"),
        (CO_MUNICIPIO, "3106200 OR 1=1"),
        (ANO_CENSO, 1999),
        (ANO_CENSO, 2101),
        (ANO_CENSO, 2024.5),
        (ANO_CENSO, True),
        (ETAPA, "superior"),
        (ETAPA, "FUND_AI"),
        (ENTIDADE_TIPO, "rede"),
        (PREFIXO_BUSCA, "ab"),
        (PREFIXO_BUSCA, "x" * 101),
    ],
)
def test_normalizacao_invalida_vira_400(spec: ParamSpec, valor: object) -> None:
    with pytest.raises(InvalidQueryRequest) as exc:
        spec.normalize(valor)
    assert exc.value.http_status == 400
    assert exc.value.field == spec.name


def test_tipos_espelham_schema_verificado() -> None:
    # B2: co_entidade/co_municipio são STRING e nu_ano_censo é INTEGER.
    assert CO_ENTIDADE.type is ParamType.STRING
    assert CO_MUNICIPIO.type is ParamType.STRING
    assert ANO_CENSO.type is ParamType.INT64


def test_nome_de_parametro_invalido_e_erro_de_programacao() -> None:
    with pytest.raises(ValueError):
        ParamSpec("co_municipio; DROP", ParamType.STRING)
