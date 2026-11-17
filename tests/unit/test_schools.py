"""`GET /v1/schools` — envelope, paginação, validação e NULL≠0."""

from __future__ import annotations

from tests.unit.conftest import school_row


def _envelope_keys(body: dict) -> set[str]:
    return set(body)


def test_busca_por_nome_devolve_envelope_completo(client, repository):
    repository.schools = [school_row()]

    body = client.get("/v1/schools", params={"q": "modelo"}).json()

    assert _envelope_keys(body) == {"data", "meta", "page"}
    meta = body["meta"]
    assert meta["contract"] == "serving-marts"
    assert meta["contract_version"] == "mvp-1"
    assert meta["ano_referencia"] == 2025
    assert meta["etapa"] == "bas"
    assert meta["universo"] == "escolas_mg"
    assert meta["fonte"] == {
        "orgao": "INEP",
        "base": "Censo Escolar",
        "tabela": "dim_escola",
    }
    assert meta["avisos"] == []
    assert body["data"][0]["co_entidade"] == "31000001"


def test_pagina_tem_has_more_e_nao_tem_total(client, repository):
    repository.schools = [school_row(co_entidade=f"3100000{i}") for i in range(3)]

    page = client.get("/v1/schools", params={"q": "modelo", "limit": 2}).json()["page"]

    assert set(page) == {"limit", "offset", "returned", "has_more"}
    assert page == {"limit": 2, "offset": 0, "returned": 2, "has_more": True}


def test_ultima_pagina_nao_tem_has_more(client, repository):
    repository.schools = [school_row()]

    page = client.get("/v1/schools", params={"q": "modelo"}).json()["page"]

    assert page["returned"] == 1
    assert page["has_more"] is False


def test_offset_repassa_para_a_consulta(client, repository):
    repository.schools = [school_row(co_entidade=f"3100000{i}") for i in range(5)]

    body = client.get(
        "/v1/schools", params={"q": "modelo", "limit": 2, "offset": 3}
    ).json()

    assert body["page"] == {"limit": 2, "offset": 3, "returned": 2, "has_more": False}
    assert [(name, kw["offset"]) for name, kw in repository.calls if name == "search_schools"] == [
        ("search_schools", 3)
    ]


def test_busca_sem_criterio_e_400(client, repository):
    response = client.get("/v1/schools", params={"limit": 5})

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "PARAMETRO_INVALIDO"
    assert body["instance"] == "/v1/schools"
    assert repository.methods_called() == ["get_table_columns"]


def test_co_entidade_invalida_e_422(client):
    response = client.get("/v1/schools", params={"co_entidade": "123"})

    assert response.status_code == 422
    assert response.json()["code"] == "PARAMETRO_INVALIDO"
    assert response.json()["errors"][0]["loc"] == ["query", "co_entidade"]


def test_co_municipio_fora_de_mg_e_422(client):
    response = client.get("/v1/schools", params={"co_municipio": "3550308"})

    assert response.status_code == 422
    assert response.json()["code"] == "PARAMETRO_INVALIDO"


def test_q_curto_e_422(client):
    assert client.get("/v1/schools", params={"q": "ab"}).status_code == 422


def test_limit_acima_do_maximo_e_422(client):
    response = client.get("/v1/schools", params={"q": "modelo", "limit": 101})

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["query", "limit"]


def test_offset_acima_do_teto_e_422(client):
    response = client.get("/v1/schools", params={"q": "modelo", "offset": 1001})

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["query", "offset"]


def test_parametro_desconhecido_e_400(client):
    response = client.get("/v1/schools", params={"q": "modelo", "order": "nome"})

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "PARAMETRO_INVALIDO"
    assert body["errors"][0]["loc"] == ["query", "order"]


def test_escola_inexistente_por_codigo_e_404(client, repository):
    response = client.get("/v1/schools", params={"co_entidade": "99999999"})

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NAO_ENCONTRADO"
    assert body["status"] == 404
    assert body["type"] == "https://api.panorama/erros/nao-encontrado"
    assert set(body) == {"type", "title", "status", "detail", "instance", "code", "errors"}


def test_busca_sem_resultado_e_lista_vazia_200(client):
    body = client.get("/v1/schools", params={"q": "inexistente"}).json()

    assert body["data"] == []
    assert body["page"]["has_more"] is False


def test_null_preservado_e_oferta_desconhecida(client, repository):
    repository.schools = [
        school_row(is_oferta_desconhecida=True, of_med=None, of_esp=0, n_anos_serie=None)
    ]

    school = client.get("/v1/schools", params={"q": "modelo"}).json()["data"][0]

    assert school["oferta"]["med"] is None
    assert school["oferta"]["esp"] is False
    assert school["is_oferta_desconhecida"] is True
    assert school["n_anos_serie"] is None
    # métrica ausente não pode virar 0
    assert school["nu_ano_ultimo_registro"] == 2025


def test_apenas_ativas_filtra_na_consulta(client, repository):
    repository.schools = [school_row()]

    client.get("/v1/schools", params={"q": "modelo", "apenas_ativas": "true"})

    call = next(kw for name, kw in repository.calls if name == "search_schools")
    assert call["apenas_ativas"] is True
