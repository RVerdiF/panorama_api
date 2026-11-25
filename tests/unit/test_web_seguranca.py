"""CSP, `nosniff` e o asset `app.js` do front (card `t_71b25279`).

O `/app` passou a servir JavaScript (`static/app.js`, com hash de conteúdo). A
partir daí valem três invariantes que este arquivo protege:

* toda resposta do front — página, erro HTML e `/app/static/*` — sai com a CSP
  **exata** da spec (`interatividade.md` §6) e com `X-Content-Type-Options:
  nosniff`; `*hit* do LRU, *miss* e 304` levam o mesmo header constante;
* nada em `/v1` (e `/health`) ganha header novo: o contrato público é comparado
  com o mesmo app **sem** o middleware de segurança;
* o asset JS é servido como `text/javascript; charset=utf-8` com cache imutável,
  e as páginas carregam exatamente uma tag `<script src=… defer>` — sem inline,
  sem `<style>`, sem `style=` fora da barra de share e sem atributo `on*=`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.main import create_app
from panorama_api.web.middleware import CSP_WEB, WebSecurityHeadersMiddleware
from panorama_api.web.routes import assets
from tests.unit.conftest import (
    FakeRepository,
    competidor_row,
    history_row,
    indicator_row,
    market_row,
    municipio_row,
    school_row,
    share_row,
)

ANOS = (2021, 2022, 2023, 2024, 2025)
MUNICIPIO = "3106200"
ESCOLA = "31000001"

BUSCA = "/app/"
METODOLOGIA = "/app/metodologia"
FICHA = f"/app/escolas/{ESCOLA}"
CONCORRENCIA = f"{FICHA}/concorrencia"
INDICE = "/app/mercados/"
MERCADO = f"/app/mercados/{MUNICIPIO}"
ATALHO = "/app/mercados"
COMPARAR = f"/app/comparar?escolas={ESCOLA}"
COMPARAR_DUAS = f"/app/comparar?escolas={ESCOLA},31000002"

#: Todos os templates do front, por página que os renderiza (o guarda exige que
#: cada página carregue exatamente a tag única de `app.js`). A concorrência
#: antiga (`/concorrencia`) é `301` para a âncora `#concorrencia` da ficha
#: (card V2 `t_cbd54a92`): redirect não tem corpo, então os guardas de markup
#: só valem a âncora de destino para ela.
PAGINAS = (
    ("/", 200),
    (BUSCA, 200),
    (METODOLOGIA, 200),
    (FICHA, 200),
    (CONCORRENCIA, 301),
    (INDICE, 200),
    (MERCADO, 200),
    # Comparação lado a lado (card C4): as duas formas da página — com um id e
    # com dois — carregam a mesma base única de JS.
    (COMPARAR, 200),
    (COMPARAR_DUAS, 200),
    # Erros HTML também herdam o layout base (`erro.html`).
    (ATALHO, 422),
    ("/app/rota-que-nao-existe", 404),
    ("/app/escolas/99999999", 404),
)

DIRETORIO_WEB = Path(__file__).resolve().parents[2] / "src" / "panorama_api" / "web"
TEMPLATES = DIRETORIO_WEB / "templates"
APP_JS = DIRETORIO_WEB / "static" / "app.js"

#: Orçamento do arquivo bruto, sem minificação (spec §3/§6). O gráfico da série
#: (linha/área com dica, ponteiro e teclado, card V2 `t_cbd54a92`) exige ~18 KB:
#: o teto é o tamanho real medido (`wc -c`) com folga para ajuste fino.
ORCAMENTO_APP_JS = 20_480

#: Construções proibidas num arquivo sob CSP estrita sem `'unsafe-eval'`.
PROIBIDOS_APP_JS = ("eval(", "innerHTML", "new Function", "document.write")


def _settings() -> Settings:
    return Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        max_bytes_billed=256 * 1024 * 1024,
        validate_schema_on_startup=False,
        contract_version="mvp-1",
        data_version="dev",
        app_anos_disponiveis=",".join(str(ano) for ano in ANOS),
    )


def _repo() -> FakeRepository:
    return FakeRepository(
        municipios=[municipio_row()],
        schools=[school_row(), school_row(co_entidade="31000002", no_entidade="ESCOLA B")],
        history=[
            history_row(nu_ano_censo=ano) for ano in ANOS
        ]
        + [
            history_row(co_entidade="31000002", no_entidade="ESCOLA B", nu_ano_censo=ano)
            for ano in ANOS
        ],
        indicators=[indicator_row(nu_ano_censo=2025)],
        competidores=[competidor_row(nu_ano_censo=2025)],
        markets=[market_row(nu_ano_censo=ano, etapa="bas") for ano in ANOS],
        share=[share_row(nu_ano_censo=ano) for ano in ANOS],
    )


@pytest.fixture
def cliente() -> Iterator[TestClient]:
    app = create_app(settings=_settings(), repository=_repo())
    with TestClient(app) as test_client:
        yield test_client


def _sem_cabecalho_novo(cabecalhos) -> None:
    assert "content-security-policy" not in cabecalhos
    assert "x-content-type-options" not in cabecalhos


def _com_cabecalho_de_seguranca(cabecalhos) -> None:
    assert cabecalhos["content-security-policy"] == CSP_WEB
    assert cabecalhos["x-content-type-options"] == "nosniff"


# -- 1. headers nas respostas do front ---------------------------------------


@pytest.mark.parametrize(
    "caminho",
    [
        BUSCA,
        METODOLOGIA,
        FICHA,
        MERCADO,
        "/app/rota-que-nao-existe",
    ],
)
def test_paginas_do_front_levam_csp_e_nosniff(cliente: TestClient, caminho: str) -> None:
    resposta = cliente.get(caminho)

    assert resposta.status_code in (200, 404), resposta.status_code
    _com_cabecalho_de_seguranca(resposta.headers)


def test_csp_e_a_politica_exata_da_spec(cliente: TestClient) -> None:
    assert cliente.get(BUSCA).headers["content-security-policy"] == (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; font-src 'self'; connect-src 'self'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'; object-src 'none'"
    )


def test_assets_estaticos_levam_csp_e_nosniff(cliente: TestClient) -> None:
    for nome in ("app.css", "app.js"):
        resposta = cliente.get(assets().url(nome))

        assert resposta.status_code == 200, nome
        _com_cabecalho_de_seguranca(resposta.headers)


def test_asset_com_hash_errado_e_404_html_com_csp(cliente: TestClient) -> None:
    resposta = cliente.get("/app/static/000000000000-app.js")

    assert resposta.status_code == 404
    assert resposta.headers["content-type"].startswith("text/html")
    _com_cabecalho_de_seguranca(resposta.headers)


# -- 2. 304 e hit do LRU carregam o header -----------------------------------


def test_revalidacao_304_leva_csp(cliente: TestClient) -> None:
    primeira = cliente.get(FICHA)
    etag = primeira.headers["etag"]

    segunda = cliente.get(FICHA, headers={"If-None-Match": etag})

    assert segunda.status_code == 304
    assert segunda.content == b""
    _com_cabecalho_de_seguranca(segunda.headers)


def test_hit_do_lru_leva_csp_sem_consultar_o_repositorio(
    cliente: TestClient,
) -> None:
    primeira = cliente.get(FICHA)
    # `TestClient` guarda o app: o mesmo repositório fake conta as chamadas.
    repo: FakeRepository = cliente.app.state.repo
    chamadas = len(repo.methods_called())

    segunda = cliente.get(FICHA)

    assert segunda.status_code == 200
    assert segunda.text == primeira.text
    assert len(repo.methods_called()) == chamadas, "hit do LRU executou o handler"
    _com_cabecalho_de_seguranca(segunda.headers)


# -- 3. `/v1` não ganha header novo ------------------------------------------


def _sem_middleware_de_seguranca():
    """App igual, com o `WebSecurityHeadersMiddleware` retirado da pilha.

    É a linha de base da comparação: qualquer header novo em `/v1` aparece como
    diferença de conjunto em :func:`test_v1_nao_ganha_header_novo`.
    """
    app = create_app(settings=_settings(), repository=_repo())
    app.user_middleware = [
        m for m in app.user_middleware if m.cls is not WebSecurityHeadersMiddleware
    ]
    app.middleware_stack = None
    return app


@pytest.mark.parametrize(
    "caminho",
    [
        f"/v1/markets/{MUNICIPIO}?ano=2025",
        f"/v1/schools?co_entidade={ESCOLA}",
        # Dois erros problem+json: validação (400) e parâmetro inválido (422).
        "/v1/schools",
        "/v1/markets/3100000",
    ],
)
def test_v1_nao_ganha_header_novo(caminho: str) -> None:
    with TestClient(create_app(settings=_settings(), repository=_repo())) as atual:
        with TestClient(_sem_middleware_de_seguranca()) as base:
            resposta = atual.get(caminho)
            referencia = base.get(caminho)

    assert resposta.status_code == referencia.status_code, caminho
    assert set(resposta.headers) == set(referencia.headers), caminho
    _sem_cabecalho_novo(resposta.headers)
    if "problem+json" in resposta.headers["content-type"]:
        assert resposta.headers["content-type"].startswith("application/problem+json")


def test_v1_200_sem_header_novo() -> None:
    """O caminho de sucesso do contrato público é o que mais importa: 200, sem CSP."""
    with TestClient(create_app(settings=_settings(), repository=_repo())) as atual:
        with TestClient(_sem_middleware_de_seguranca()) as base:
            resposta = atual.get(f"/v1/markets/{MUNICIPIO}?ano=2025")
            referencia = base.get(f"/v1/markets/{MUNICIPIO}?ano=2025")

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("application/json")
    assert set(resposta.headers) == set(referencia.headers)
    _sem_cabecalho_novo(resposta.headers)


def test_health_nao_ganha_header_novo() -> None:
    with TestClient(create_app(settings=_settings(), repository=_repo())) as atual:
        with TestClient(_sem_middleware_de_seguranca()) as base:
            resposta = atual.get("/health")
            referencia = base.get("/health")

    assert set(resposta.headers) == set(referencia.headers)
    _sem_cabecalho_novo(resposta.headers)


# -- 4. o asset `app.js` -----------------------------------------------------


def test_app_js_e_servido_como_javascript_imutavel(cliente: TestClient) -> None:
    resposta = cliente.get(assets().url("app.js"))

    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "text/javascript; charset=utf-8"
    assert resposta.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert resposta.content == APP_JS.read_bytes()


def test_url_do_app_js_tem_hash_do_conteudo(cliente: TestClient) -> None:
    assert re.fullmatch(r"/app/static/[0-9a-f]{12}-app\.js", assets().url("app.js"))


# -- 5. guarda do markup das páginas -----------------------------------------


def _tags_script(html: str) -> list[str]:
    return re.findall(r"<script\b[^>]*>\s*</script>", html)


@pytest.mark.parametrize(("caminho", "status"), PAGINAS)
def test_pagina_carrega_exatamente_o_app_js_com_defer(
    cliente: TestClient, caminho: str, status: int
) -> None:
    # Sem seguir redirect: o 301 da concorrência antiga não tem HTML.
    resposta = cliente.get(caminho, follow_redirects=False)

    assert resposta.status_code == status, caminho
    if status == 301:
        # Redirect não tem corpo com tags: só a âncora de destino.
        assert resposta.headers["location"].endswith("#concorrencia"), caminho
        assert _tags_script(resposta.text) == [], caminho
        return
    tags = _tags_script(resposta.text)
    assert tags == [f'<script src="{assets().url("app.js")}" defer></script>'], (
        caminho,
        tags,
    )


@pytest.mark.parametrize(("caminho", "status"), PAGINAS)
def test_pagina_sem_inline_de_estilo_ou_script(
    cliente: TestClient, caminho: str, status: int
) -> None:
    # Sem seguir redirect: o corpo do 301 é vazio por definição.
    html = cliente.get(caminho, follow_redirects=False).text

    assert "<style" not in html, caminho
    _sem_style_fora_da_barra(html, caminho)
    assert not re.search(r"\son[a-z]+\s*=", html), caminho


#: Exceção única ao `style=`: a largura da barra de share (percentual real do
#: SSR, card V2 `t_cbd54a92`), só em `.barra-share__preenche`.
_STYLE_SHARE = re.compile(r'<span class="barra-share__preenche" style="width:[0-9.]+%">')


def _sem_style_fora_da_barra(html: str, caminho: str = "") -> None:
    """Nenhum `style=` fora da largura da barra de share."""
    sem_barra = _STYLE_SHARE.sub("", html)
    assert not re.search(r"\sstyle\s*=", sem_barra), caminho


def test_nenhum_template_tem_inline_ou_script_sem_src() -> None:
    for caminho in sorted(TEMPLATES.rglob("*.html")):
        texto = caminho.read_text(encoding="utf-8")

        for tag in _tags_script(texto):
            assert 'src="' in tag, f"{caminho.name}: script sem src: {tag}"
        assert "<style" not in texto, caminho.name
        _sem_style_fora_da_barra(texto, caminho.name)
        assert not re.search(r"\son[a-z]+\s*=", texto), caminho.name


# -- 6. orçamento e construções proibidas ------------------------------------


def test_app_js_cabe_no_orcamento_de_20480_bytes() -> None:
    tamanho = len(APP_JS.read_bytes())

    assert tamanho <= ORCAMENTO_APP_JS, f"app.js com {tamanho} bytes"


@pytest.mark.parametrize("proibido", PROIBIDOS_APP_JS)
def test_app_js_nao_usa_construcoes_incompativeis_com_a_csp(proibido: str) -> None:
    assert proibido not in APP_JS.read_text(encoding="utf-8"), proibido
