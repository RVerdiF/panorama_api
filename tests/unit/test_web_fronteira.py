"""Fronteira do front `/app` — a extração para `panorama_web` depende disto.

Este teste é o alarme que faltava: sem ele, um `from panorama_api.repositories
import ...` numa tela nova (F3–F5) passaria no review sem sinal e a extração do
front deixaria de ser mecânica (``docs/desacoplamento-web.md``).

Invariantes verificados, todos por AST (nada de grep textual):

1. nenhum arquivo de ``web/`` importa ``panorama_api.repositories``,
   ``panorama_api.api`` nem ``google.cloud``/BigQuery — o front não fala com a
   fonte de dados;
2. ``web/routes.py`` não importa ``panorama_api.services``: todo acesso a dado
   passa por ``web/dados.py``;
3. dentro de ``web/``, só ``dados.py`` importa ``panorama_api.services``;
4. fora de ``web/`` e de ``main.py``, nenhum módulo importa ``panorama_api.web``
   (direção única: app → web).

O detector não é vazio por construção: ``test_detector_flagra_cada_import_proibido``
injeta fontes sintéticas de cada forma proibida e exige que a violação apareça.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable, Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.core.errors import ProblemError
from panorama_api.main import create_app
from panorama_api.web import dados
from tests.unit.conftest import FakeRepository, school_row

SRC = Path(__file__).resolve().parents[2] / "src"
PACOTE = SRC / "panorama_api"
WEB = PACOTE / "web"

#: Módulos que o front não pode importar, por etapa do pipeline que eles tocam:
#: repositório/BigQuery = fonte de dados; `api` = camada HTTP do `/v1`.
IMPORTS_PROIBIDOS_NO_WEB = (
    "panorama_api.repositories",
    "panorama_api.api",
    "google",
)
#: `panorama_api.services` é permitido **apenas** em `web/dados.py` (a fachada).
MODULO_FACHADA = WEB / "dados.py"


# -- detector (AST) -----------------------------------------------------------


def _nome_do_modulo(caminho: Path) -> str:
    """Nome absoluto do módulo do arquivo (``panorama_api.web.routes``).

    É a base para resolver imports relativos. Arquivos fora do pacote (mutação
    em ``tmp_path``) não têm base implícita: o chamador passa ``nome_modulo``.
    """
    try:
        relativo = caminho.resolve().relative_to(PACOTE)
    except ValueError:
        return ""
    return ".".join(("panorama_api", *relativo.with_suffix("").parts))


def _modulo_resolvido(nome_modulo: str, no: ast.ImportFrom) -> str:
    """Resolve ``from .x import y`` / ``from .. import y`` para o nome absoluto.

    Semântica do Python: ``level`` é o número de pontos; o nível 1 é o pacote
    que contém o arquivo. ``web/x.py`` + ``from ..repositories import y``
    resolve para ``panorama_api.repositories``.
    """
    if not no.level:
        return no.module or ""
    partes = nome_modulo.split(".")[:-1] if nome_modulo else []
    saltos = no.level - 1
    if saltos:
        if saltos > len(partes):
            return ""  # relativo além do topo: nada sensato a resolver
        partes = partes[: len(partes) - saltos]
    if not partes:
        return ""
    return ".".join([*partes, *([no.module] if no.module else [])])


def _modulos_importados(caminho: Path, nome_modulo: str | None = None) -> set[str]:
    """Nomes de módulo importados, relativos já resolvidos ao nome absoluto.

    Inclui tanto o módulo quanto cada nome importado: ``from panorama_api
    import repositories`` produz ``panorama_api`` **e** ``panorama_api.repositories``.
    """
    modulo_do_arquivo = _nome_do_modulo(caminho) if nome_modulo is None else nome_modulo
    nomes: set[str] = set()
    for no in ast.walk(ast.parse(caminho.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            nomes.update(alias.name for alias in no.names)
        elif isinstance(no, ast.ImportFrom):
            base = _modulo_resolvido(modulo_do_arquivo, no)
            if base:
                nomes.add(base)
                nomes.update(
                    f"{base}.{alias.name}" for alias in no.names if alias.name != "*"
                )
    return nomes


def violacoes(
    caminho: Path,
    proibidos: Iterable[str] = IMPORTS_PROIBIDOS_NO_WEB,
    nome_modulo: str | None = None,
) -> list[str]:
    """Imports proibidos encontrados em ``caminho`` (vazio = fronteira respeitada)."""
    nomes = _modulos_importados(caminho, nome_modulo)
    return sorted(
        nome
        for nome in nomes
        for proibido in proibidos
        if nome == proibido or nome.startswith(proibido + ".")
    )


def _arquivos_do_web() -> list[Path]:
    return sorted(p for p in WEB.rglob("*.py") if "__pycache__" not in p.parts)


def _arquivos_fonte() -> list[Path]:
    return sorted(
        p
        for p in PACOTE.rglob("*.py")
        if "__pycache__" not in p.parts
        and WEB not in p.parents
        and p != PACOTE / "main.py"
    )


# -- 1. o front não fala com a fonte de dados ---------------------------------


def test_web_nao_importa_repositories_nem_api():
    """`web/` usa a fachada e o contrato; repositório e camada HTTP ficam fora."""
    encontrados = {p: v for p in _arquivos_do_web() if (v := violacoes(p))}
    assert not encontrados, f"imports proibidos em web/: {encontrados}"


def test_web_nao_abre_conexao_ou_cliente_bigquery():
    """Nenhum módulo do front importa `google.cloud`/BigQuery (nem por alias)."""
    arquivos = _arquivos_do_web()
    assert arquivos, "nenhum módulo de web/ encontrado — o teste não estaria testando nada"
    for caminho in arquivos:
        nomes = _modulos_importados(caminho)
        assert not [n for n in nomes if n == "google" or n.startswith("google.")], (
            f"{caminho.name} importa google.cloud/BigQuery: {sorted(nomes)}"
        )
        assert not [n for n in nomes if "bigquery" in n.lower()], (
            f"{caminho.name} importa um módulo de BigQuery: {sorted(nomes)}"
        )


# -- 2/3. ponto único de dados: `web/dados.py` --------------------------------


def test_rotas_nao_importam_services_direto():
    """Critério de aceite: `routes.py` sem `from panorama_api.services`."""
    assert not violacoes(WEB / "routes.py", ("panorama_api.services",))


def test_apenas_a_fachada_importa_services():
    """Dentro de `web/`, só `dados.py` conhece `services`."""
    infratores = [
        caminho
        for caminho in _arquivos_do_web()
        if caminho != MODULO_FACHADA and violacoes(caminho, ("panorama_api.services",))
    ]
    assert not infratores, f"telas devem consumir web/dados.py, não services: {infratores}"


def test_fachada_e_o_unico_reexportador_de_texto_de_contrato():
    """O texto de `meta.definicoes.competidores` chega às telas pela fachada."""
    fonte = (WEB / "conteudo.py").read_text(encoding="utf-8")
    assert "from panorama_api.web.dados import DESCRICAO_COMPETIDORES" in fonte
    assert dados.DESCRICAO_COMPETIDORES


# -- 4. direção única: app → web ---------------------------------------------


def test_fora_de_web_so_main_importa_web():
    """`main.py` monta o front; nenhum outro módulo de produção conhece `web`."""
    infratores = {
        caminho.relative_to(SRC).as_posix(): v
        for caminho in _arquivos_fonte()
        if (v := violacoes(caminho, ("panorama_api.web",)))
    }
    assert not infratores, f"imports de panorama_api.web fora de main.py: {infratores}"


# -- o detector não é vazio por construção -----------------------------------

SERVICOS = ("panorama_api.services",)
WEB_MODULO = ("panorama_api.web",)

#: (fonte, módulo do arquivo, proibidos). O módulo é necessário porque
#: ``tmp_path`` está fora do pacote: sem ele imports relativos não teriam base.
CASOS_PROIBIDOS = [
    # absolutos diretos
    ("from panorama_api.repositories.serving import ServingRepository\n", "panorama_api.web.tela", IMPORTS_PROIBIDOS_NO_WEB),
    ("from panorama_api.repositories import serving\n", "panorama_api.web.tela", IMPORTS_PROIBIDOS_NO_WEB),
    ("import panorama_api.repositories.serving\n", "panorama_api.web.tela", IMPORTS_PROIBIDOS_NO_WEB),
    ("from panorama_api.api.v1.schools import router\n", "panorama_api.web.tela", IMPORTS_PROIBIDOS_NO_WEB),
    ("from google.cloud import bigquery\n", "panorama_api.web.tela", IMPORTS_PROIBIDOS_NO_WEB),
    ("import google.cloud.bigquery\n", "panorama_api.web.tela", IMPORTS_PROIBIDOS_NO_WEB),
    # `from <pacote> import <submódulo>` — o nome está no alias, não no módulo
    ("from panorama_api import repositories\n", "panorama_api.web.tela", IMPORTS_PROIBIDOS_NO_WEB),
    ("from panorama_api import api\n", "panorama_api.web.tela", IMPORTS_PROIBIDOS_NO_WEB),
    ("from panorama_api import repositories as repo\n", "panorama_api.web.tela", IMPORTS_PROIBIDOS_NO_WEB),
    # relativos, resolvidos a partir do pacote do arquivo
    ("from ..repositories.serving import ServingRepository\n", "panorama_api.web.tela", IMPORTS_PROIBIDOS_NO_WEB),
    ("from .. import repositories\n", "panorama_api.web.tela", IMPORTS_PROIBIDOS_NO_WEB),
    ("from . import repositories\n", "panorama_api.tela", IMPORTS_PROIBIDOS_NO_WEB),
    # `services` também é fronteira: só `web/dados.py` importa
    ("from panorama_api.services import schools\n", "panorama_api.web.tela", SERVICOS),
    ("from panorama_api import services\n", "panorama_api.web.tela", SERVICOS),
    ("from ..services import schools\n", "panorama_api.web.tela", SERVICOS),
    ("from .. import services\n", "panorama_api.web.tela", SERVICOS),
    # `web` fora de `web/`: direção única app → web
    ("from panorama_api.web import PREFIXO_WEB\n", "panorama_api.config", WEB_MODULO),
    ("from panorama_api import web\n", "panorama_api.config", WEB_MODULO),
    ("from . import web\n", "panorama_api.config", WEB_MODULO),
]


@pytest.mark.parametrize(("fonte", "nome_modulo", "proibidos"), CASOS_PROIBIDOS)
def test_detector_flagra_cada_import_proibido(fonte, nome_modulo, proibidos, tmp_path):
    """Cada forma de import proibido é detectada — a fronteira falha se voltar."""
    arquivo = tmp_path / "tela_nova.py"
    arquivo.write_text(fonte, encoding="utf-8")
    encontrados = violacoes(arquivo, proibidos, nome_modulo)
    assert encontrados, f"detector não flagrou: {fonte!r} (módulo {nome_modulo})"


def test_detector_ignora_o_que_e_permitido(tmp_path):
    """Sanidade oposta: a fachada, o contrato e o próprio `web` passam."""
    arquivo = tmp_path / "ok.py"
    arquivo.write_text(
        "from panorama_api.web import PREFIXO_WEB\n"
        "from panorama_api.web.dados import buscar_escolas\n"
        "from panorama_api.contract import ETAPAS\n",
        encoding="utf-8",
    )
    assert not violacoes(arquivo, nome_modulo="panorama_api.web.tela")


def test_detector_resolve_viarios_niveis_relativos(tmp_path):
    """`.` sobe zero, `..` sobe um: ``web/x.py`` + `.dados` = ``panorama_api.web.dados``."""
    arquivo = tmp_path / "ok.py"
    arquivo.write_text("from .dados import buscar_escolas\n", encoding="utf-8")
    assert violacoes(arquivo, SERVICOS, "panorama_api.web.routes") == []
    assert _modulos_importados(arquivo, "panorama_api.web.routes") >= {
        "panorama_api.web.dados",
        "panorama_api.web.dados.buscar_escolas",
    }
    arquivo.write_text("from ..repositories import serving\n", encoding="utf-8")
    assert "panorama_api.repositories" in violacoes(
        arquivo, IMPORTS_PROIBIDOS_NO_WEB, "panorama_api.web.routes"
    )


def test_detector_flagra_import_de_servico_em_tela(tmp_path):
    arquivo = tmp_path / "tela_nova.py"
    arquivo.write_text("from panorama_api.services import schools\n", encoding="utf-8")
    assert "panorama_api.services" in violacoes(arquivo, SERVICOS)


# -- a fachada é só repasse: mesmo envelope do `/v1` -------------------------


@pytest.fixture
def contexto_web() -> Iterator[tuple[TestClient, FakeRepository]]:
    app_settings = Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        max_bytes_billed=256 * 1024 * 1024,
        validate_schema_on_startup=False,
        contract_version="mvp-1",
    )
    repo = FakeRepository(
        schools=[school_row(), school_row(co_entidade="31000002", no_entidade="ESCOLA DOIS")]
    )
    app = create_app(settings=app_settings, repository=repo)
    with TestClient(app) as client:
        yield client, repo


def _request(app: FastAPI) -> Request:
    return Request(
        {
            "type": "http",
            "app": app,
            "method": "GET",
            "scheme": "http",
            "path": "/app/",
            "root_path": "",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )


def test_fachada_devolve_o_mesmo_envelope_do_v1(contexto_web):
    """Repasse puro: a fachada e `GET /v1/schools` devolvem o mesmo corpo."""
    client, _repo = contexto_web
    do_v1 = client.get("/v1/schools", params={"co_municipio": "3106200"}).json()
    da_fachada = dados.buscar_escolas(
        _request(client.app), co_municipio="3106200"
    ).model_dump(mode="json")
    assert da_fachada == do_v1


def test_fachada_valida_antes_de_consultar_o_repositorio(contexto_web):
    """422 sem chamar o repositório (mesma garantia do `/v1`)."""
    client, repo = contexto_web
    with pytest.raises(ProblemError) as erro:
        dados.buscar_escolas(_request(client.app), q="ab")
    assert erro.value.status == 422
    assert repo.methods_called() == []


def test_fachada_nao_inventa_criterio_de_busca(contexto_web):
    """Sem `q`/`co_entidade`/`co_municipio` não há scan da mart: 400."""
    client, repo = contexto_web
    with pytest.raises(ProblemError) as erro:
        dados.buscar_escolas(_request(client.app))
    assert erro.value.status == 400
    assert repo.methods_called() == []
