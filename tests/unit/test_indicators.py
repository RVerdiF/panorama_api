"""`GET /v1/schools/{co_entidade}/indicators`."""

from __future__ import annotations

from tests.unit.conftest import competidor_row, indicator_row, school_row


def test_indicadores_com_competicao(client, repository):
    repository.indicators = [indicator_row()]
    repository.competidores = [competidor_row()]

    response = client.get("/v1/schools/31000001/indicators")

    assert response.status_code == 200
    body = response.json()
    item = body["data"]["items"][0]
    assert item["retencao_liquida_proxy_pct"] == 98.5
    assert item["competicao"]["rank_mat_bas_municipio"] == 3
    assert item["competicao"]["lider_no_entidade"] == "ESCOLA LIDER"
    assert body["meta"]["universo"] == "privadas_ativas_mg"
    assert body["meta"]["fonte"]["tabela"] == "mart_escola_indicadores"
    assert body["meta"]["etapa"] == "bas"
    assert "retencao_liquida_proxy_pct" in body["meta"]["definicoes"]
    assert "evasão" in body["meta"]["definicoes"]["retencao_liquida_proxy_pct"]


def test_competicao_ausente_vira_null(client, repository):
    repository.indicators = [indicator_row()]

    item = client.get("/v1/schools/31000001/indicators").json()["data"]["items"][0]

    assert item["competicao"] is None


def test_avisos_de_porte_e_metodologia(client, repository):
    repository.indicators = [
        indicator_row(is_abaixo_porte=True, n_etapas_metodologia_incomparavel=1)
    ]
    repository.competidores = [competidor_row()]

    avisos = client.get("/v1/schools/31000001/indicators").json()["meta"]["avisos"]

    assert "IS_ABAIXO_PORTE" in avisos
    assert "METODOLOGIA_INCOMPARAVEL_2025" in avisos


def test_null_preservado_nos_indicadores(client, repository):
    repository.indicators = [
        indicator_row(
            share_total_pct=None,
            crescimento_yoy_pct=None,
            is_qt_mat_bas_missing=True,
            qt_mat_bas=None,
        )
    ]
    repository.competidores = [competidor_row()]

    item = client.get("/v1/schools/31000001/indicators").json()["data"]["items"][0]

    assert item["share_total_pct"] is None
    assert item["crescimento_yoy_pct"] is None
    assert item["qt_mat_bas"] is None
    assert item["is_qt_mat_bas_missing"] is True


def test_escola_fora_do_universo_e_404(client, repository):
    repository.schools = [school_row(tp_dependencia="3")]  # pública, sem indicadores

    response = client.get("/v1/schools/31000001/indicators")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NAO_ENCONTRADO"
    assert "universo" in body["detail"]


def test_escola_inexistente_e_404(client, repository):
    response = client.get("/v1/schools/99999999/indicators")

    assert response.status_code == 404
    assert response.json()["code"] == "NAO_ENCONTRADO"


def test_ano_sem_dado_mas_escola_tem_serie_e_404_ano_fora_do_contrato(
    client, repository
):
    repository.schools = [school_row()]
    repository.indicators = [indicator_row(nu_ano_censo=2025)]

    response = client.get("/v1/schools/31000001/indicators", params={"ano": 2020})

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "ANO_FORA_DO_CONTRATO"
    assert "2025" in body["detail"]


def test_ano_especifico_filtra(client, repository):
    repository.indicators = [
        indicator_row(nu_ano_censo=2024),
        indicator_row(nu_ano_censo=2025),
    ]
    repository.competidores = [competidor_row(nu_ano_censo=2025)]

    body = client.get(
        "/v1/schools/31000001/indicators", params={"ano": 2025}
    ).json()

    assert [item["nu_ano_censo"] for item in body["data"]["items"]] == [2025]


def test_ano_fora_da_faixa_e_422(client):
    response = client.get("/v1/schools/31000001/indicators", params={"ano": 1999})

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["query", "ano"]
