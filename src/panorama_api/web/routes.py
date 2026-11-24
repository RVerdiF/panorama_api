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
from panorama_api.core import validation
from panorama_api.core.errors import ErrorCode, ProblemError, ano_fora_do_contrato, invalid
from panorama_api.web import PREFIXO_WEB, dados
from panorama_api.web.assets import CACHE_CONTROL_ASSET, AssetRegistry
from panorama_api.web.conteudo import (
    AVISOS_METODOLOGIA,
    DEFINICAO_CONCORRENCIA,
    DEFINICOES,
    ETAPAS_ROTULOS,
    ETAPA_PADRAO_MERCADO,
    EXPLICACAO_OFERTA_DESCONHECIDA,
    ROTULO_RETENCAO,
    TEXTO_OFERTA_DESCONHECIDA,
    UNIVERSOS,
    rotulo_etapa,
    traduzir_avisos,
)
from panorama_api.web.escola import (
    contexto_escola,
    item_mais_recente,
    pertence_ao_universo_privado,
)
from panorama_api.web.filters import (
    fmt_ano,
    fmt_celula,
    fmt_contagem,
    fmt_gap_lider,
    fmt_nulo,
    fmt_oferta,
)
from panorama_api.web.mercado import contexto_mercado
from panorama_api.web.municipios import municipios_mg
from panorama_api.web.paginacao import montar as montar_paginacao
from panorama_api.web.paginacao import url as url_lista

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

#: 404 de endereço que não é recurso de dados (rota inexistente): dizer
#: "recorte de Minas Gerais" seria falso — a página nem chegou a consultar dado
#: (achado C5 do card `t_3ea9454f`). Título e volta mandam o usuário para a
#: entrada do front.
TITULO_PAGINA_INEXISTENTE = "Página não encontrada"
SUGESTAO_PAGINA_INEXISTENTE = (
    "Confira o endereço digitado: ele não corresponde a nenhuma página deste site."
)


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
    ambiente.env.filters["fmt_contagem"] = fmt_contagem
    ambiente.env.filters["fmt_celula"] = fmt_celula
    ambiente.env.filters["fmt_oferta"] = fmt_oferta
    ambiente.env.filters["fmt_ano"] = fmt_ano
    ambiente.env.filters["fmt_gap_lider"] = fmt_gap_lider
    return ambiente


def contexto_base(request: Request, *, pagina: str | None = None) -> dict[str, Any]:
    """Contexto comum a toda página: versões, CSS versionado e prefixo público.

    ``pagina`` é a tela ativa do nav principal (``"busca"``/``"metodologia"``).
    Ela vira ``aria-current="page"`` no link correspondente; escola e mercado não
    aparecem no nav, então não marcam nenhum item (marcar "Busca" numa ficha de
    escola diria que o usuário está na busca, o que é falso).
    """
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
        "pagina_atual": pagina,
    }


def pagina_erro(
    request: Request,
    problem: ProblemError,
    *,
    retry_after: int | None = None,
    titulo: str | None = None,
    sugestao: str | None = None,
    acao: Mapping[str, str] | None = None,
) -> Response:
    """Renderiza a página HTML de erro com o status e o cache corretos.

    Regras (plano §5): erro nunca é cacheado; ``503`` leva ``Retry-After``;
    nenhuma página de erro mostra stack trace ou SQL.

    ``titulo``/``sugestao``/``acao`` sobrescrevem o texto da tabela por código:
    só o 404 de **endereço** inexistente precisa de outra mensagem (ver
    :func:`pagina_inexistente`). ``acao`` é ``{"href", "rotulo"}``.
    """
    titulo_padrao, sugestao_padrao = _PAGINAS_ERRO.get(problem.code, ("Erro", None))
    contexto = {
        **contexto_base(request),
        "status": problem.status,
        "titulo": titulo or titulo_padrao,
        "detalhe": problem.detail,
        "codigo": problem.code.value,
        "erros": problem.errors,
        "instancia": request.url.path,
        "retry_after": retry_after,
        "sugestao": sugestao or sugestao_padrao,
        "acao": acao,
    }
    cabecalhos = {"Cache-Control": CACHE_CONTROL_ERRO}
    if retry_after:
        cabecalhos["Retry-After"] = str(retry_after)
    return templates().TemplateResponse(
        request, "erro.html", contexto, status_code=problem.status, headers=cabecalhos
    )


