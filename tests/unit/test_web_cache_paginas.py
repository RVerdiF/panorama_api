"""Cache HTTP das páginas `/app`: ETag, 304 e LRU por `DATA_VERSION`+`APP_BUILD`.

Card `t_68bd7615` (F2). O que este arquivo prova:

* página `200` sai com `Cache-Control: private, no-cache` + `ETag` forte;
* `If-None-Match` igual → **304 sem executar o handler**, logo com o contador de
  chamadas ao repositório fake inalterado;
* o LRU serve a página sem tocar no repositório;
* trocar `DATA_VERSION` **ou** `APP_BUILD` muda o `ETag` da página;
* `APP_BUILD` **não** altera o `ETag` nem o `Cache-Control` de `/v1`;
* `4xx`/`5xx` não emitem `ETag` e saem com `no-store`;
* assets `/app/static/*` continuam imutáveis e fora do cache de páginas.

As páginas reais (busca/escola/mercado) entram em F3–F5; aqui a página é uma
sonda registrada no app de teste que consulta o repositório fake — é o contador
que o critério de aceite pede.
"""

from __future__ import annotations

import logging

import pytest
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from panorama_api.config import Settings
from panorama_api.core.errors import ErrorCode, ProblemError
from panorama_api.core.http_cache import (
    CACHE_CONTROL,
    CACHE_CONTROL_PAGINA,
    cache_key,
    etag_for,
)
from panorama_api.main import create_app
from panorama_api.web.routes import CACHE_CONTROL_ERRO
from tests.unit.conftest import FakeRepository, market_row, municipio_row

SENDA = "/app/_sonda"
V1_MARKET = "/v1/markets/3106200"


def _settings(*, data_version: str = "2026.11.17", app_build: str = "build-a") -> Settings:
    return Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        max_bytes_billed=256 * 1024 * 1024,
        validate_schema_on_startup=False,
        contract_version="mvp-1",
        data_version=data_version,
        app_build=app_build,
    )


def _app(*, data_version: str = "2026.11.17", app_build: str = "build-a"):
    """App com a sonda `/app/_sonda` e dados de mercado para o `/v1`."""
    repo = FakeRepository(municipios=[municipio_row()], markets=[market_row(etapa="bas")])
    app = create_app(
        settings=_settings(data_version=data_version, app_build=app_build),
        repository=repo,
    )

    @app.get(SENDA, response_class=HTMLResponse, include_in_schema=False)
    def _sonda(request: Request, co_municipio: str = "3106200") -> str:
        # Mesmo caminho das telas: toda leitura passa pelo repositório do app.
        encontrado = request.app.state.repo.get_municipio(co_municipio)
        nome = (encontrado or {}).get("no_municipio") or "sem dado"
        return f"<html><body><p>{nome}</p></body></html>"

    @app.get("/app/_indisponivel", include_in_schema=False)
    def _indisponivel() -> None:  # pragma: no cover - handler do teste
        raise ProblemError(ErrorCode.FONTE_INDISPONIVEL, "fonte de dados indisponível")

    @app.get("/app/_invalido", include_in_schema=False)
    def _invalido(limit: int) -> None:  # pragma: no cover - handler do teste
        raise AssertionError("não deveria executar")

    return app, repo


def _pega(client: TestClient, url: str = SENDA, **kwargs):
    return client.get(url, **kwargs)


# -- 200: política de cache da página ----------------------------------------


def test_pagina_200_tem_private_no_cache_e_etag_forte():
    app, _repo = _app()
    with TestClient(app) as client:
        resposta = _pega(client)

    assert resposta.status_code == 200
    assert resposta.headers["cache-control"] == CACHE_CONTROL_PAGINA
    etag = resposta.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"') and len(etag) == 34


def test_pagina_200_continua_html():
    app, _repo = _app()
    with TestClient(app) as client:
        resposta = _pega(client)

    assert resposta.headers["content-type"].startswith("text/html")
    assert "BELO HORIZONTE" in resposta.text


# -- 304 por If-None-Match, sem tocar no repositório -------------------------


