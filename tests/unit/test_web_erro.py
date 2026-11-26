"""Trava do DOM da tela de erro (card `t_ec42fcd5`, herança do D13).

`erro.html` não tem contraparte no protótipo: herda o sistema e usa só
componentes de `panorama.css`. Aqui ficam os critérios de aceite que o HTML
renderizado prova sozinho, para o card não depender de inspeção manual:

* os três status (404/422/503) continuam iguais;
* a página tem **uma** `h1` e **um** `role="alert"` — o alerta é um só, do
  painel, não a página inteira;
* o código HTTP aparece visível em `dl.rodape-meta` (`HTTP {status}`);
* as sete classes que não existem no protótipo continuam fora do template.

O texto não muda: os mesmos trechos que a tela mostrava antes seguem lá.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.core.errors import ErrorCode, ProblemError
from panorama_api.main import create_app

#: Classes legadas que a tela de erro usava e que não existem em
#: `panorama.css` (medido no plano §1.3). A trava de classes cobre o template
#: cru; aqui a mesma lista vale para o HTML renderizado das três telas.
#: `painel--erro`, `codigo-erro`, `aviso--temporario`, `lista-regras`,
#: `paginacao__link` e `rodape-erro` saíram do app-only no D1-E7 (ninguém os
#: usava depois do D1-E5); continuam na lista como sentinela — se voltarem ao
#: HTML, o teste falha antes de a regra precisar existir.
CLASSES_LEGADAS = (
    "painel--erro",
    "codigo-erro",
    "subtitulo",
    "aviso--temporario",
    "lista-regras",
    "paginacao__link",
    "rodape-erro",
)


def _settings() -> Settings:
    return Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        max_bytes_billed=256 * 1024 * 1024,
        validate_schema_on_startup=False,
        contract_version="mvp-1",
        data_version="dev",
        app_anos_disponiveis="2021,2022,2023,2024,2025",
    )


@pytest.fixture
def telas_de_erro(repository):
    """Cliente com as rotas de teste dos três status: 404, 422 e 503."""
    app = create_app(settings=_settings(), repository=repository)

    @app.get("/app/_boom")
    def _boom() -> None:  # pragma: no cover - handler do teste
        raise ProblemError(ErrorCode.FONTE_INDISPONIVEL, "fonte de dados indisponível")

    @app.get("/app/_validacao")
    def _validacao(limit: int) -> None:  # pragma: no cover - handler do teste
        raise AssertionError("não deveria executar")

    with TestClient(app) as cliente:
        yield cliente


def _html(cliente: TestClient, caminho: str, params: dict | None = None) -> tuple[int, str]:
    resposta = cliente.get(caminho, params=params)
    assert resposta.headers["content-type"].startswith("text/html")
    return resposta.status_code, resposta.text


CASOS = (
    ("404", "/app/rota-que-nao-existe", None),
    ("422", "/app/mercados", {"co_municipio": ""}),
    ("503", "/app/_boom", None),
)


@pytest.mark.parametrize(("status", "caminho", "params"), CASOS)
def test_tela_de_erro_preserva_o_status(telas_de_erro, status, caminho, params):
    codigo, _ = _html(telas_de_erro, caminho, params)

    assert codigo == int(status)


@pytest.mark.parametrize(("status", "caminho", "params"), CASOS)
def test_tela_de_erro_tem_uma_h1_e_um_alerta(
    telas_de_erro, status, caminho, params
):
    _, html = _html(telas_de_erro, caminho, params)

    assert html.count("<h1") == 1
    assert html.count('role="alert"') == 1


@pytest.mark.parametrize(("status", "caminho", "params"), CASOS)
def test_tela_de_erro_mostra_o_codigo_http_no_rodape_meta(
    telas_de_erro, status, caminho, params
):
    _, html = _html(telas_de_erro, caminho, params)

    bloco = re.search(r'<dl class="rodape-meta".*?</dl>', html, flags=re.S)
    assert bloco is not None, "tela de erro sem dl.rodape-meta"
    assert "<dt>Código</dt>" in bloco.group(0)
    assert f"<dd>HTTP {status}</dd>" in bloco.group(0)


@pytest.mark.parametrize(("status", "caminho", "params"), CASOS)
def test_tela_de_erro_nao_usa_classe_fora_do_prototipo(
    telas_de_erro, status, caminho, params
):
    _, html = _html(telas_de_erro, caminho, params)

    sobras = [classe for classe in CLASSES_LEGADAS if classe in html]
    assert not sobras, f"classes fora do protótipo no HTML: {sobras}"
