"""Redirect 301 de `/app/mercados/{co}/escolas` para a `section#escolas` (D1-E3).

A rota antiga do ranking (card NAV-3) virou redirect permanente para a
própria página do mercado com o recorte na query e `#escolas` no `Location`
(decisão D4). Cobre, sobre o app de verdade (`TestClient` + repositório fake,
nenhuma rede/BigQuery):

* `301` com `ano`+`etapa`+`offset` preservados e `#escolas` no `Location`;
* `ano` passa cru (quem valida é o destino); `offset=0` some (1ª página
  canônica, como em `web/paginacao.py`);
* parâmetro inválido (`offset=5000`, `etapa=xyz`) → `422`, nunca redirect;
* nenhum link interno da página do mercado aponta para `/escolas` (sem cadeia
  de redirect interno).
"""

from __future__ import annotations

from html import unescape as desescapar

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.main import create_app
from tests.unit.conftest import (
    FakeRepository,
    market_row,
    municipio_row,
    share_row,
)

MUNICIPIO = "3106200"
MERCADO = f"/app/mercados/{MUNICIPIO}"
ESCOLAS = f"{MERCADO}/escolas"
ANOS = (2021, 2022, 2023, 2024, 2025)


def _settings() -> Settings:
    return Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        max_bytes_billed=256 * 1024 * 1024,
        validate_schema_on_startup=False,
        contract_version="mvp-1",
        app_anos_disponiveis=",".join(str(ano) for ano in ANOS),
    )


@pytest.fixture
def mercado_repo() -> FakeRepository:
    return FakeRepository(
        municipios=[municipio_row()],
        markets=[
            market_row(nu_ano_censo=ano, etapa=etapa)
            for ano in ANOS
            for etapa in ("bas", "creche", "med")
        ],
        share=[
            share_row(
                nu_ano_censo=2025,
                etapa="bas",
                id_entidade=f"310000bas{indice:02d}",
            )
            for indice in range(60)
        ],
    )


def _client(repository: FakeRepository) -> TestClient:
    return TestClient(
        create_app(settings=_settings(), repository=repository),
    )


def _redirect(resposta) -> str:
    assert resposta.status_code == 301, resposta.text[:600]
    return resposta.headers["location"]


# -- 301 preserva o recorte -------------------------------------------------


def test_escolas_com_recorte_completo_redireciona_para_a_ancora(mercado_repo):
    """Critério 2 da V3-M: 301 com ano+etapa+offset e `#escolas`."""
    resposta = _client(mercado_repo).get(
        ESCOLAS,
        params={"ano": "2024", "etapa": "med", "offset": "20"},
        follow_redirects=False,
    )

    assert (
        _redirect(resposta)
        == "/app/mercados/3106200?ano=2024&etapa=med&offset=20#escolas"
    )
    assert mercado_repo.calls == []


def test_escolas_sem_params_redireciona_para_a_pagina(mercado_repo):
    resposta = _client(mercado_repo).get(ESCOLAS, follow_redirects=False)

    assert _redirect(resposta) == "/app/mercados/3106200#escolas"


def test_escolas_offset_zero_e_canonico_sem_offset(mercado_repo):
    """`offset=0` é a 1ª página: o `Location` omite, como `paginacao.url`."""
    resposta = _client(mercado_repo).get(
        ESCOLAS, params={"offset": "0"}, follow_redirects=False
    )

    assert _redirect(resposta) == "/app/mercados/3106200#escolas"


def test_escolas_ano_passa_cru_quem_valida_e_o_destino(mercado_repo):
    """Ano fora do contrato passa: o destino responde o `404` com seletor."""
    resposta = _client(mercado_repo).get(
        ESCOLAS, params={"ano": "2019"}, follow_redirects=False
    )

    assert _redirect(resposta) == "/app/mercados/3106200?ano=2019#escolas"

    destino = _client(mercado_repo).get(
        "/app/mercados/3106200", params={"ano": "2019"}
    )
    assert destino.status_code == 404


# -- parâmetro inválido nunca vira redirect ----------------------------------


@pytest.mark.parametrize("params", [{"offset": "5000"}, {"offset": "-1"}])
def test_escolas_offset_fora_da_faixa_responde_422(mercado_repo, params):
    resposta = _client(mercado_repo).get(ESCOLAS, params=params)

    assert resposta.status_code == 422
    assert "location" not in resposta.headers
    assert mercado_repo.calls == []


def test_escolas_etapa_invalida_responde_422(mercado_repo):
    resposta = _client(mercado_repo).get(ESCOLAS, params={"etapa": "xyz"})

    assert resposta.status_code == 422
    assert resposta.headers["content-type"].startswith("text/html")
    assert "location" not in resposta.headers
    assert mercado_repo.calls == []


# -- sem cadeia de redirect interna ------------------------------------------


def test_nenhum_link_interno_da_pagina_aponta_para_escolas(mercado_repo):
    """A página nova linka `#escolas` direto; nada passa pelo 301."""
    cliente = _client(mercado_repo)

    for params in ({}, {"offset": "10"}, {"ano": "2024", "etapa": "med"}):
        html = desescapar(cliente.get(MERCADO, params=params).text)

        assert "/mercados/3106200/escolas" not in html