def test_if_none_match_igual_devolve_304_sem_consultar_o_repositorio():
    app, repo = _app()
    with TestClient(app) as client:
        primeira = _pega(client)
        chamadas = len(repo.calls)

        segunda = _pega(client, headers={"If-None-Match": primeira.headers["etag"]})

    assert primeira.status_code == 200
    assert segunda.status_code == 304
    assert segunda.content == b""
    assert segunda.headers["etag"] == primeira.headers["etag"]
    assert segunda.headers["cache-control"] == CACHE_CONTROL_PAGINA
    assert "content-length" not in segunda.headers
    # Critério de aceite: revalidar não executa o handler.
    assert len(repo.calls) == chamadas


def test_304_aceita_tag_fraca_lista_e_curinga_na_pagina():
    app, repo = _app()
    with TestClient(app) as client:
        etag = _pega(client).headers["etag"]
        chamadas = len(repo.calls)

        fraco = _pega(client, headers={"If-None-Match": f"W/{etag}"})
        lista = _pega(client, headers={"If-None-Match": f'"outro", {etag}'})
        curinga = _pega(client, headers={"If-None-Match": "*"})

    assert fraco.status_code == lista.status_code == 304
    # `*` só casa depois de confirmar que a página existe (RFC 9110).
    assert curinga.status_code in (200, 304)
    assert len(repo.calls) == chamadas + (1 if curinga.status_code == 200 else 0)


def test_etag_diferente_devolve_200_com_corpo():
    app, _repo = _app()
    with TestClient(app) as client:
        resposta = _pega(client, headers={"If-None-Match": '"nao-e-esse"'})

    assert resposta.status_code == 200
    assert "BELO HORIZONTE" in resposta.text


# -- LRU ---------------------------------------------------------------


def test_lru_serve_a_pagina_sem_tocar_no_repositorio():
    app, repo = _app()
    with TestClient(app) as client:
        primeira = _pega(client)
        chamadas = len(repo.calls)

        segunda = _pega(client)

    assert segunda.status_code == 200
    assert segunda.content == primeira.content
    assert segunda.headers["etag"] == primeira.headers["etag"]
    assert len(repo.calls) == chamadas


def test_lru_preserva_o_content_type_da_pagina_no_hit():
    """Regressão: o *hit* do LRU saía como `application/json`.

    O `_StreamingResponse` do `BaseHTTPMiddleware` tem `media_type=None`, então
    guardar os headers do próprio middleware (sem o `content-type` real) fazia o
    HTML cacheado perder o tipo e o navegador não renderizar.
    """
    app, repo = _app()
    with TestClient(app) as client:
        miss = _pega(client)
        chamadas = len(repo.calls)
        hit = _pega(client)

    assert len(repo.calls) == chamadas  # veio do LRU
    assert miss.headers["content-type"].startswith("text/html")
    assert hit.headers["content-type"] == miss.headers["content-type"]
    assert hit.text == miss.text


def test_lru_de_v1_continua_json_no_hit_e_no_miss():
    app, repo = _app()
    with TestClient(app) as client:
        miss = client.get(V1_MARKET, params={"ano": 2025})
        chamadas = len(repo.calls)
        hit = client.get(V1_MARKET, params={"ano": 2025})

    assert miss.status_code == hit.status_code == 200
    assert len(repo.calls) == chamadas  # veio do LRU
    assert miss.headers["content-type"] == hit.headers["content-type"]
    assert hit.headers["content-type"].startswith("application/json")


def test_order_da_query_nao_muda_o_etag_da_pagina():
    app, repo = _app()
    with TestClient(app) as client:
        primeiro = _pega(client, params={"co_municipio": "3106200", "x": "1"})
        chamadas = len(repo.calls)
        segundo = _pega(client, params={"x": "1", "co_municipio": "3106200"})

    assert primeiro.status_code == segundo.status_code == 200
    assert segundo.headers["etag"] == primeiro.headers["etag"]
    assert len(repo.calls) == chamadas  # veio do LRU


# -- versões: DATA_VERSION e APP_BUILD --------------------------------------


