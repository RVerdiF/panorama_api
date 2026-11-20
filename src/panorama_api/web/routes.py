"""Router do front SSR sob `/app` e montagem do ambiente de templates.

Esta é a fundação (card F1): layout base, assets versionados por hash,
`/app/metodologia` e as páginas de erro HTML. As telas de busca, escola e
mercado entram nos cards F3–F5 e reutilizam este mesmo ambiente — por isso os
filtros, o registro de assets e as definições ficam num único módulo.

`/v1/*` não é tocado aqui: nenhum handler deste módulo serve JSON de dados.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from fastapi import APIRouter, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse

from panorama_api import __version__
from panorama_api.config import Settings
from panorama_api.contract import (
    CONTRACT,
    UNIVERSO_ESCOLAS_ATIVAS_MG,
    UNIVERSO_ESCOLAS_MG,
    UNIVERSO_PRIVADAS_ATIVAS_MG,
)
from panorama_api.core.errors import ErrorCode, ProblemError
from panorama_api.web import PREFIXO_WEB
from panorama_api.web.assets import CACHE_CONTROL_ASSET, AssetRegistry
from panorama_api.web.conteudo import (
    DEFINICAO_CONCORRENCIA,
    DEFINICOES,
    ROTULO_RETENCAO,
    traduzir_avisos,
)
from panorama_api.web.filters import fmt_nulo, fmt_oferta

DIRETORIO = Path(__file__).resolve().parent
TEMPLATES_DIR = DIRETORIO / "templates"
STATIC_DIR = DIRETORIO / "static"

#: Universo de cada tela, traduzido para leitura humana (contrato 2b R1).
UNIVERSOS: Mapping[str, str] = {
    UNIVERSO_ESCOLAS_MG: "Todas as escolas do recorte (inclui inativas).",
    UNIVERSO_PRIVADAS_ATIVAS_MG: "Escolas privadas ativas no ano de referência.",
    UNIVERSO_ESCOLAS_ATIVAS_MG: "Escolas ativas no ano de referência.",
}

#: Metadados de página para cada `ErrorCode`: (título da página, ação sugerida).
_PAGINAS_ERRO: Mapping[ErrorCode, tuple[str, str | None]] = {
    ErrorCode.FONTE_INDISPONIVEL: (
        "Fonte de dados temporariamente indisponível",
        "Nenhuma seção foi exibida parcialmente: aguarde e recarregue a página.",
    ),
    ErrorCode.NAO_ENCONTRADO: (
        "Não encontrado no recorte de Minas Gerais",
        "Confira o código ou o nome informado e volte à busca.",
    ),
    ErrorCode.ANO_FORA_DO_CONTRATO: (
        "Sem dados para este ano ou etapa",
        "Selecione outro ano ou etapa disponível no contrato.",
    ),
    ErrorCode.PARAMETRO_INVALIDO: (
        "Parâmetro inválido",
        "Corrija os campos indicados e envie novamente.",
    ),
    ErrorCode.ERRO_INTERNO: (
        "Erro interno",
        "O problema foi registrado; tente novamente em instantes.",
    ),
}

#: `Retry-After` obrigatório da página 503 (plano §5: nova tentativa em 5 min).
RETRY_AFTER_SEGUNDOS = 300
#: Erro nunca é cacheado — inclui o 503, que também não leva `ETag`.
CACHE_CONTROL_ERRO = "no-store"


@lru_cache
def assets() -> AssetRegistry:
    """Assets do front, carregados uma vez por processo (hash do conteúdo)."""
    return AssetRegistry(STATIC_DIR, prefixo=PREFIXO_WEB)


def templates() -> Jinja2Templates:
    """Ambiente Jinja2 do front com os filtros das regras de exibição."""
    return _templates()


@lru_cache
def _templates() -> Jinja2Templates:
    ambiente = Jinja2Templates(directory=str(TEMPLATES_DIR))
    ambiente.env.filters["fmt_nulo"] = fmt_nulo
    ambiente.env.filters["fmt_oferta"] = fmt_oferta
    return ambiente


def contexto_base(request: Request) -> dict[str, Any]:
    """Contexto comum a toda página: versões, CSS versionado e prefixo público."""
    settings = _settings(request)
    return {
        "app_prefix": PREFIXO_WEB,
        "app_version": __version__,
        "css_url": assets().url("app.css"),
        "contract": CONTRACT,
        "contract_version": settings.contract_version,
        "data_version": settings.data_version,
        # Links do front em caminho relativo: `url_for` devolve URL absoluta
        # (com host), o que não é desejável dentro do HTML servido.
        "href_metodologia": f"{PREFIXO_WEB}/metodologia",
    }


def pagina_erro(
    request: Request,
    problem: ProblemError,
    *,
    retry_after: int | None = None,
) -> Response:
    """Renderiza a página HTML de erro com o status e o cache corretos.

    Regras (plano §5): erro nunca é cacheado; ``503`` leva ``Retry-After``;
    nenhuma página de erro mostra stack trace ou SQL.
    """
    titulo, sugestao = _PAGINAS_ERRO.get(problem.code, ("Erro", None))
    contexto = {
        **contexto_base(request),
        "status": problem.status,
        "titulo": titulo,
        "detalhe": problem.detail,
        "codigo": problem.code.value,
        "erros": problem.errors,
        "instancia": request.url.path,
        "retry_after": retry_after,
        "sugestao": sugestao,
    }
    cabecalhos = {"Cache-Control": CACHE_CONTROL_ERRO}
    if retry_after:
        cabecalhos["Retry-After"] = str(retry_after)
    return templates().TemplateResponse(
        request, "erro.html", contexto, status_code=problem.status, headers=cabecalhos
    )


def _settings(request: Request) -> Settings:
    return request.app.state.settings


#: Router do front. O prefixo `/app` está no próprio router para que `url_for`
#: resolva os nomes `web_*` sem depender do registro em `main.create_app`.
router = APIRouter(prefix=PREFIXO_WEB, include_in_schema=False)


@router.get(
    "/metodologia",
    response_class=HTMLResponse,
    name="web_metodologia",
    summary="Metodologia, versão dos dados e definições semânticas",
)
def metodologia(request: Request) -> Response:
    """Página estática de metodologia: de onde vem cada número e com que limites."""
    contexto = {
        **contexto_base(request),
        "rotulo_retencao": ROTULO_RETENCAO,
        "definicao_retencao": DEFINICOES["retencao_liquida_proxy_pct"],
        "definicao_concorrencia": DEFINICAO_CONCORRENCIA,
        "definicoes": DEFINICOES,
        "avisos_conhecidos": {
            "IS_ABAIXO_PORTE": traduzir_avisos(["IS_ABAIXO_PORTE"])[0],
        },
        "universos": UNIVERSOS,
    }
    return templates().TemplateResponse(request, "metodologia.html", contexto)


@router.get(
    "/static/{caminho}",
    name="web_static",
    summary="Assets do front (nome com hash de conteúdo)",
)
def asset(caminho: str) -> Response:
    """Serve um asset imutável; caminho fora do registro é 404."""
    encontrado = assets().get(caminho)
    if encontrado is None:
        raise ProblemError(ErrorCode.NAO_ENCONTRADO, "asset não encontrado")
    return Response(
        content=encontrado.corpo,
        media_type=encontrado.media_type,
        headers={"Cache-Control": CACHE_CONTROL_ASSET},
    )


__all__ = [
    "CACHE_CONTROL_ERRO",
    "RETRY_AFTER_SEGUNDOS",
    "TEMPLATES_DIR",
    "assets",
    "contexto_base",
    "pagina_erro",
    "router",
    "templates",
]
