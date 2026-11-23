"""Router do front SSR sob `/app` e montagem do ambiente de templates.

Esta é a fundação (card F1): layout base, assets versionados por hash,
`/app/metodologia` e as páginas de erro HTML. A tela da escola vive aqui
desde o card F4; busca (F3) e mercado (F5) reutilizam o mesmo ambiente —
por isso os filtros, o registro de assets e as definições ficam num único
módulo.

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
    FONTE_BASE,
    FONTE_ORGAO,
    UNIVERSO_ESCOLAS_MG,
)
from panorama_api.core.errors import ErrorCode, ProblemError
from panorama_api.web import PREFIXO_WEB, dados
from panorama_api.web.assets import CACHE_CONTROL_ASSET, AssetRegistry
from panorama_api.web.conteudo import (
    DEFINICAO_CONCORRENCIA,
    DEFINICOES,
    ROTULO_RETENCAO,
    UNIVERSOS,
    rotulo_etapa,
    traduzir_avisos,
)
from panorama_api.web.escola import (
    contexto_escola,
    item_mais_recente,
    pertence_ao_universo_privado,
)
from panorama_api.web.filters import fmt_ano, fmt_gap_lider, fmt_nulo, fmt_oferta
from panorama_api.web.municipios import municipios_mg
from panorama_api.web.paginacao import montar as montar_paginacao

DIRETORIO = Path(__file__).resolve().parent
TEMPLATES_DIR = DIRETORIO / "templates"
STATIC_DIR = DIRETORIO / "static"

#: Recorte fixo da tela de busca — o mesmo de `GET /v1/schools` (`dim_escola`,
#: MG, etapa BAS). Usado quando ainda não houve consulta: a tela declara de onde
#: virão ano, etapa, universo, fonte e avisos em vez de omitir o recorte.
META_BUSCA: Mapping[str, Any] = {
    "ano_referencia": None,
    "etapa": "bas",
    "universo": UNIVERSO_ESCOLAS_MG,
    "fonte": {"orgao": FONTE_ORGAO, "base": FONTE_BASE, "tabela": "dim_escola"},
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
    ambiente.env.filters["fmt_ano"] = fmt_ano
    ambiente.env.filters["fmt_gap_lider"] = fmt_gap_lider
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
        # Busca é a página inicial do front (caminho relativo, sem `url_for`).
        "href_busca": f"{PREFIXO_WEB}/",
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
    "/",
    response_class=HTMLResponse,
    name="web_busca",
    summary="Busca de escolas por nome ou município",
)
def busca(
    request: Request,
    q: str | None = None,
    co_municipio: str | None = None,
    apenas_ativas: bool = False,
    offset: int | None = None,
) -> Response:
    """Busca de escolas (= ``GET /v1/schools``) por nome, município ou ambos.

    Regras do card F3:

    * sem critério não há consulta: a página responde ``200`` com a mensagem de
      "nenhuma escola" e o repositório **não** é chamado;
    * parâmetro inválido (`q` com menos de 3 caracteres, município fora de
      ``^31\\d{5}$``, `offset` fora de ``0..1000``) vira ``422`` **antes** de
      qualquer acesso ao repositório — a validação é a mesma do `/v1`;
    * paginação é decidida só por ``page.has_more`` (o contrato não tem
      `total`) e o offset nunca passa do teto do contrato.
    """
    termo = (q or "").strip()
    municipio = (co_municipio or "").strip()
    # Filtros preservados nos links de paginação; vazio não entra na URL.
    filtros_pagina = {
        "q": termo,
        "co_municipio": municipio,
        "apenas_ativas": "true" if apenas_ativas else "",
    }

    contexto: dict[str, Any] = {
        **contexto_base(request),
        "filtros": {
            "q": termo,
            "co_municipio": municipio,
            "apenas_ativas": apenas_ativas,
        },
        "municipios": municipios_mg(),
        "resposta": None,
        "escolas": [],
        "paginacao": None,
        "meta": META_BUSCA,
        "etapa_rotulo": rotulo_etapa(META_BUSCA["etapa"]),
        "universo_descricao": UNIVERSOS[UNIVERSO_ESCOLAS_MG],
        "avisos": None,
    }

    if not termo and not municipio:
        # Busca vazia: nada de scan da mart (o `/v1` responderia 400). A tela
        # apenas anuncia que ainda não há escola listada.
        return templates().TemplateResponse(request, "busca.html", contexto)

    resposta = dados.buscar_escolas(
        request,
        q=termo or None,
        co_municipio=municipio or None,
        apenas_ativas=apenas_ativas,
        limit=dados.LIMITE_BUSCA_PADRAO,
        offset=offset,
    )
    meta = resposta.meta
    contexto.update(
        resposta=resposta,
        escolas=resposta.data,
        meta=meta,
        etapa_rotulo=rotulo_etapa(meta.etapa),
        universo_descricao=UNIVERSOS.get(meta.universo, ""),
        avisos=traduzir_avisos(meta.avisos),
        paginacao=montar_paginacao(
            resposta.page, caminho=f"{PREFIXO_WEB}/", filtros=filtros_pagina
        ),
    )
    return templates().TemplateResponse(request, "busca.html", contexto)


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
    "/escolas/{co_entidade}",
    response_class=HTMLResponse,
    name="web_escola",
    summary="Visão da escola: série, oferta, rendimento e posição municipal",
)
def escola(co_entidade: str, request: Request) -> Response:
    """Tela da escola (card F4).

    A série de `history` é obrigatória. Indicadores e comparação municipal só
    são consultados quando o item mais recente da série diz **privada ativa**:
    pública, inativa ou com dependência não informada não gasta cota nem
    fabrica seção. Um 404 residual de universo nessas duas consultas vira
    seção "não se aplica" na própria página (200); qualquer outro erro (503,
    422, 500) sobe para o handler global, e a página inteira vira a página de
    erro — nunca uma renderização parcial.
    """
    historico = dados.historico_escola(request, co_entidade=co_entidade)

    indicadores = concorrentes = None
    nao_se_aplica: list[str] = []
    if pertence_ao_universo_privado(item_mais_recente(historico.data.items)):
        indicadores, ausente = _secao_opcional(
            lambda: dados.indicadores_escola(request, co_entidade=co_entidade)
        )
        if ausente:
            nao_se_aplica.append("indicadores")
        concorrentes, ausente = _secao_opcional(
            lambda: dados.concorrentes_escola(request, co_entidade=co_entidade)
        )
        if ausente:
            nao_se_aplica.append("competidores")

    contexto = {
        **contexto_base(request),
        **contexto_escola(
            historico=historico,
            indicadores=indicadores,
            concorrentes=concorrentes,
            nao_se_aplica=nao_se_aplica,
        ),
    }
    return templates().TemplateResponse(request, "escola.html", contexto)


def _secao_opcional(consulta: Any) -> tuple[Any | None, bool]:
    """Executa uma consulta que pode não se aplicar à escola.

    Só ``404 NAO_ENCONTRADO`` é absorvido (estado legítimo de universo: a seção
    "não se aplica"). ``503`` e demais códigos sobem — página inteira de erro.
    O ``detail`` do 404 não vai para a tela: é diagnóstico da API, e a
    explicação exibida é texto fixo de `web/conteudo.py`. A tupla devolvida é
    ``(resposta, nao_se_aplica)``.
    """
    try:
        return consulta(), False
    except ProblemError as erro:
        if erro.code is not ErrorCode.NAO_ENCONTRADO:
            raise
        return None, True


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
    "META_BUSCA",
    "RETRY_AFTER_SEGUNDOS",
    "TEMPLATES_DIR",
    "assets",
    "contexto_base",
    "pagina_erro",
    "router",
    "templates",
]