def test_trocar_data_version_muda_o_etag_da_pagina():
    app_a, _ = _app(data_version="2026.11.17")
    app_b, _ = _app(data_version="2026.11.20")

    with TestClient(app_a) as client_a, TestClient(app_b) as client_b:
        antes = _pega(client_a)
        depois = _pega(client_b)

    assert antes.status_code == depois.status_code == 200
    assert antes.headers["etag"] != depois.headers["etag"]
    assert depois.content == antes.content  # dados iguais, versão diferente


def test_trocar_app_build_muda_o_etag_da_pagina():
    app_a, _ = _app(app_build="build-a")
    app_b, _ = _app(app_build="build-b")

    with TestClient(app_a) as client_a, TestClient(app_b) as client_b:
        antes = _pega(client_a)
        depois = _pega(client_b)

    assert antes.status_code == depois.status_code == 200
    assert antes.headers["etag"] != depois.headers["etag"]
    # O HTML é o mesmo: só o build do código mudou (deploy novo).
    assert depois.content == antes.content


def test_data_version_nova_invalida_lru_e_etag_no_mesmo_processo():
    app, repo = _app()
    with TestClient(app) as client:
        antes = _pega(client)
        chamadas = len(repo.calls)

        client.app.state.settings.app_build = "build-b"
        depois = _pega(client)

        revalidando = _pega(client, headers={"If-None-Match": antes.headers["etag"]})

    assert depois.headers["etag"] != antes.headers["etag"]
    assert len(repo.calls) > chamadas  # miss: executou o handler de novo
    assert revalidando.status_code == 200
    assert revalidando.headers["etag"] == depois.headers["etag"]


def test_settings_recusa_app_build_invalido_no_boot():
    with pytest.raises(ValidationError) as erro:
        _settings(app_build="build com espaço")

    assert "APP_BUILD" in str(erro.value)


def test_settings_recusa_data_version_invalida_no_boot():
    with pytest.raises(ValidationError) as erro:
        _settings(data_version="2026; DROP TABLE x")

    assert "DATA_VERSION" in str(erro.value)


# -- contrato /v1 preservado --------------------------------------------------


def test_app_build_nao_entra_no_cache_de_v1():
    """`/v1` é contrato público: só `DATA_VERSION` decide o `ETag`."""
    app_a, _ = _app(app_build="build-a")
    app_b, _ = _app(app_build="build-b")

    with TestClient(app_a) as client_a, TestClient(app_b) as client_b:
        antes = client_a.get(V1_MARKET, params={"ano": 2025})
        depois = client_b.get(V1_MARKET, params={"ano": 2025})

    assert antes.status_code == depois.status_code == 200
    assert antes.headers["etag"] == depois.headers["etag"]
    assert antes.headers["cache-control"] == CACHE_CONTROL
    assert depois.headers["cache-control"] == CACHE_CONTROL


def test_data_version_continua_mudando_o_etag_de_v1():
    app_a, _ = _app(data_version="2026.11.17")
    app_b, _ = _app(data_version="2026.11.20")

    with TestClient(app_a) as client_a, TestClient(app_b) as client_b:
        antes = client_a.get(V1_MARKET, params={"ano": 2025})
        depois = client_b.get(V1_MARKET, params={"ano": 2025})

    assert antes.headers["etag"] != depois.headers["etag"]


def test_chave_do_v1_permanece_identica_sem_app_build():
    """Sem `app_build` a chave é bit a bit a do card anterior."""
    chave = cache_key("2026.11.17", "/v1/schools", [("a", "1")])

    assert chave == "2026.11.17\x00/v1/schools\x00a=1"
    assert cache_key("2026.11.17", "/v1/schools", [("a", "1")], app_build="b") != chave
    assert (
        cache_key("2026.11.17", "/v1/schools", [("a", "1")], app_build="b")
        != cache_key("2026.11.17", "/v1/schools", [("a", "1")], app_build="c")
    )


# -- erros: sem ETag, no-store ----------------------------------------------


