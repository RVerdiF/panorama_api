"""`GET /v1/schools/{co_entidade}/history`."""

from __future__ import annotations

from panorama_api.core.errors import UpstreamUnavailable
from tests.unit.conftest import history_row


def test_serie_ordenada_com_cabecalho_do_ano_mais_recente(client, repository):
    repository.history = [
        history_row(nu_ano_censo=2024, no_entidade="NOME ANTIGO"),
        history_row(nu_ano_censo=2025, no_entidade="NOME NOVO"),
    ]

    response = client.get("/v1/schools/31000001/history")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["no_entidade"] == "NOME NOVO"
    assert body["data"]["co_entidade"] == "31000001"
    assert [item["nu_ano_censo"] for item in body["data"]["items"]] == [2024, 2025]
    assert body["meta"]["ano_referencia"] == 2025
    assert body["meta"]["fonte"]["tabela"] == "mart_escola"
    assert body["meta"]["universo"] == "escolas_mg"
    # série curta: sem paginação
    assert "page" not in body


def test_null_preservado_na_serie(client, repository):
    repository.history = [
        history_row(
            qt_mat_bas=None,
            is_qt_mat_bas_missing=True,
            qt_mat_med=None,
            is_qt_mat_med_missing=True,
            tx_aprov_fund_t=None,
            is_tx_aprov_fund_t_missing=True,
            is_oferta_desconhecida=True,
            of_med=None,
            latitude=None,
            needs_review=None,
        )
    ]

    item = client.get("/v1/schools/31000001/history").json()["data"]["items"][0]

    assert item["qt_mat_bas"] is None
    assert item["is_qt_mat_bas_missing"] is True
    assert item["qt_mat_med"] is None
    assert item["is_qt_mat_med_missing"] is True
    assert item["tx_aprov_fund_t"] is None
    assert item["is_tx_aprov_fund_t_missing"] is True
    assert item["oferta"]["med"] is None
    assert item["latitude"] is None
    assert item["needs_review"] is None


def test_aviso_de_metodologia_incomparavel(client, repository):
    repository.history = [
        history_row(nu_ano_censo=2025, n_etapas_metodologia_incomparavel=2)
    ]

    body = client.get("/v1/schools/31000001/history").json()

    assert "METODOLOGIA_INCOMPARAVEL_2025" in body["meta"]["avisos"]


def test_filtro_de_anos(client, repository):
    repository.history = [
        history_row(nu_ano_censo=2023),
        history_row(nu_ano_censo=2024),
        history_row(nu_ano_censo=2025),
    ]

    body = client.get(
        "/v1/schools/31000001/history", params={"ano_inicio": 2024, "ano_fim": 2025}
    ).json()

    assert [item["nu_ano_censo"] for item in body["data"]["items"]] == [2024, 2025]


def test_sem_linhas_e_404(client, repository):
    response = client.get("/v1/schools/99999999/history")

    assert response.status_code == 404
    assert response.json()["code"] == "NAO_ENCONTRADO"


def test_co_entidade_invalida_e_422(client):
    response = client.get("/v1/schools/abc/history")

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["path", "co_entidade"]


def test_intervalo_invertido_e_422(client):
    response = client.get(
        "/v1/schools/31000001/history", params={"ano_inicio": 2025, "ano_fim": 2020}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "PARAMETRO_INVALIDO"
    assert response.json()["errors"][0]["loc"] == ["query", "ano_inicio"]


def test_fonte_indisponivel_e_503(client, repository):
    repository.errors["get_school_history"] = UpstreamUnavailable("timeout")

    response = client.get("/v1/schools/31000001/history")

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "FONTE_INDISPONIVEL"
    assert body["type"] == "https://api.panorama/erros/fonte-indisponivel"
    assert "timeout" not in body["detail"]
