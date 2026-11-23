"""Fundação do front SSR `/app` (card `t_4370a4f1`).

Cobre o que o card exige como verificável sobre o HTML renderizado:

* `null` → "sem dado" e **nunca** "0" (inclusive com a razão de `is_*_missing`);
* oferta tri-estado `true/false/null` → Sim/Não/Desconhecido;
* `503` → página 503 com `Retry-After` e `Cache-Control: no-store`;
* grep do HTML: sem "evasão" como rótulo de métrica e sem "raio"/"próximos"/"na região";
* assets com hash de conteúdo servidos como imutáveis;
* `/v1/*` continua em `application/problem+json` (contrato preservado).
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from panorama_api.core.errors import ErrorCode, ProblemError, UpstreamUnavailable
from panorama_api.main import create_app
from panorama_api.web.filters import fmt_nulo, fmt_oferta
from panorama_api.web.routes import CACHE_CONTROL_ERRO, RETRY_AFTER_SEGUNDOS
from tests.unit.conftest import school_row

METODOLOGIA = "/app/metodologia"
#: Termos proibidos como vocabulário de comparação geográfica (escopo-adiado-v1).
TERMOS_PROIBIDOS = ("raio", "próximos", "proximos", "na região", "na regiao")


def _html(response) -> str:
    assert response.status_code in (200, 400, 404, 422, 500, 503)
    assert response.headers["content-type"].startswith("text/html")
    return response.text


# -- filtros: fonte única das regras de exibição -------------------------------


@pytest.mark.parametrize("valor", [None, "", "   "])
def test_filtro_nulo_nunca_vira_zero(valor):
    assert fmt_nulo(valor) == "sem dado"
    assert "0" not in fmt_nulo(valor)


def test_filtro_nulo_mostra_motivo_da_flag_quando_existe():
    assert fmt_nulo(None, "is_qt_mat_bas_missing") == "sem dado (is_qt_mat_bas_missing)"


def test_filtro_nulo_preserva_zero_real():
    # Zero declarado é dado, não ausência: sai como "0", não como "sem dado".
    assert fmt_nulo(0) == "0"
    assert fmt_nulo(0.0) == "0,0"


def test_filtro_nulo_formata_booleano_e_numeros():
    assert fmt_nulo(True) == "Sim"
    assert fmt_nulo(False) == "Não"
    assert fmt_nulo(12345) == "12.345"
    assert fmt_nulo(98.5) == "98,5"


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [(True, "Sim"), (False, "Não"), (None, "Desconhecido")],
)
def test_filtro_oferta_tri_estado(valor, esperado):
    assert fmt_oferta(valor) == esperado


def test_filtro_oferta_desconhecida_nao_e_lida_como_nao_oferta():
    assert fmt_oferta(None) != "Não"
    assert fmt_oferta(False) == "Não"
    # A flag `is_oferta_desconhecida` nunca muda o texto para "Não": o estado
    # da célula é sempre o tri-estado do contrato.
    assert fmt_oferta(None) == "Desconhecido"


def test_metodologia_nao_tem_link_absoluto_nem_celula_vazia(client):
    html = _html(client.get(METODOLOGIA))

    # `url_for` geraria `http://host/app/...`; o front usa caminho relativo.
    assert "http://testserver" not in html
    # Nenhuma célula de definição vazia (ausência ambígua é proibida).
    assert "<dd></dd>" not in html


# -- HTML renderizado por templates reais ------------------------------------


def _render(trecho: str, **contexto: object) -> str:
    """Renderiza um fragmento com o MESMO ambiente Jinja2 do front."""
    from panorama_api.web.routes import templates

    return templates().env.from_string(trecho).render(**contexto)


def test_html_de_campo_nulo_diz_sem_dado_e_nunca_zero():
    html = _render(
        '<td id="mat">{{ qt_mat_bas | fmt_nulo("is_qt_mat_bas_missing") }}</td>',
        qt_mat_bas=None,
    )

    assert "sem dado" in html
    assert "is_qt_mat_bas_missing" in html
    assert ">0<" not in html


def test_html_de_oferta_tri_estado():
    trecho = '{% for v in valores %}<li>{{ v | fmt_oferta }}</li>{% endfor %}'
    html = _render(trecho, valores=[True, False, None])

    assert html.count("Sim") == 1
    assert html.count("Não") == 1
    assert html.count("Desconhecido") == 1


def test_html_de_zero_declarado_continua_zero():
    html = _render('<span>{{ valor | fmt_nulo }}</span>', valor=0)

    assert ">0<" in html
    assert "sem dado" not in html


# -- /app/metodologia ---------------------------------------------------------


def test_metodologia_e_html_200(client):
    resposta = client.get(METODOLOGIA)
    html = _html(resposta)

    assert resposta.status_code == 200
    assert "Metodologia" in html
    # Versões obrigatórias: dados publicados e contrato de serving.
    assert "mvp-1" in html
    assert "serving-marts" in html
    # Definição semântica obrigatória do proxy de retenção.
    assert "não é taxa de evasão" in html
    assert "Escolas privadas ativas no mesmo município e ano censitário (MG)" in html


def test_metodologia_nao_tem_rotulo_de_metrica_com_evasao(client):
    html = _html(client.get(METODOLOGIA))

    rotulos = re.findall(r"<dt>(.*?)</dt>", html, flags=re.S)
    for rotulo in rotulos:
        assert "evasão" not in rotulo.lower(), f"rótulo de métrica com 'evasão': {rotulo!r}"

    for termo in TERMOS_PROIBIDOS:
        assert termo not in html.lower(), f"termo geográfico proibido no HTML: {termo!r}"


def test_metodologia_renderiza_assets_com_hash_e_cache_imutavel(client):
    html = _html(client.get(METODOLOGIA))
    caminho = re.search(r'href="(/app/static/[^"]+\.css)"', html)

    assert caminho is not None, "link de CSS ausente no layout base"
    url = caminho.group(1)
    assert re.fullmatch(r"/app/static/[0-9a-f]{12}-app\.css", url), url

    asset = client.get(url)
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert asset.headers["content-type"].startswith("text/css")


def test_asset_com_hash_errado_e_404_html(client):
    resposta = client.get("/app/static/000000000000-app.css")

    assert resposta.status_code == 404
    assert resposta.headers["cache-control"] == CACHE_CONTROL_ERRO
    assert "não encontrado" in _html(resposta).lower()


# -- páginas de erro ----------------------------------------------------------


def test_404_em_app_e_pagina_html_sem_stack(client):
    resposta = client.get("/app/rota-que-nao-existe")

    assert resposta.status_code == 404
    assert resposta.headers["cache-control"] == CACHE_CONTROL_ERRO
    html = _html(resposta)
    assert "não encontrado" in html.lower()
    # Sem stack trace / SQL na página de erro.
    assert "traceback" not in html.lower()
    assert "select " not in html.lower()


def test_503_de_problem_error_em_app_devolve_retry_after_e_no_store(repository):
    app = create_app(settings=_settings(), repository=repository)

    @app.get("/app/_boom")
    def _boom() -> None:  # pragma: no cover - handler do teste
        raise ProblemError(ErrorCode.FONTE_INDISPONIVEL, "fonte de dados indisponível")

    with TestClient(app) as test_client:
        resposta = test_client.get("/app/_boom")

    assert resposta.status_code == 503
    assert resposta.headers["retry-after"] == str(RETRY_AFTER_SEGUNDOS)
    assert resposta.headers["cache-control"] == CACHE_CONTROL_ERRO
    html = _html(resposta)
    assert "temporariamente indisponível" in html.lower()
    # "nunca renderização parcial": a página é só o erro, sem seção de dados.
    assert "traceback" not in html.lower()


def test_503_de_upstream_unavailable_em_app_vira_pagina(repository):
    app = create_app(settings=_settings(), repository=repository)

    @app.get("/app/_upstream")
    def _upstream() -> None:  # pragma: no cover - handler do teste
        raise UpstreamUnavailable()

    with TestClient(app) as test_client:
        resposta = test_client.get("/app/_upstream")

    assert resposta.status_code == 503
    assert resposta.headers["retry-after"] == str(RETRY_AFTER_SEGUNDOS)
    assert resposta.headers["cache-control"] == CACHE_CONTROL_ERRO


def test_422_de_validacao_em_app_vira_pagina(repository):
    app = create_app(settings=_settings(), repository=repository)

    @app.get("/app/_validacao")
    def _validacao(limit: int) -> None:  # pragma: no cover - handler do teste
        raise AssertionError("não deveria executar")

    with TestClient(app) as test_client:
        resposta = test_client.get("/app/_validacao", params={"limit": "abc"})

    assert resposta.status_code == 422
    assert resposta.headers["cache-control"] == CACHE_CONTROL_ERRO
    html = _html(resposta)
    assert "parâmetro inválido" in html.lower()
    assert "limit" in html


def test_erro_interno_em_app_nao_expoe_stack(repository):
    app = create_app(settings=_settings(), repository=repository)

    @app.get("/app/_quebra")
    def _quebra() -> None:  # pragma: no cover - handler do teste
        raise RuntimeError("boom interno")

    with TestClient(app, raise_server_exceptions=False) as test_client:
        resposta = test_client.get("/app/_quebra")

    assert resposta.status_code == 500
    assert resposta.headers["cache-control"] == CACHE_CONTROL_ERRO
    html = _html(resposta)
    assert "erro interno" in html.lower()
    assert "boom interno" not in html
    assert "traceback" not in html.lower()


# -- contrato /v1 preservado --------------------------------------------------


def test_erros_de_v1_continuam_em_problem_json(client):
    resposta = client.get("/v1/schools", params={"co_municipio": "0000000"})

    assert resposta.status_code == 422
    assert resposta.headers["content-type"] == "application/problem+json"
    assert resposta.json()["code"] == ErrorCode.PARAMETRO_INVALIDO.value


def test_v1_nao_ganha_pagina_html(client):
    """404 de `/v1` continua RFC 9457, nunca HTML do front."""
    resposta = client.get("/v1/markets/3106200")

    assert resposta.status_code in (400, 404, 422, 503)
    assert resposta.headers["content-type"] == "application/problem+json"


def test_app_nao_aparece_no_openapi(client):
    schema = client.get("/openapi.json").json()

    assert not [caminho for caminho in schema["paths"] if caminho.startswith("/app")]


# -- gzip restrito a /app (header de /v1 não pode mudar) ----------------------


def test_gzip_comprime_html_do_app(client):
    resposta = client.get(METODOLOGIA, headers={"Accept-Encoding": "gzip"})

    assert resposta.status_code == 200
    # `TestClient` descomprime o corpo; o header prova que houve compressão.
    assert resposta.headers.get("content-encoding") == "gzip"


def test_gzip_nao_toca_em_v1(repository):
    """`/v1` é contrato público: nenhum header novo aparece nele."""
    repository.schools = [school_row()]
    resposta = client_para(repository).get(
        "/v1/schools",
        params={"co_municipio": "3106200"},
        headers={"Accept-Encoding": "gzip"},
    )

    assert resposta.status_code == 200
    assert "content-encoding" not in resposta.headers
    assert resposta.headers["cache-control"] == "public, max-age=86400, stale-while-revalidate=604800"


def test_sem_gzip_no_html_quando_cliente_nao_aceita(client):
    # `TestClient` envia `Accept-Encoding: gzip` por padrão; aqui pedimos
    # explicitamente identidade, como faria um cliente sem suporte a gzip.
    resposta = client.get(METODOLOGIA, headers={"Accept-Encoding": "identity"})

    assert resposta.status_code == 200
    assert "content-encoding" not in resposta.headers


def client_para(repository):
    from fastapi.testclient import TestClient

    return TestClient(create_app(settings=_settings(), repository=repository))


def _settings():
    from panorama_api.config import Settings

    return Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        max_bytes_billed=256 * 1024 * 1024,
        validate_schema_on_startup=False,
        contract_version="mvp-1",
        data_version="dev",
    )