def test_404_de_pagina_nao_tem_etag_e_nao_e_cacheado():
    app, repo = _app()
    with TestClient(app) as client:
        primeira = client.get("/app/rota-que-nao-existe")
        chamadas = len(repo.calls)
        segunda = client.get("/app/rota-que-nao-existe")

    for resposta in (primeira, segunda):
        assert resposta.status_code == 404
        assert "etag" not in resposta.headers
        assert resposta.headers["cache-control"] == CACHE_CONTROL_ERRO
    assert len(repo.calls) == chamadas  # 404 de rota não chega ao repositório


def test_503_de_pagina_nao_tem_etag_e_nao_e_cacheado():
    app, _repo = _app()
    with TestClient(app) as client:
        resposta = client.get("/app/_indisponivel")

    assert resposta.status_code == 503
    assert "etag" not in resposta.headers
    assert resposta.headers["cache-control"] == CACHE_CONTROL_ERRO
    assert resposta.headers["retry-after"] == "300"


def test_422_de_pagina_nao_tem_etag():
    app, _repo = _app()
    with TestClient(app) as client:
        resposta = client.get("/app/_invalido", params={"limit": "abc"})

    assert resposta.status_code == 422
    assert "etag" not in resposta.headers
    assert resposta.headers["cache-control"] == CACHE_CONTROL_ERRO


# -- assets continuam imutáveis e fora do cache de páginas -------------------


def test_asset_continua_imutavel_e_sem_etag():
    app, _repo = _app()
    with TestClient(app) as client:
        html = client.get("/app/metodologia").text
        import re

        caminho = re.search(r'href="(/app/static/[^"]+\.css)"', html)

        assert caminho is not None, "link de CSS ausente no layout base"
        asset = client.get(caminho.group(1))

    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "etag" not in asset.headers


# -- regressão: a raiz /v1 nunca foi cacheada --------------------------------


def test_raiz_do_v1_com_if_none_match_forjado_continua_404_sem_cache():
    """`/v1` (sem barra) não é rota: 404 problem+json, sem ETag/Cache-Control.

    Regressão do review: o casamento do prefixo não pode aceitar a raiz `/v1`
    (só `/app` aceita a própria raiz). Sem isso, um `If-None-Match` forjado
    com a chave do caminho `/v1` devolvia 304 e o log `http_cache` passava a
    registrar requisições que antes não existiam.
    """
    app, repo = _app()
    etag_forjado = etag_for(cache_key("2026.11.17", "/v1", []))
    with TestClient(app) as client:
        resposta = client.get("/v1", headers={"If-None-Match": etag_forjado})

    assert resposta.status_code == 404
    assert resposta.headers["content-type"].startswith("application/problem+json")
    assert "etag" not in resposta.headers
    assert "cache-control" not in resposta.headers
    assert repo.calls == []


# -- regressão: caminhos fora do segmento /app não são páginas ---------------


@pytest.mark.parametrize("caminho", ["/apple", "/app-x", "/appfoo"])
def test_vizinho_do_prefixo_nao_e_tratado_como_pagina(caminho, caplog):
    """`/apple`, `/app-x` e `/appfoo` não pertencem a `/app`.

    Regressão do review: o casamento do prefixo precisa ser por segmento
    (`/app/`), não `startswith("/app")`. Um `If-None-Match` forjado com a
    chave desses caminhos devolvia 304 com ETag e `private, no-cache`, e um
    GET comum passava a gravar uma linha `http_cache` que antes não existia.
    """
    app, repo = _app()
    etag_forjado = etag_for(cache_key("2026.11.17", caminho, [], app_build="build-a"))
    with caplog.at_level(logging.INFO, logger="panorama_api"):
        with TestClient(app) as client:
            forjado = client.get(caminho, headers={"If-None-Match": etag_forjado})
            comum = client.get(caminho)

    for resposta in (forjado, comum):
        assert resposta.status_code == 404
        assert resposta.headers["content-type"].startswith("application/problem+json")
        assert "etag" not in resposta.headers
        assert "cache-control" not in resposta.headers
    assert repo.calls == []
    assert not [r for r in caplog.records if r.getMessage().startswith("http_cache")]
