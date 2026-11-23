"""Cache HTTP/LRU das respostas `GET /v1/*` (card `t_817a670c`)."""

from __future__ import annotations

import logging

from panorama_api.core.http_cache import (
    CACHE_CONTROL,
    LruCache,
    CachedResponse,
    cache_key,
    etag_for,
    etag_matches,
)
from panorama_api.core.errors import UpstreamUnavailable
from tests.unit.conftest import concentracao_row, market_row, municipio_row, school_row

CACHE_CONTROL_ESPERADO = "public, max-age=86400, stale-while-revalidate=604800"
MARKET_URL = "/v1/markets/3106200"


def _abastece_mercado(repository) -> None:
    repository.municipios = [municipio_row()]
    repository.markets = [market_row(etapa="bas")]
    repository.concentracao = [concentracao_row(etapa="bas")]


def _get_mercado(client, *, headers=None):
    return client.get(MARKET_URL, params={"ano": 2025}, headers=headers)


def _chamadas(repository) -> int:
    return len(repository.calls)


def test_200_de_v1_tem_cache_control_e_etag_forte(client, repository):
    _abastece_mercado(repository)

    response = _get_mercado(client)

    assert response.status_code == 200
    assert response.headers["cache-control"] == CACHE_CONTROL_ESPERADO
    assert response.headers["cache-control"] == CACHE_CONTROL
    etag = response.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"') and len(etag) == 34


def test_etag_e_estavel_para_a_mesma_requisicao(client, repository):
    _abastece_mercado(repository)

    primeiro = _get_mercado(client)
    segundo = _get_mercado(client)

    assert primeiro.headers["etag"] == segundo.headers["etag"]
    assert primeiro.content == segundo.content


def test_etag_muda_quando_mudam_os_parametros(client, repository):
    repository.schools = [school_row()]

    curto = client.get(
        "/v1/schools", params={"co_municipio": "3106200", "limit": 5}
    )
    longo = client.get(
        "/v1/schools", params={"co_municipio": "3106200", "limit": 10}
    )

    assert curto.status_code == longo.status_code == 200
    assert curto.headers["etag"] != longo.headers["etag"]


def test_ordem_dos_parametros_nao_muda_etag_nem_chave(client, repository):
    repository.schools = [school_row()]

    primeiro = client.get(
        "/v1/schools", params={"co_municipio": "3106200", "limit": 5}
    )
    chamadas = _chamadas(repository)
    segundo = client.get(
        "/v1/schools", params={"limit": 5, "co_municipio": "3106200"}
    )

    assert segundo.headers["etag"] == primeiro.headers["etag"]
    assert _chamadas(repository) == chamadas  # veio do LRU, sem consulta
    assert segundo.content == primeiro.content


def test_if_none_match_devolve_304_sem_corpo_e_sem_consultar(client, repository):
    _abastece_mercado(repository)
    primeira = _get_mercado(client)
    chamadas = _chamadas(repository)

    resposta = _get_mercado(client, headers={"If-None-Match": primeira.headers["etag"]})

    assert resposta.status_code == 304
    assert resposta.content == b""
    assert resposta.headers["etag"] == primeira.headers["etag"]
    assert resposta.headers["cache-control"] == CACHE_CONTROL_ESPERADO
    assert "content-length" not in resposta.headers
    assert _chamadas(repository) == chamadas  # nenhum job novo


def test_304_aceita_tag_fraca_e_lista(client, repository):
    _abastece_mercado(repository)
    etag = _get_mercado(client).headers["etag"]

    fraco = _get_mercado(client, headers={"If-None-Match": f"W/{etag}"})
    lista = _get_mercado(client, headers={"If-None-Match": f'"outro", {etag}'})
    curinga = _get_mercado(client, headers={"If-None-Match": "*"})

    assert fraco.status_code == lista.status_code == curinga.status_code == 304


def test_curinga_nao_esconde_recurso_inexistente(client, repository):
    # RFC 9110: `If-None-Match: *` só casa quando existe representação atual.
    _abastece_mercado(repository)

    resposta = client.get("/v1/markets/3106200?ano=2024", headers={"If-None-Match": "*"})

    assert resposta.status_code == 404
    assert "etag" not in resposta.headers


def test_curinga_so_responde_304_depois_de_confirmar_que_o_recurso_existe(
    client, repository
):
    _abastece_mercado(repository)

    resposta = _get_mercado(client, headers={"If-None-Match": "*"})

    assert resposta.status_code == 304
    assert resposta.content == b""
    assert _chamadas(repository) > 0  # o handler confirmou a existência


def test_etag_diferente_devolve_200_com_corpo(client, repository):
    _abastece_mercado(repository)

    resposta = _get_mercado(client, headers={"If-None-Match": '"nao-e-esse"'})

    assert resposta.status_code == 200
    assert resposta.json()["data"]["co_municipio"] == "3106200"


def test_hit_do_lru_nao_consulta_o_repositorio_e_loga_cache_hit(
    client, repository, caplog
):
    _abastece_mercado(repository)
    primeira = _get_mercado(client)
    chamadas = _chamadas(repository)

    with caplog.at_level(logging.INFO, logger="panorama_api.core.http_cache"):
        segunda = _get_mercado(client)

    assert segunda.content == primeira.content
    assert _chamadas(repository) == chamadas
    cache_logs = [r for r in caplog.records if r.getMessage() == "http_cache"]
    assert cache_logs and cache_logs[-1].cache == "hit"
    assert cache_logs[-1].status == 200


