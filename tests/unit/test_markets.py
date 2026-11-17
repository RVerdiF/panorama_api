"""`GET /v1/markets/{co_municipio}`."""

from __future__ import annotations

from panorama_api.contract import ETAPAS
from tests.unit.conftest import concentracao_row, market_row, municipio_row


def test_mercado_com_as_nove_etapas(client, repository):
    repository.municipios = [municipio_row()]
    repository.markets = [market_row(etapa=etapa) for etapa in ETAPAS]
    repository.concentracao = [concentracao_row(etapa="bas")]

    response = client.get("/v1/markets/3106200", params={"ano": 2025})

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["no_municipio"] == "BELO HORIZONTE"
    assert [item["etapa"] for item in body["data"]["items"]] == sorted(ETAPAS)
    assert body["meta"]["ano_referencia"] == 2025
    assert body["meta"]["etapa"] is None  # resposta cobre as 9 etapas
    assert body["meta"]["fonte"]["tabela"] == "mart_mercado"
    # cobertura é por etapa: não há como agregar 9 linhas sem inventar
    assert body["meta"]["cobertura"] is None
    # só a etapa "bas" tem concentração
    assert body["data"]["items"][0]["concentracao"][0]["c4_pct"] == 60.0
    assert body["data"]["items"][1]["concentracao"] == []


def test_cobertura_por_linha_e_no_meta_quando_etapa_unica(client, repository):
    repository.municipios = [municipio_row()]
    repository.markets = [market_row(etapa="med")]
    repository.concentracao = [concentracao_row(etapa="med")]

    body = client.get(
        "/v1/markets/3106200", params={"ano": 2025, "etapa": "med"}
    ).json()

    item = body["data"]["items"][0]
    assert item["cobertura"] == {
        "n_escolas_ativas": 100,
        "n_escolas_com_linha_matricula": 99,
        "n_escolas_mat_linha_missing": 1,
        "n_escolas_mat_valor_missing": 2,
        "n_escolas_mat_missing": 3,
    }
    assert body["meta"]["cobertura"] == item["cobertura"]
    assert body["meta"]["etapa"] == "med"


def test_baseline_ausente_fica_null(client, repository):
    repository.municipios = [municipio_row()]
    repository.markets = [market_row(etapa="bas", n_escolas_sairam=None)]

    item = client.get("/v1/markets/3106200", params={"ano": 2025}).json()["data"][
        "items"
    ][0]

    assert item["n_escolas_sairam"] is None
    assert item["n_escolas_entraram"] is None


def test_municipio_inexistente_e_404(client, repository):
    response = client.get("/v1/markets/3106200", params={"ano": 2025})

    assert response.status_code == 404
    assert response.json()["code"] == "NAO_ENCONTRADO"


def test_ano_sem_dado_e_404_ano_fora_do_contrato(client, repository):
    repository.municipios = [municipio_row()]
    repository.markets = [market_row(nu_ano_censo=2025)]

    response = client.get("/v1/markets/3106200", params={"ano": 2020})

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "ANO_FORA_DO_CONTRATO"
    assert body["type"] == "https://api.panorama/erros/ano-fora-do-contrato"


def test_ano_obrigatorio(client, repository):
    response = client.get("/v1/markets/3106200")

    assert response.status_code == 422
    assert response.json()["code"] == "PARAMETRO_INVALIDO"
    assert response.json()["errors"][0]["loc"] == ["query", "ano"]


def test_ano_fora_da_faixa_e_422(client):
    response = client.get("/v1/markets/3106200", params={"ano": 2101})

    assert response.status_code == 422


def test_etapa_invalida_e_422(client):
    response = client.get("/v1/markets/3106200", params={"ano": 2025, "etapa": "xyz"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "PARAMETRO_INVALIDO"
    assert body["errors"][0]["loc"] == ["query", "etapa"]


def test_co_municipio_sem_prefixo_mg_e_422(client):
    response = client.get("/v1/markets/3550308", params={"ano": 2025})

    assert response.status_code == 422
