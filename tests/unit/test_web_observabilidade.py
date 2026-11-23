"""Linha de log `page_view` do front `/app` (card `t_88589ae7`, plano §7).

O que este arquivo prova, sem `caplog` — o mesmo caminho de produção, que é o
stdout que o Cloud Logging lê como `jsonPayload`:

* uma linha `page_view` por requisição de página, com **todos** os campos do
  plano: `route`, `status`, `cache` (`hit`/`miss`/`304`), `ms`, `data_version`,
  `app_build`, `user_hash`;
* `cache = 304` em revalidação por `If-None-Match`, e `hit`/`miss` conforme o
  LRU — a decisão vem do middleware de cache, não é reimplementada;
* `user_hash` é `sha256(salt + email)[:16]` e **o e-mail em claro nunca aparece
  no stdout capturado**, nem com `API_OBS_USER_HASH_SALT` ausente;
* sem header do IAP → `anon`; assets `/app/static/*`, `/v1` e `/health` não
  geram `page_view` (não são páginas).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.core.errors import ErrorCode, ProblemError
from panorama_api.core.logging_config import configure_logging
from panorama_api.main import create_app
from panorama_api.web import observability
from panorama_api.web.observability import (
    EMAIL_HEADER,
    USER_HASH_ANON,
    email_do_header,
    user_hash,
)
from panorama_api.web.routes import assets
from tests.unit.conftest import FakeRepository, market_row, municipio_row

EMAIL = "piloto.alfa@example.com"
EMAIL_HEADER_ELF = f"accounts.google.com:{EMAIL}"
SALT = "sal-de-teste-88589ae7"
SENDA = "/app/_sonda"
SENDA_ROTA = "/app/_sonda/{co_municipio}"

CAMPOS = {
    "route",
    "status",
    "cache",
    "ms",
    "data_version",
    "app_build",
    "user_hash",
}


def _settings(*, salt: str = SALT) -> Settings:
    return Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        max_bytes_billed=256 * 1024 * 1024,
        validate_schema_on_startup=False,
        contract_version="mvp-1",
        data_version="2026.11.17",
        app_build="build-a",
        obs_user_hash_salt=salt,
    )


def _app(*, salt: str = SALT):
    repo = FakeRepository(municipios=[municipio_row()], markets=[market_row(etapa="bas")])
    app = create_app(settings=_settings(salt=salt), repository=repo)

    @app.get(SENDA_ROTA, response_class=HTMLResponse, include_in_schema=False)
    def _sonda(co_municipio: str, request: Request) -> str:
        encontrado = request.app.state.repo.get_municipio(co_municipio)
        nome = (encontrado or {}).get("no_municipio") or "sem dado"
        return f"<html><body><p>{nome}</p></body></html>"

    @app.get("/app/_indisponivel", include_in_schema=False)
    def _indisponivel() -> None:  # pragma: no cover - handler do teste
        raise ProblemError(ErrorCode.FONTE_INDISPONIVEL, "fonte de dados indisponível")

    @app.get("/app/_quebrada", include_in_schema=False)
    def _quebrada() -> None:  # pragma: no cover - handler do teste
        raise RuntimeError("falha fora do handler global")

    return app, repo


def _linhas(out: str, message: str = "page_view") -> list[dict[str, Any]]:
    return [
        item
        for item in (json.loads(line) for line in out.splitlines() if line.startswith("{"))
        if item.get("message") == message
    ]


@pytest.fixture(autouse=True)
def _logging_e_aviso_limpos():
    """Cada teste parte do logger configurado e do aviso de salt já emitido."""
    configure_logging(force=True)
    observability.reset_warning()
    yield
    observability.reset_warning()


# -- a linha: campos e valores ------------------------------------------------


def test_page_view_tem_todos_os_campos_do_plano(capsys):
    app, _repo = _app()
    with TestClient(app) as client:
        capsys.readouterr()
        resposta = client.get(
            f"{SENDA_ROTA.replace('{co_municipio}', '3106200')}",
            headers={EMAIL_HEADER: EMAIL_HEADER_ELF},
        )

    assert resposta.status_code == 200
    (linha,) = _linhas(capsys.readouterr().out)

    assert CAMPOS <= set(linha)
    assert linha["severity"] == "INFO"
    assert linha["logger"] == "panorama_api.web.observability"
    assert linha["route"] == SENDA_ROTA
    assert linha["status"] == 200
    assert linha["cache"] == "miss"
    assert isinstance(linha["ms"], float)
    assert linha["ms"] >= 0.0
    assert linha["data_version"] == "2026.11.17"
    assert linha["app_build"] == "build-a"


def test_page_view_usa_o_template_da_rota_e_nao_o_caminho_concreto(capsys):
    app, _repo = _app()
    with TestClient(app) as client:
        capsys.readouterr()
        client.get(
            SENDA_ROTA.replace("{co_municipio}", "3106200"),
            headers={EMAIL_HEADER: EMAIL_HEADER_ELF},
        )
        client.get(
            SENDA_ROTA.replace("{co_municipio}", "3106201"),
            headers={EMAIL_HEADER: EMAIL_HEADER_ELF},
        )

    rotas = [linha["route"] for linha in _linhas(capsys.readouterr().out)]
    # Agregar por rota exige que o caminho concreto não vaze para o campo.
    assert rotas == [SENDA_ROTA, SENDA_ROTA]


# -- cache: hit, miss e 304 --------------------------------------------------


def test_page_view_marca_304_na_revalidacao_por_etag(capsys):
    app, _repo = _app()
    url = SENDA_ROTA.replace("{co_municipio}", "3106200")
    with TestClient(app) as client:
        primeira = client.get(url, headers={EMAIL_HEADER: EMAIL_HEADER_ELF})
        capsys.readouterr()
        # `If-None-Match` é decidido antes do handler: a rota nunca é executada.
        client.get(
            url,
            headers={EMAIL_HEADER: EMAIL_HEADER_ELF, "If-None-Match": primeira.headers["etag"]},
        )

    assert primeira.status_code == 200
    (linha,) = _linhas(capsys.readouterr().out)
    assert linha["cache"] == "304"
    assert linha["status"] == 304
    assert linha["route"] == SENDA_ROTA


def test_page_view_marca_hit_quando_servido_do_lru(capsys):
    app, repo = _app()
    url = f"{SENDA_ROTA.replace('{co_municipio}', '3106200')}"
    with TestClient(app, headers={EMAIL_HEADER: EMAIL_HEADER_ELF}) as client:
        client.get(url)  # miss: enche o LRU
        chamadas = len(repo.calls)
        capsys.readouterr()
        client.get(url)  # hit: não executa o handler

    assert len(repo.calls) == chamadas
    (linha,) = _linhas(capsys.readouterr().out)
    assert linha["cache"] == "hit"
    assert linha["status"] == 200


def test_page_view_de_erro_carrega_o_status_real_e_nao_cacheia(capsys):
    app, _repo = _app()
    # `raise_server_exceptions=False`: a sonda quer a resposta 500 que o cliente
    # de fato recebe, não a exceção re-levantada pelo `TestClient`.
    with TestClient(app, raise_server_exceptions=False) as client:
        capsys.readouterr()
        indisponivel = client.get("/app/_indisponivel")
        quebrada = client.get("/app/_quebrada")

    assert indisponivel.status_code == 503
    assert quebrada.status_code == 500
    linhas = _linhas(capsys.readouterr().out)

    assert [linha["status"] for linha in linhas] == [503, 500]
    assert {linha["cache"] for linha in linhas} == {"miss"}
    assert {linha["route"] for linha in linhas} == {
        "/app/_indisponivel",
        "/app/_quebrada",
    }

    # Caminho sem rota registrada continua rastreável pelo caminho concreto.
    with TestClient(app) as client:
        capsys.readouterr()
        client.get("/app/inexistente")
    (linha,) = _linhas(capsys.readouterr().out)
    assert linha["route"] == "/app/inexistente"
    assert linha["status"] == 404


# -- identidade: hash, nunca o e-mail ---------------------------------------


def test_user_hash_e_sha256_do_salt_mais_email_truncado():
    esperado = hashlib.sha256((SALT + EMAIL).encode("utf-8")).hexdigest()[:16]

    assert user_hash(EMAIL, SALT) == esperado
    assert len(esperado) == 16
    # Ordem importa: salt primeiro.
    assert user_hash(EMAIL, SALT) != hashlib.sha256((EMAIL + SALT).encode()).hexdigest()[:16]


def test_user_hash_e_anon_sem_email_ou_sem_salt():
    assert user_hash(None, SALT) == USER_HASH_ANON
    assert user_hash("", SALT) == USER_HASH_ANON
    assert user_hash(EMAIL, "") == USER_HASH_ANON


def test_email_do_header_aceita_formato_do_iap_e_valor_cru():
    assert email_do_header(EMAIL_HEADER_ELF) == EMAIL
    assert email_do_header(EMAIL) == EMAIL
    assert email_do_header(None) is None
    assert email_do_header("accounts.google.com:") is None


def test_page_view_hash_do_piloto_e_nao_traz_o_email(capsys):
    app, _repo = _app()
    with TestClient(app) as client:
        capsys.readouterr()
        client.get(SENDA, headers={EMAIL_HEADER: EMAIL_HEADER_ELF})

    capturado = capsys.readouterr().out
    linha = _linhas(capturado)[0]

    assert linha["user_hash"] == hashlib.sha256((SALT + EMAIL).encode()).hexdigest()[:16]
    # Critério de aceite: o e-mail em claro nunca aparece no stdout capturado.
    assert EMAIL not in capturado
    assert "piloto.alfa" not in capturado


def test_sem_header_do_iap_page_view_e_anon(capsys):
    app, _repo = _app()
    with TestClient(app) as client:
        capsys.readouterr()
        client.get(SENDA)

    (linha,) = _linhas(capsys.readouterr().out)
    assert linha["user_hash"] == USER_HASH_ANON


def test_sem_salt_page_view_e_anon_e_avisa_uma_vez(capsys):
    app, _repo = _app(salt="")
    with TestClient(app) as client:
        capsys.readouterr()
        client.get(SENDA, headers={EMAIL_HEADER: EMAIL_HEADER_ELF})
        client.get(SENDA, headers={EMAIL_HEADER: EMAIL_HEADER_ELF})

    capturado = capsys.readouterr().out
    linhas = _linhas(capturado)

    assert [linha["user_hash"] for linha in linhas] == [USER_HASH_ANON, USER_HASH_ANON]
    avisos = _linhas(capturado, "page_view_user_hash_sem_salt")
    assert len(avisos) == 1
    assert avisos[0]["env"] == "API_OBS_USER_HASH_SALT"
    assert EMAIL not in capturado


# -- o que NÃO gera page_view ------------------------------------------------


def test_assets_v1_e_health_nao_geram_page_view(capsys):
    app, _repo = _app()
    with TestClient(app) as client:
        capsys.readouterr()
        asset = assets().url("app.css")
        client.get(asset)
        client.get("/v1/markets/3106200", params={"ano": 2025})
        client.get("/health")

    assert _linhas(capsys.readouterr().out) == []


# -- o middleware em isolamento (sem app, sem cache) ------------------------


def test_cache_status_normaliza_a_decisao_do_cache():
    """`hit`/`miss` vêm do middleware de cache; 304 e ausência têm regra própria."""
    from panorama_api.web.observability import _cache_status

    assert _cache_status("hit", 200) == "hit"
    assert _cache_status("miss", 200) == "miss"
    # Revalidação vence: o status real da resposta é 304, mesmo com `hit` no scope.
    assert _cache_status("hit", 304) == "304"
    assert _cache_status(None, 304) == "304"
    # Requisição que o cache não tratou (ex. POST) executou o handler: é `miss`.
    assert _cache_status(None, 200) == "miss"
