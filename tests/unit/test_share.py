"""`GET /v1/markets/{co_municipio}/share`."""

from __future__ import annotations

from tests.unit.conftest import market_row, municipio_row, share_row


def test_share_por_escola_com_denominadores(client, repository):
    repository.municipios = [municipio_row()]
    repository.markets = [market_row(etapa="bas")]
    repository.share = [
        share_row(id_entidade="31000001", mat_entidade=120.0),
        share_row(id_entidade="31000002", mat_entidade=80.0, no_entidade="ESCOLA B"),
    ]

    response = client.get(
        "/v1/markets/3106200/share", params={"ano": 2025, "etapa": "bas"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["etapa"] == "bas"
    assert body["meta"]["universo"] == "escolas_ativas_mg"
    assert body["meta"]["fonte"]["tabela"] == "mart_market_share"
    assert body["meta"]["cobertura"] == {
        "n_escolas_privadas": 30,
        "n_escolas_ativas": 100,
    }
    assert body["data"]["entidade_tipo"] == "escola"
    assert body["data"]["mercado"] == {
        "n_escolas_privadas": 30,
        "n_escolas_ativas": 100,
        "qt_mat_privada": 15000.0,
        "qt_mat_total": 50000.0,
    }
    assert body["page"] == {"limit": 50, "offset": 0, "returned": 2, "has_more": False}


def test_share_mantenedora_usa_no_grupo(client, repository):
    repository.municipios = [municipio_row()]
    repository.markets = [market_row(etapa="bas")]
    repository.share = [
        share_row(
            entidade_tipo="mantenedora",
            id_entidade="00012345",
            no_entidade=None,
            no_grupo="GRUPO MODELO",
            n_unidades=4,
        )
    ]

    item = client.get(
        "/v1/markets/3106200/share",
        params={"ano": 2025, "etapa": "bas", "entidade_tipo": "mantenedora"},
    ).json()["data"]["items"][0]

    assert item["no_entidade"] == "GRUPO MODELO"
    assert item["n_unidades"] == 4


def test_share_escola_tem_n_unidades_null(client, repository):
    repository.municipios = [municipio_row()]
    repository.markets = [market_row(etapa="bas")]
    repository.share = [share_row(n_unidades=None)]

    item = client.get(
        "/v1/markets/3106200/share", params={"ano": 2025, "etapa": "bas"}
    ).json()["data"]["items"][0]

    assert item["n_unidades"] is None


def test_mercado_sem_linhas_de_share_e_200_com_lista_vazia(client, repository):
    repository.municipios = [municipio_row()]
    repository.markets = [market_row(etapa="bas", qt_mat_privada=None, qt_mat_total=None)]

    response = client.get(
        "/v1/markets/3106200/share", params={"ano": 2025, "etapa": "bas"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"] == []
    # denominadores ainda vêm do mart_mercado; ausência vira null, não zero
    assert body["data"]["mercado"]["qt_mat_privada"] is None
    assert body["data"]["mercado"]["n_escolas_privadas"] == 30
    assert body["page"]["returned"] == 0


def test_mercado_inexistente_e_404_ano_fora_do_contrato(client, repository):
    repository.municipios = [municipio_row()]

    response = client.get(
        "/v1/markets/3106200/share", params={"ano": 2025, "etapa": "bas"}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "ANO_FORA_DO_CONTRATO"


def test_municipio_inexistente_e_404(client, repository):
    response = client.get(
        "/v1/markets/3106200/share", params={"ano": 2025, "etapa": "bas"}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NAO_ENCONTRADO"
    assert "get_market_share" not in repository.methods_called()


def test_paginacao_limite_maximo(client, repository):
    repository.municipios = [municipio_row()]
    repository.markets = [market_row(etapa="bas")]
    repository.share = [share_row(id_entidade=f"3100000{i}") for i in range(3)]

    body = client.get(
        "/v1/markets/3106200/share",
        params={"ano": 2025, "etapa": "bas", "limit": 2},
    ).json()

    assert body["page"] == {"limit": 2, "offset": 0, "returned": 2, "has_more": True}

    response = client.get(
        "/v1/markets/3106200/share",
        params={"ano": 2025, "etapa": "bas", "limit": 201},
    )
    assert response.status_code == 422


def test_etapa_obrigatoria(client, repository):
    response = client.get("/v1/markets/3106200/share", params={"ano": 2025})

    assert response.status_code == 422
    assert response.json()["code"] == "PARAMETRO_INVALIDO"
    assert response.json()["errors"][0]["loc"] == ["query", "etapa"]


def test_ano_obrigatorio(client, repository):
    response = client.get("/v1/markets/3106200/share", params={"etapa": "bas"})

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["query", "ano"]


def test_etapa_fora_do_dominio_e_422(client):
    response = client.get(
        "/v1/markets/3106200/share", params={"ano": 2025, "etapa": "superior"}
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["query", "etapa"]


def test_entidade_tipo_invalida_e_422(client):
    response = client.get(
        "/v1/markets/3106200/share",
        params={"ano": 2025, "etapa": "bas", "entidade_tipo": "ong"},
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["query", "entidade_tipo"]
