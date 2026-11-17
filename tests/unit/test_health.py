"""`GET /health` — liveness sem BigQuery."""

from __future__ import annotations


def test_health_responde_sem_consultar_dados(client, repository):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "contract": "serving-marts/mvp-1",
    }
    # só a validação de schema do startup tocou o repositório
    assert repository.methods_called() == ["get_table_columns"]


def test_health_nao_usa_envelope(client):
    body = client.get("/health").json()

    assert "data" not in body
    assert "meta" not in body