def pagina_inexistente(request: Request, problem: ProblemError) -> Response:
    """404 de endereço que não existe — sem prometer recorte de dado nenhum.

    Rota inexistente não é busca de escola ou município: a página diz "Página
    não encontrada" e oferece a entrada do front, em vez de "Não encontrado no
    recorte de Minas Gerais" (achado C5 do card `t_3ea9454f`). Esse segundo
    texto continua valendo para escola e município, que são recursos do recorte
    MG e chegam aqui por `ProblemError` de `NAO_ENCONTRADO`.
    """
    return pagina_erro(
        request,
        problem,
        titulo=TITULO_PAGINA_INEXISTENTE,
        sugestao=SUGESTAO_PAGINA_INEXISTENTE,
        acao={"href": f"{PREFIXO_WEB}/", "rotulo": "Ir para a busca de escolas"},
    )


def _settings(request: Request) -> Settings:
    return request.app.state.settings


#: Router do front. O prefixo `/app` está no próprio router para que `url_for`
#: resolva os nomes `web_*` sem depender do registro em `main.create_app`.
router = APIRouter(prefix=PREFIXO_WEB, include_in_schema=False)


def _sugestoes_busca_vazia(
    *,
    termo: str,
    municipio: str,
    apenas_ativas: bool,
    filtros_pagina: Mapping[str, str],
) -> list[dict[str, str]]:
    """Próximos passos do resultado vazio da busca (achado C4).

    Cada item é ``{"lead", "href", "motivo"}``; ``href`` vazio significa dica
    de texto (sem link). Todo link é a **mesma** busca com um filtro a menos —
    nunca uma URL que devolveria outra página vazia ou um ``422``:

    * "menos letras" é texto quando há `q`; sem `q` a dica é informar o nome,
      porque reduzir letras de um termo inexistente não muda nada;
    * sem município: só quando há `q`; removê-lo sem `q` cairia na busca sem
      critério, que o próprio `/v1` recusa;
    * sem o filtro de ativas: sempre que ele está ligado, porque `q` e/ou
      `co_municipio` continuam na URL.
    """
    caminho = f"{PREFIXO_WEB}/"
    sugestoes: list[dict[str, str]] = []
    if termo:
        sugestoes.append(
            {
                "lead": "Use menos letras",
                "href": "",
                "motivo": "um trecho do começo do nome costuma bastar.",
            }
        )
    else:
        sugestoes.append(
            {
                "lead": "Informe o nome da escola",
                "href": "",
                "motivo": (
                    "trecho de 3 a 100 caracteres, combinado ou não com o município."
                ),
            }
        )
    if municipio and termo:
        sugestoes.append(
            {
                "lead": "Buscar sem o filtro de município",
                "href": url_lista(caminho, {**filtros_pagina, "co_municipio": ""}),
                "motivo": "restrita a um município, a busca não vê escolas de outro.",
            }
        )
    if apenas_ativas:
        sugestoes.append(
            {
                "lead": "Incluir escolas inativas",
                "href": url_lista(caminho, {**filtros_pagina, "apenas_ativas": ""}),
                "motivo": (
                    "o filtro de situação esconde escolas que já encerraram as "
                    "atividades."
                ),
            }
        )
    return sugestoes


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

    O `offset` é validado **antes** do atalho de busca vazia: com critério e sem
    critério, o mesmo valor fora de ``0..1000`` responde ``422`` (achado C7 do
    card `t_3ea9454f` — antes `?offset=2000` sozinho devolvia ``200``).
    """
    termo = (q or "").strip()
    municipio = (co_municipio or "").strip()
    deslocamento = validation.offset(offset)
    # Filtros preservados nos links de paginação; vazio não entra na URL.
    filtros_pagina = {
        "q": termo,
        "co_municipio": municipio,
        "apenas_ativas": "true" if apenas_ativas else "",
    }

    contexto: dict[str, Any] = {
        **contexto_base(request, pagina="busca"),
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
        # Anos publicados do front (o mesmo `APP_ANOS_DISPONIVEIS` do seletor do
        # mercado): o bloco de orientação anuncia o recorte real, nunca literal.
        "anos_disponiveis": list(_settings(request).anos_disponiveis),
        # Sem consulta o bloco "Recorte da busca" não tem o que declarar — em
        # especial `ano_referencia`, que sairia como "sem dado" e passaria a
        # impressão de base faltando (achado A3).
        "houve_consulta": bool(termo or municipio),
        # Sugestões do estado vazio (achado C4): cada uma é um próximo passo
        # concreto. O link "sem o município" só existe quando sobra outro
        # critério (`q`) — removê-lo sem `q` cairia na busca vazia, que é outro
        # beco sem saída.
        "sugestoes_vazio": _sugestoes_busca_vazia(
            termo=termo,
            municipio=municipio,
            apenas_ativas=apenas_ativas,
            filtros_pagina=filtros_pagina,
        ),
        "texto_oferta_desconhecida": TEXTO_OFERTA_DESCONHECIDA,
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
        offset=deslocamento,
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
        **contexto_base(request, pagina="metodologia"),
        "rotulo_retencao": ROTULO_RETENCAO,
        "definicao_retencao": DEFINICOES["retencao_liquida_proxy_pct"],
        "definicao_concorrencia": DEFINICAO_CONCORRENCIA,
        "definicoes": DEFINICOES,
        "explicacao_oferta_desconhecida": EXPLICACAO_OFERTA_DESCONHECIDA,
        # Avisos explicados na metodologia: título em português + o que ele muda
        # na leitura do número (código cru sozinho não é explicação).
        "avisos_conhecidos": AVISOS_METODOLOGIA,
        "universos": UNIVERSOS,
    }
    return templates().TemplateResponse(request, "metodologia.html", contexto)


@router.get(
    "/escolas/{co_entidade}",
    response_class=HTMLResponse,
    name="web_escola",
    summary="Visão da escola: série, oferta, rendimento e posição municipal",
)
def escola(co_entidade: str, request: Request, ano: int | None = None) -> Response:
    """Tela da escola (card F4).

    A série de `history` é obrigatória. Indicadores e comparação municipal só
    são consultados quando o item mais recente da série diz **privada ativa**:
    pública, inativa ou com dependência não informada não gasta cota nem
    fabrica seção. Um 404 residual de universo nessas duas consultas vira
    seção "não se aplica" na própria página (200); qualquer outro erro (503,
    422, 500) sobe para o handler global, e a página inteira vira a página de
    erro — nunca uma renderização parcial.

    `?ano=` não é um recorte válido desta tela: a ficha mostra a série inteira
    e o ano de referência é o mais recente da própria série. Aceitar o
    parâmetro e ignorá-lo faria a página responder 200 a um recorte que ela não
    aplicou — por isso, presente, ele vira ``422`` `PARAMETRO_INVALIDO` em vez
    de silêncio.
    """
    if ano is not None:
        raise invalid(
            "a tela da escola mostra a série inteira; o parâmetro ano não é "
            "suportado aqui — remova-o da URL",
            loc=("query", "ano"),
        )
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
    "/mercados/{co_municipio}",
    response_class=HTMLResponse,
    name="web_mercado",
    summary="Visão de mercado municipal: tamanho, composição e share",
)
def mercado(
    co_municipio: str,
    request: Request,
    ano: int | None = None,
    etapa: str | None = None,
    offset: int | None = None,
) -> Response:
    """Tela de mercado do município (card F5).

    * o ano sai de `APP_ANOS_DISPONIVEIS` (setting validado no boot); sem `ano`,
      o padrão é o **maior** ano da lista, nunca o ano corrente inventado;
    * `ANO_FORA_DO_CONTRATO` (ano fora da lista ou sem linha em `mart_mercado`)
      responde ``404`` com o seletor de outro ano — o recorte é substituível
      pelo usuário, não é erro de sistema;
    * share é sempre de **uma** etapa (`bas` quando não informada) e paginado
      (`limit=50`, só `page.has_more`); ``items: []`` é estado legítimo da tela.
    """
    settings = _settings(request)
    anos = settings.anos_disponiveis
    etapa_ref = (etapa or "").strip() or ETAPA_PADRAO_MERCADO
    filtros_pagina = {"ano": "", "etapa": etapa_ref}

    contexto: dict[str, Any] = {
        **contexto_base(request),
        "municipio": co_municipio,
        "anos_disponiveis": list(anos),
        "ano_selecionado": None,
        "etapa_selecionada": etapa_ref,
        "etapa_rotulo": rotulo_etapa(etapa_ref),
        "etapas_disponiveis": ETAPAS_ROTULOS,
        "href_base": f"{PREFIXO_WEB}/mercados/{co_municipio}",
        "sem_dados_ano": False,
    }

    try:
        ano_ref = _ano_do_seletor(ano, anos)
        filtros_pagina["ano"] = str(ano_ref)
        # A composição por etapa é a tela inteira: sem recorte de etapa.
        resposta_mercado = dados.mercado(
            request, co_municipio=co_municipio, ano=ano_ref, etapa=None
        )
        resposta_share = dados.share_mercado(
            request,
            co_municipio=co_municipio,
            ano=ano_ref,
            etapa=etapa_ref,
            entidade_tipo="escola",
            limit=dados.LIMITE_SHARE_PADRAO,
            offset=offset,
        )
    except ProblemError as erro:
        if erro.code is not ErrorCode.ANO_FORA_DO_CONTRATO:
            raise
        # Recorte de ano/etapa substituível pelo usuário: a página responde 404
        # e mostra o seletor, sem consultar nada mais e sem cache.
        contexto.update(
            sem_dados_ano=True,
            ano_selecionado=ano if ano is not None else max(anos),
            detalhe=erro.detail,
            codigo=erro.code.value,
            pagina_erro_titulo=_PAGINAS_ERRO[erro.code][0],
        )
        return templates().TemplateResponse(
            request,
            "mercado.html",
            contexto,
            status_code=erro.status,
            headers={"Cache-Control": CACHE_CONTROL_ERRO},
        )

    contexto.update(
        contexto_mercado(
            mercado=resposta_mercado,
            share=resposta_share,
            anos_disponiveis=anos,
            caminho=f"{PREFIXO_WEB}/mercados/{co_municipio}",
            filtros_pagina=filtros_pagina,
            montar_paginacao=montar_paginacao,
            url_lista=url_lista,
        )
    )
    return templates().TemplateResponse(request, "mercado.html", contexto)


def _ano_do_seletor(ano: int | None, anos: tuple[int, ...]) -> int:
    """Resolve o ano pedido contra `APP_ANOS_DISPONIVEIS`.

    Ausente → maior ano da lista. Presente mas fora da lista → ``404``
    `ANO_FORA_DO_CONTRATO` (o seletor oferece os anos válidos). O `int` da
    query já é validado por `dados.mercado`; aqui só a pertença ao seletor.
    """
    if ano is None:
        return max(anos)
    if ano not in anos:
        raise ano_fora_do_contrato(
            f"ano {ano} fora de APP_ANOS_DISPONIVEIS "
            f"({', '.join(str(item) for item in anos)})"
        )
    return ano


@router.get(
    "/static/{caminho}",
    name="web_static",
    summary="Assets do front (nome com hash de conteúdo)",
)
def asset(caminho: str, request: Request) -> Response:
    """Serve um asset imutável; caminho fora do registro é 404 de endereço."""
    encontrado = assets().get(caminho)
    if encontrado is None:
        # Nome de asset inválido é endereço quebrado (link antigo, hash errado),
        # não recurso do recorte MG: mesma página do 404 de rota.
        return pagina_inexistente(
            request, ProblemError(ErrorCode.NAO_ENCONTRADO, "asset não encontrado")
        )
    return Response(
        content=encontrado.corpo,
        media_type=encontrado.media_type,
        headers={"Cache-Control": CACHE_CONTROL_ASSET},
    )


__all__ = [
    "CACHE_CONTROL_ERRO",
    "META_BUSCA",
    "RETRY_AFTER_SEGUNDOS",
    "SUGESTAO_PAGINA_INEXISTENTE",
    "TEMPLATES_DIR",
    "TITULO_PAGINA_INEXISTENTE",
    "assets",
    "contexto_base",
    "pagina_erro",
    "pagina_inexistente",
    "router",
    "templates",
]