def test_miss_loga_cache_miss(client, repository, caplog):
    _abastece_mercado(repository)

    with caplog.at_level(logging.INFO, logger="panorama_api.core.http_cache"):
        _get_mercado(client)

    cache_logs = [r for r in caplog.records if r.getMessage() == "http_cache"]
    assert cache_logs and cache_logs[-1].cache == "miss"
    assert cache_logs[-1].data_version == "dev"


def test_data_version_nova_invalida_etag_e_cache(client, repository):
    _abastece_mercado(repository)
    antes = _get_mercado(client)
    chamadas = _chamadas(repository)

    client.app.state.settings.data_version = "2026.11.17"
    depois = _get_mercado(client)

    assert depois.headers["etag"] != antes.headers["etag"]
    assert _chamadas(repository) > chamadas  # miss: voltou ao BigQuery
    assert depois.content == antes.content  # dados iguais, versão diferente

    # O ETag antigo não vale mais: cliente recebe 200 com o ETag novo.
    revalidando = _get_mercado(client, headers={"If-None-Match": antes.headers["etag"]})
    assert revalidando.status_code == 200
    assert revalidando.headers["etag"] == depois.headers["etag"]


def test_data_version_igual_continua_sendo_hit(client, repository):
    _abastece_mercado(repository)
    primeira = _get_mercado(client)
    chamadas = _chamadas(repository)

    client.app.state.settings.data_version = "dev"  # mesmo valor, explícito
    segunda = _get_mercado(client)

    assert segunda.headers["etag"] == primeira.headers["etag"]
    assert _chamadas(repository) == chamadas


def test_404_nao_e_cacheado_nem_leva_cabecalhos(client, repository):
    _abastece_mercado(repository)
    url = "/v1/markets/3106200?ano=2024"
    chamadas = _chamadas(repository)

    primeira = client.get(url)
    depois_da_primeira = _chamadas(repository)
    segunda = client.get(url)

    assert primeira.status_code == segunda.status_code == 404
    for resposta in (primeira, segunda):
        assert "etag" not in resposta.headers
        assert "cache-control" not in resposta.headers
    assert depois_da_primeira > chamadas  # foi ao repositório
    assert _chamadas(repository) > depois_da_primeira  # e repetiu: nada cacheado


def test_503_nao_e_cacheado(client, repository):
    _abastece_mercado(repository)
    chamadas = _chamadas(repository)
    repository.errors["get_market"] = UpstreamUnavailable("fonte indisponível")

    resposta = _get_mercado(client)

    assert resposta.status_code == 503
    assert "etag" not in resposta.headers
    assert "cache-control" not in resposta.headers
    assert _chamadas(repository) > chamadas

    # Com o erro resolvido, a mesma URL volta a consultar e a cachear.
    repository.errors.clear()
    repository.markets = [market_row(etapa="bas")]
    recuperado = _get_mercado(client)
    assert recuperado.status_code == 200
    assert recuperado.headers["cache-control"] == CACHE_CONTROL_ESPERADO


def test_400_de_parametro_desconhecido_nao_e_cacheado(client, repository):
    _abastece_mercado(repository)

    resposta = client.get(MARKET_URL, params={"ano": 2025, "order": "x"})

    assert resposta.status_code == 400
    assert "etag" not in resposta.headers
    assert "cache-control" not in resposta.headers


def test_health_fica_fora_do_cache(client):
    resposta = client.get("/health")

    assert resposta.status_code == 200
    assert "etag" not in resposta.headers
    assert "cache-control" not in resposta.headers


def test_lru_descarta_a_entrada_menos_recente():
    cache = LruCache(max_entries=2)

    def entry(valor: str) -> CachedResponse:
        return CachedResponse(body=valor.encode(), media_type="application/json")

    cache.put("a", entry("a"))
    cache.put("b", entry("b"))
    assert cache.get("a") is not None  # "a" passa a ser o mais recente

    cache.put("c", entry("c"))  # "b" é o menos recente: sai

    assert cache.get("b") is None
    assert cache.get("a") is not None
    assert cache.get("c") is not None
    assert len(cache) == 2
    assert cache.max_entries == 2


def test_lru_rejeita_tamanho_invalido():
    import pytest

    with pytest.raises(ValueError):
        LruCache(max_entries=0)
    with pytest.raises(TypeError):
        LruCache(max_entries=True)  # type: ignore[arg-type]


def test_chave_canonica_inclui_data_version_e_ordena_params():
    primeira = cache_key("v1", "/v1/schools", [("b", "2"), ("a", "1")], app_build="b0")
    segunda = cache_key("v1", "/v1/schools", [("a", "1"), ("b", "2")], app_build="b0")
    outra = cache_key("v2", "/v1/schools", [("a", "1"), ("b", "2")], app_build="b0")

    assert primeira == segunda
    assert outra != primeira
    assert etag_for(primeira) != etag_for(outra)


def test_chave_canonica_inclui_app_build():
    """F9/D7: o build do código também identifica a representação de `/v1`."""
    base = cache_key("v1", "/v1/schools", [], app_build="b0")

    assert cache_key("v1", "/v1/schools", [], app_build="b1") != base
    assert cache_key("v1", "/v1/schools", [], app_build="b0") == base


def test_etag_matches_tolera_espacos_e_tags_fracas():
    etag = etag_for("chave")

    assert etag_matches(f' {etag} , "outro"', etag)
    assert etag_matches(f"W/{etag}", etag)
    assert etag_matches("*", etag)
    assert not etag_matches(None, etag)
    assert not etag_matches('"outro"', etag)
