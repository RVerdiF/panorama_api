"""Validadores de entrada (422 antes de qualquer consulta)."""

from __future__ import annotations

import pytest

from panorama_api.contract import ETAPAS
from panorama_api.core import validation
from panorama_api.core.errors import ErrorCode, ProblemError


def _falha(fn, *args, **kwargs) -> ProblemError:
    with pytest.raises(ProblemError) as excinfo:
        fn(*args, **kwargs)
    return excinfo.value


def test_co_entidade_exige_oito_digitos():
    assert validation.co_entidade("31000001") == "31000001"
    erro = _falha(validation.co_entidade, "3100000")
    assert erro.status == 422
    assert erro.code is ErrorCode.PARAMETRO_INVALIDO
    _falha(validation.co_entidade, "3100000a")


def test_co_municipio_exige_prefixo_de_mg():
    assert validation.co_municipio("3106200") == "3106200"
    _falha(validation.co_municipio, "3550308")
    _falha(validation.co_municipio, "310620")


@pytest.mark.parametrize("etapa", ETAPAS)
def test_etapa_aceita_as_nove(etapa):
    assert validation.etapa(etapa) == etapa


def test_etapa_rejeita_fora_do_dominio_e_case():
    _falha(validation.etapa, "superior")
    _falha(validation.etapa, "BAS")
    assert validation.etapa(None) is None
    _falha(validation.etapa, None, required=True)


def test_entidade_tipo_default_e_dominio():
    assert validation.entidade_tipo(None) == "escola"
    assert validation.entidade_tipo("mantenedora") == "mantenedora"
    _falha(validation.entidade_tipo, "rede")


def test_limites_de_paginacao():
    assert validation.limit(None, default=20, maximum=100) == 20
    assert validation.limit(100, default=20, maximum=100) == 100
    _falha(validation.limit, 101, default=20, maximum=100)
    _falha(validation.limit, 0, default=20, maximum=100)


def test_offset_teto_de_mil():
    assert validation.offset(None) == 0
    assert validation.offset(1000) == 1000
    _falha(validation.offset, 1001)
    _falha(validation.offset, -1)


def test_ano_faixa():
    assert validation.ano(2025) == 2025
    assert validation.ano(2000) == 2000
    assert validation.ano(2100) == 2100
    _falha(validation.ano, 1999)
    _falha(validation.ano, 2101)
    _falha(validation.ano, None, required=True)


def test_termo_de_busca_entre_3_e_100():
    assert validation.search_term("  abc  ") == "abc"
    _falha(validation.search_term, "ab")
    _falha(validation.search_term, "a" * 101)
