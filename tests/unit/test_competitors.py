"""`GET /v1/schools/{co_entidade}/competitors` — comparação MUNICIPAL.

Fonte única: `mart_competidores` (grão `co_entidade × nu_ano_censo`). O endpoint
compara a escola com as privadas ativas do mesmo município/ano; não há lista
nominal de concorrentes nem filtro geográfico além de `co_municipio`.
"""

from __future__ import annotations

from panorama_api.core.errors import UpstreamUnavailable
from panorama_api.services.schools import DESCRICAO_COMPETIDORES
from tests.unit.conftest import competidor_row, school_row

URL = "/v1/schools/31000001/competitors"


def _campos_esperados() -> set[str]:
    """Colunas de `mart_competidores` expostas (as mesmas da mart, sem id extra)."""
    return {
        "nu_ano_censo",
        "no_entidade",
        "co_municipio",
        "qt_mat_bas",
        "rank_mat_bas_municipio",
        "n_concorrentes_privados_municipio",
        "n_concorrentes_com_matricula_bas",
        "n_concorrentes_creche_xself",
        "n_concorrentes_pre_xself",
        "n_concorrentes_fund_ai_xself",
        "n_concorrentes_fund_af_xself",
        "n_concorrentes_med_xself",
        "lider_no_entidade",
        "lider_qt_mat_bas",
        "gap_mat_bas_para_lider",
    }


def test_comparacao_municipal_no_ano_mais_recente(client, repository):
    repository.competidores = [competidor_row()]

    response = client.get(URL)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "meta"}
    assert body["data"]["co_entidade"] == "31000001"
    assert body["data"]["co_municipio"] == "3106200"
    meta = body["meta"]
    assert meta["contract"] == "serving-marts"
    assert meta["contract_version"] == "mvp-1"
    assert meta["ano_referencia"] == 2025
    assert meta["etapa"] == "bas"
    assert meta["universo"] == "privadas_ativas_mg"
    assert meta["fonte"] == {
        "orgao": "INEP",
        "base": "Censo Escolar",
        "tabela": "mart_competidores",
    }
    assert meta["definicoes"] == {"competidores": DESCRICAO_COMPETIDORES}


def test_descricao_obrigatoria_e_municipal(client):
    """Descrição obrigatória do card e ausência de termos de geografia livre."""
    schema = client.get("/openapi.json").json()
    operacao = schema["paths"]["/v1/schools/{co_entidade}/competitors"]["get"]
    texto = f"{operacao['summary']} {operacao['description']}"

    assert DESCRICAO_COMPETIDORES == (
        "Escolas privadas ativas no mesmo município e ano censitário (MG)"
    )
    assert operacao["summary"] == DESCRICAO_COMPETIDORES
    assert DESCRICAO_COMPETIDORES in texto
    for proibido in ("próxim", "proxim", "região", "regiao", "raio", "distância", "distancia"):
        assert proibido not in texto.lower()


def test_schema_openapi_expoe_so_campos_da_mart(client):
    schema = client.get("/openapi.json").json()
    props = schema["components"]["schemas"]["CompetitorItem"]["properties"]

    assert set(props) == _campos_esperados()
    assert schema["paths"]["/v1/schools/{co_entidade}/competitors"]["get"]["summary"] == (
        DESCRICAO_COMPETIDORES
    )


def test_serie_ordenada_por_ano_com_cabecalho_do_mais_recente(client, repository):
    repository.competidores = [
        competidor_row(nu_ano_censo=2024, no_entidade="NOME ANTIGO", rank_mat_bas_municipio=5),
        competidor_row(nu_ano_censo=2025, no_entidade="NOME NOVO", rank_mat_bas_municipio=2),
    ]

    body = client.get(URL).json()

    assert body["data"]["no_entidade"] == "NOME NOVO"
    assert [item["nu_ano_censo"] for item in body["data"]["items"]] == [2024, 2025]
    assert [item["rank_mat_bas_municipio"] for item in body["data"]["items"]] == [5, 2]
    assert body["meta"]["ano_referencia"] == 2025
    # série curta: sem paginação
    assert "page" not in body


def test_campos_da_mart_chegam_ao_payload(client, repository):
    repository.competidores = [
        competidor_row(
            n_concorrentes_privados_municipio=10,
            n_concorrentes_com_matricula_bas=8,
            n_concorrentes_creche_xself=3,
            n_concorrentes_pre_xself=4,
            n_concorrentes_fund_ai_xself=5,
            n_concorrentes_fund_af_xself=2,
            n_concorrentes_med_xself=1,
            lider_no_entidade="ESCOLA LIDER",
            lider_qt_mat_bas=300,
            gap_mat_bas_para_lider=-180,
        )
    ]

    item = client.get(URL).json()["data"]["items"][0]

    assert item["n_concorrentes_privados_municipio"] == 10
    assert item["n_concorrentes_com_matricula_bas"] == 8
    assert item["n_concorrentes_creche_xself"] == 3
    assert item["n_concorrentes_pre_xself"] == 4
    assert item["n_concorrentes_fund_ai_xself"] == 5
    assert item["n_concorrentes_fund_af_xself"] == 2
    assert item["n_concorrentes_med_xself"] == 1
    assert item["lider_no_entidade"] == "ESCOLA LIDER"
    assert item["lider_qt_mat_bas"] == 300
    assert item["gap_mat_bas_para_lider"] == -180


def test_null_preservado_nao_vira_zero(client, repository):
    """Ausência de medida não é 0 concorrente (AGENTS.md §6 / R2)."""
    repository.competidores = [
        competidor_row(
            n_concorrentes_privados_municipio=None,
            n_concorrentes_com_matricula_bas=None,
            n_concorrentes_med_xself=None,
            lider_no_entidade=None,
            lider_qt_mat_bas=None,
            gap_mat_bas_para_lider=None,
        )
    ]

    item = client.get(URL).json()["data"]["items"][0]

    assert item["n_concorrentes_privados_municipio"] is None
    assert item["n_concorrentes_com_matricula_bas"] is None
    assert item["n_concorrentes_med_xself"] is None
    assert item["lider_no_entidade"] is None
    assert item["lider_qt_mat_bas"] is None
    assert item["gap_mat_bas_para_lider"] is None


def test_gap_zero_significa_escola_lider(client, repository):
    """`gap = 0` é medida observada (a própria escola lidera) — também não se perde."""
    repository.competidores = [
        competidor_row(lider_no_entidade="ESCOLA MODELO", lider_qt_mat_bas=120, gap_mat_bas_para_lider=0)
    ]

    item = client.get(URL).json()["data"]["items"][0]

    assert item["gap_mat_bas_para_lider"] == 0
    assert item["lider_qt_mat_bas"] == 120


def test_escola_publica_e_404_com_universo(client, repository):
    repository.schools = [school_row(tp_dependencia="3")]

    response = client.get(URL)

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NAO_ENCONTRADO"
    assert body["type"] == "https://api.panorama/erros/nao-encontrado"
    assert "universo" in body["detail"]
    # nunca 200 com zeros
    assert "data" not in body


def test_escola_inativa_e_404(client, repository):
    repository.schools = [school_row(tp_dependencia="4", tp_situacao_funcionamento="2")]

    response = client.get(URL)

    assert response.status_code == 404
    assert response.json()["code"] == "NAO_ENCONTRADO"
    assert "universo" in response.json()["detail"]


def test_escola_fora_de_mg_e_404(client, repository):
    """Escola ausente do recorte MG (não está em `dim_escola`) — 404."""
    response = client.get("/v1/schools/99999999/competitors")

    assert response.status_code == 404
    assert response.json()["code"] == "NAO_ENCONTRADO"


def test_privada_ativa_sem_linha_na_mart_e_404_sem_zeros(client, repository):
    """Ausência de matrícula BAS: 404 explícito, nunca 0 concorrentes."""
    repository.schools = [school_row(tp_dependencia="4", tp_situacao_funcionamento="1")]

    response = client.get(URL)

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NAO_ENCONTRADO"
    assert "matrícula BAS" in body["detail"]


def test_co_entidade_invalida_e_422(client):
    response = client.get("/v1/schools/abc/competitors")

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "PARAMETRO_INVALIDO"
    assert body["errors"][0]["loc"] == ["path", "co_entidade"]


def test_parametro_fora_da_allowlist_e_400(client, repository):
    """`raio`, `ano`, `limit`... não existem nesta rota."""
    repository.competidores = [competidor_row()]

    for query in ({"raio": "5"}, {"limit": "10"}, {"order": "rank"}):
        response = client.get(URL, params=query)

        assert response.status_code == 400, query
        assert response.json()["code"] == "PARAMETRO_INVALIDO"


def test_fonte_indisponivel_e_503(client, repository):
    repository.errors["get_school_competidores"] = UpstreamUnavailable("timeout")

    response = client.get(URL)

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "FONTE_INDISPONIVEL"
    assert "timeout" not in body["detail"]
    assert "data" not in body


def test_resposta_e_cacheavel(client, repository):
    """Resposta 200 entra no cache HTTP como os demais GET /v1/*."""
    repository.competidores = [competidor_row()]

    response = client.get(URL)

    assert response.status_code == 200
    assert response.headers["cache-control"].startswith("public, max-age=86400")
    assert "etag" in {name.lower() for name in response.headers}


def test_consulta_nao_usa_count_nem_nome_de_concorrente():
    """A consulta é allowlist: só a linha da própria escola, sem lista nominal."""
    from panorama_api.repositories import queries

    sql, params = queries.school_competidores(
        lambda table: f"`proj.dset.{table}`", co_entidade="31000001"
    )

    assert "FROM `proj.dset.mart_competidores`" in sql
    assert "WHERE co_entidade = @co_entidade" in sql
    assert "ORDER BY nu_ano_censo ASC" in sql
    assert "COUNT(" not in sql.upper()
    assert [(name, type_) for name, type_, _ in params] == [("co_entidade", "STRING")]
    # nenhuma coluna de distância/raio e nenhuma lista de escolas
    for proibido in ("raio", "distancia", "distância", "geom", "latitude", "longitude"):
        assert proibido not in sql.lower()
