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
from fastapi.responses import RedirectResponse, Response
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
from panorama_api.web import CAMINHO_INICIO, PREFIXO_WEB, dados
from panorama_api.web.assets import CACHE_CONTROL_ASSET, AssetRegistry
from panorama_api.web.conteudo import (
    AVISOS_METODOLOGIA,
    DEFINICAO_CONCORRENCIA,
    DEFINICOES,
    ETAPAS_ROTULOS,
    ETAPA_PADRAO_MERCADO,
    EXPLICACAO_OFERTA_DESCONHECIDA,
    MOTIVO_SECAO_INDICADORES,
    ROTULO_COMPARAR_COM_ESTA,
    ROTULO_RETENCAO,
    TEXTO_OFERTA_DESCONHECIDA,
    UNIVERSOS,
    anos_publicados,
    rotulo_etapa,
    traduzir_avisos,
)
from panorama_api.web.escola import (
    AVISO_ABAIXO_PORTE,
    contexto_comparacao,
    contexto_concorrencia,
    contexto_concorrencia_na_ficha,
    contexto_concorrencia_nao_se_aplica,
    contexto_visao_geral,
    item_mais_recente,
    kpis_da_escola,
    rotulo_dependencia,
    rotulo_situacao,
    texto_variacao,
)
from panorama_api.web.filters import (
    fmt_ano,
    fmt_bruto,
    fmt_celula,
    fmt_contagem,
    fmt_gap_lider,
    fmt_nulo,
    fmt_oferta,
)
from panorama_api.web.mercado import (
    ESCOLAS,
    ROTULO_ESCOLAS_MERCADO,
    VISAO_GERAL,
    contexto_escolas_mercado,
    contexto_share_visao_geral,
    contexto_visao_geral as contexto_mercado_visao_geral,
    itens_subnav,
    kpis_mercado,
)
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

#: Atalho do hero da landing (`GET /app/mercados?co_municipio=`): sem município
#: escolhido não há o que redirecionar (spec §6). A página diz o que fazer e
#: volta para a landing, onde o formulário está.
TITULO_ATALHO_SEM_MUNICIPIO = "Escolha um município"
SUGESTAO_ATALHO_SEM_MUNICIPIO = (
    "Para ver o mercado, selecione um município no formulário."
)
ACAO_ATALHO_SEM_MUNICIPIO = {"href": CAMINHO_INICIO, "rotulo": "Voltar ao início"}

#: Comparação lado a lado (card C4): rota própria e o teto de escolas do card.
#: Dois ids no máximo; a URL canônica é a ordem crescente (`A,B` ≡ `B,A`).
CAMINHO_COMPARAR = f"{PREFIXO_WEB}/comparar"
MAXIMO_ESCOLAS_COMPARADAS = 2


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
    ambiente.env.filters["fmt_bruto"] = fmt_bruto
    ambiente.env.filters["fmt_oferta"] = fmt_oferta
    ambiente.env.filters["fmt_ano"] = fmt_ano
    ambiente.env.filters["fmt_gap_lider"] = fmt_gap_lider
    ambiente.env.filters["variacao_texto"] = texto_variacao
    return ambiente


def contexto_base(
    request: Request,
    *,
    pagina: str | None = None,
    area: str | None = None,
) -> dict[str, Any]:
    """Contexto comum a toda página: versões, CSS versionado e prefixo público.

    ``pagina`` é a tela ativa do nav principal — uma das três entradas
    (``"escolas"``/``"municipios"``/``"metodologia"``). Ela vira
    ``aria-current="page"`` no item correspondente.

    ``area`` marca a **área** dona de uma tela-filha (ficha → ``"escolas"``;
    mercado → ``"municipios"``); o item da área recebe ``aria-current="true"``.
    É marcação mais fraca que ``"page"`` de propósito: a tela não é o índice da
    área, mas pertence a ela. Antes os itens nomeavam telas e a ficha não podia
    marcar nada (spec §2.1). ``inicio`` e as páginas de erro não passam nenhum
    dos dois: não pertencem a nenhuma área da navbar.
    """
    settings = _settings(request)
    return {
        "app_prefix": PREFIXO_WEB,
        "app_version": __version__,
        "css_url": assets().url("app.css"),
        # CSS do protótipo vendorizado (D1-a): arquivos byte a byte do design,
        # publicados pelo mesmo registro — com hash, sem duplicar hash no
        # template. Entram ANTES do `app.css`, que agora contém só o app-only
        # e sobrescreve o protótipo na cascata.
        "css_prototipo_url": assets().url("panorama.css"),
        "css_prototipo_telas_url": assets().url("panorama-telas.css"),
        # Inter 400 é a fonte do corpo: o `<head>` faz `preload` dela para o
        # texto não esperar o parse do CSS (card V1 `t_423aa547`). A URL sai do
        # mesmo registro — com hash, servida pelo app.
        "fonte_corpo_url": assets().url("inter-400.woff2"),
        # Base única de JS do front (card `t_71b25279`): mesmo registro de
        # assets, mesma URL com hash, carregada com `defer` no `<head>`.
        "js_url": assets().url("app.js"),
        "contract": CONTRACT,
        "contract_version": settings.contract_version,
        "data_version": settings.data_version,
        # Links do front em caminho relativo: `url_for` devolve URL absoluta
        # (com host), o que não é desejável dentro do HTML servido.
        "href_metodologia": f"{PREFIXO_WEB}/metodologia",
        # Entrada do sistema: o logo do topo volta para a landing, não para a
        # busca (card `t_386b791c`). `/app/` continua sendo a busca.
        "href_inicio": CAMINHO_INICIO,
        # Busca é a página principal do front (caminho relativo, sem `url_for`).
        "href_busca": f"{PREFIXO_WEB}/",
        # Índice de municípios (spec §1): escolher o mercado de um município.
        # A barra final é a rota do índice, não a do atalho `/app/mercados`.
        "href_mercados": f"{PREFIXO_WEB}/mercados/",
        "pagina_atual": pagina,
        "area_atual": area,
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

#: Router da página de entrada. Sem prefixo: a landing mora na raiz `/`, fora do
#: `/app` da busca (card `t_386b791c`). `GET` **e** `HEAD` porque o `FastAPI` não
#: deriva `HEAD` do `GET`: sem a rota explícita, `curl -I /` receberia `405`.
router_inicio = APIRouter(include_in_schema=False)


@router_inicio.api_route(
    CAMINHO_INICIO,
    methods=["GET", "HEAD"],
    response_class=HTMLResponse,
    name="web_inicio",
    summary="Página de entrada (landing)",
)
def inicio(request: Request) -> Response:
    """Landing em `/`: hero do produto com o painel do recorte (card `t_437796c3`).

    Substitui o redirect `307` → `/app/` (card `t_0c84b91f`): quem chega na
    raiz vê a apresentação do produto e o link para a busca, e quem tem `/app/`
    em favorito ou link compartilhado continua caindo direto nas escolas.

    O painel da coluna direita troca a foto da referência visual por três
    números que saem do **código e da config**, nunca de literal no template:

    * municípios: `len(municipios_mg())` — lista IBGE versionada, arquivo de
      apoio de tela, sem BigQuery;
    * anos: `settings.anos_disponiveis` (`APP_ANOS_DISPONIVEIS`), já validado e
      canônico no boot;
    * etapas e modalidades: chaves de `ETAPAS_ROTULOS` sem `"bas"`, que é o
      total do Censo e não uma etapa (spec §4).

    Nenhum desses números custa consulta: não há contagem de escolas porque
    `COUNT(*)` é proibido (`repositories/bigquery/pagination.py:1-5`). Zero
    chamadas ao repositório. Como :func:`panorama_api.web.e_caminho_web` inclui
    a raiz, a resposta ganha gzip, `ETag`/`Cache-Control: private, no-cache` com
    304 e a linha `page_view`, e um erro inesperado aqui vira página HTML
    (nunca `application/problem+json`).
    """
    contexto = contexto_base(request)
    municipios = municipios_mg()
    contexto.update(
        # As 853 opções da barra de busca do hero saem da mesma lista versionada
        # da busca (`GET /app/`); lista de apoio de tela, zero consulta.
        municipios=municipios,
        recorte_municipios=len(municipios),
        recorte_anos=anos_publicados(_settings(request).anos_disponiveis),
        # `"bas"` é o total oficial do Censo, não uma etapa do mercado.
        recorte_etapas=sum(1 for etapa in ETAPAS_ROTULOS if etapa != "bas"),
    )
    return templates().TemplateResponse(request, "inicio.html", contexto)


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
        **contexto_base(request, pagina="escolas"),
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
        # Rótulos dos códigos INEP por linha (rodada 1 da revisão, item 4): a
        # busca mostra o código com a leitura ("4 — Privada"), igual à ficha.
        "rotulo_dependencia": rotulo_dependencia,
        "rotulo_situacao": rotulo_situacao,
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
    summary="Visão geral da escola: série, oferta e rendimento",
)
def escola(co_entidade: str, request: Request, ano: int | None = None) -> Response:
    """Visão geral da escola (card F4; rota separada no NAV-2).

    A série de `history` é a **única** consulta: cabeçalho, identificação,
    oferta do ano recente, série e rendimento saem dela. Indicadores e
    comparação municipal vivem em :func:`escola_concorrencia`
    (`/app/escolas/{id}/concorrencia`), para que abrir a ficha custe 1 consulta
    ao BigQuery em vez de 3 (spec §5).

    Quando o item mais recente da série diz que a escola não é privada ativa, a
    página explica que a seção de indicadores não se aplica — sem consultar as
    marts privadas (falha fechada) e sem esconder a ausência.

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

    contexto: dict[str, Any] = {
        **contexto_base(request, area="escolas"),
        **contexto_visao_geral(historico=historico),
        "rotulo_retencao": ROTULO_RETENCAO,
    }

    # Fusão da Visão geral com indicadores/concorrência (card V2 `t_cbd54a92`):
    # a ficha é uma página só, com âncoras `#resumo`/`#concorrencia`. Para escola
    # privada ativa, uma segunda consulta (`indicadores_escola`) alimenta KPIs,
    # posição por crescimento e ranking; pública/inativa não paga essa consulta
    # (falha fechada). Um `404` do `/v1` aqui é ausência de linha na mart — a
    # seção diz "não se aplica" com o motivo, nunca 0.
    indicador = None
    competicao = None
    aviso_abaixo_porte = False
    if contexto["motivo_concorrencia"] is None:
        try:
            resposta_indicadores = dados.indicadores_escola(
                request, co_entidade=co_entidade
            )
        except ProblemError as erro:
            if erro.code is not ErrorCode.NAO_ENCONTRADO:
                raise
            contexto["motivo_concorrencia"] = MOTIVO_SECAO_INDICADORES
        else:
            recente_indicador = item_mais_recente(list(resposta_indicadores.data.items))
            indicador = recente_indicador
            competicao = (
                recente_indicador.competicao if recente_indicador is not None else None
            )
            aviso_abaixo_porte = AVISO_ABAIXO_PORTE in resposta_indicadores.meta.avisos

    contexto["kpis"] = kpis_da_escola(
        recente=contexto["recente"], item=indicador, competicao=competicao
    )
    contexto.update(
        contexto_concorrencia_na_ficha(
            item=indicador,
            competicao=competicao,
            cabecalho=contexto["cabecalho"],
            aviso_abaixo_porte=aviso_abaixo_porte,
        )
    )
    return templates().TemplateResponse(request, "escola.html", contexto)


@router.get(
    "/escolas/{co_entidade}/concorrencia",
    response_class=HTMLResponse,
    name="web_escola_concorrencia",
    summary="Rota legada: redireciona para #concorrencia na ficha",
)
def escola_concorrencia(
    co_entidade: str, request: Request, ano: int | None = None
) -> Response:
    """Endereço legado de indicadores/concorrência → ``301`` para a ficha.

    Os indicadores e a comparação municipal passaram a viver na **própria**
    ficha, na âncora ``#concorrencia`` (card V2 `t_cbd54a92`). O endereço antigo
    continua **válido** como ``301`` — links compartilhados e favoritos chegam à
    seção certa, e nenhuma página duplicada é servida. `?ano=` continua ``422``
    (a ficha ignora recorte de ano) e o código INEP é validado no formato antes
    do redirecionamento, sem consultar o repositório.
    """
    if ano is not None:
        raise invalid(
            "a ficha mostra a série inteira; o parâmetro ano não é suportado "
            "aqui — remova-o da URL",
            loc=("query", "ano"),
        )
    validation.co_entidade(co_entidade)
    return RedirectResponse(
        url=f"{PREFIXO_WEB}/escolas/{co_entidade}#concorrencia",
        status_code=301,
    )


def _escola_do_recorte(request: Request, co_entidade: str) -> Any | None:
    """Linha de `dim_escola` da escola, ou ``None`` quando ela não existe em MG.

    Usa o seam de dados do front (`buscar_escolas`), nunca o repositório: é a
    mesma consulta de identidade da busca. Só é chamada no caminho de 404 da
    rota de concorrência, para separar "não existe" de "fora do universo".
    """
    try:
        resposta = dados.buscar_escolas(request, co_entidade=co_entidade)
    except ProblemError as erro:
        if erro.code is not ErrorCode.NAO_ENCONTRADO:
            raise
        return None
    return resposta.data[0] if resposta.data else None


@router.get(
    "/comparar",
    response_class=HTMLResponse,
    name="web_comparar",
    summary="Comparação entre duas escolas (série e oferta, sem JS)",
)
def comparar(
    request: Request,
    escolas: str | None = None,
    q: str | None = None,
) -> Response:
    """Comparação SSR de **uma ou duas** escolas (card C4, `t_58f9adbb`).

    Contrato da rota:

    * ``escolas=<id>[,<id>]`` com ids de 8 dígitos, no **mesmo** formato
      validado da ficha. Zero ids, mais de dois, id inválido ou id repetido →
      ``422`` HTML, antes de qualquer consulta;
    * **URL canônica**: dois ids fora da ordem crescente respondem ``308`` para
      ``?escolas=A,B`` — assim ``A,B`` e ``B,A`` compartilham uma única chave de
      `ETag`/LRU, e o custo dobrado por *miss* não é pago duas vezes;
    * com **um** id, a página mostra a escola A e o formulário de busca
      (``q``, a mesma validação da busca por nome); os resultados trazem o link
      "Comparar com esta" já na forma canônica. ``q`` com dois ids → ``422``:
      a rota não aplicaria a busca, e ignorar o parâmetro em silêncio mentiria
      sobre o recorte.

    Dados: **as mesmas** funções da ficha (`dados.historico_escola`), uma
    consulta por escola — série e oferta saem do mesmo item e a página não
    consulta indicadores nem comparação municipal. Um ``404`` de escola
    inexistente sobe e vira a página 404 do front.
    """
    ids = _ids_da_comparacao(escolas)
    duas = len(ids) == MAXIMO_ESCOLAS_COMPARADAS
    if duas:
        if q is not None:
            raise invalid(
                "a busca por nome só existe na página com uma escola; remova q "
                "para comparar as duas",
                loc=("query", "q"),
            )
        if ids != tuple(sorted(ids)):
            return RedirectResponse(
                url=f"{CAMINHO_COMPARAR}?escolas={','.join(sorted(ids))}",
                status_code=308,
            )
        termo = None
    else:
        termo = validation.search_term((q or "").strip() or None)

    # Uma consulta por escola (série + oferta); nenhuma outra leitura.
    historicos = [
        dados.historico_escola(request, co_entidade=co_entidade) for co_entidade in ids
    ]

    contexto: dict[str, Any] = {
        **contexto_base(request, area="escolas"),
        **contexto_comparacao(historicos=historicos),
        "caminho_comparar": CAMINHO_COMPARAR,
        "escolas_param": ids[0],
        "filtros": {"q": termo or ""},
        "resultados": [],
        "resultados_tem_mais": False,
        "texto_comparar_com_esta": ROTULO_COMPARAR_COM_ESTA,
    }
    if duas:
        return templates().TemplateResponse(request, "comparar.html", contexto)

    if termo:
        resposta = dados.buscar_escolas(
            request, q=termo, limit=dados.LIMITE_BUSCA_PADRAO
        )
        contexto.update(
            resultados=[
                _resultado_comparavel(escola, ids[0]) for escola in resposta.data
            ],
            resultados_tem_mais=resposta.page.has_more,
        )
    return templates().TemplateResponse(request, "comparar.html", contexto)


def _ids_da_comparacao(valor: str | None) -> tuple[str, ...]:
    """Ids de ``?escolas=``: um ou dois, formato da ficha, sem repetição.

    A validação de formato é a **mesma** de `core.validation.co_entidade`
    (reusada, não reescrita); só o `loc` do erro aponta o parâmetro desta
    rota, para a página 422 mandar corrigir `escolas` e não `co_entidade`.
    """
    brutos = [parte.strip() for parte in (valor or "").split(",")]
    if len(brutos) > MAXIMO_ESCOLAS_COMPARADAS:
        raise invalid(
            "a comparação aceita no máximo duas escolas (escolas=<id>[,<id>])",
            loc=("query", "escolas"),
        )
    ids: list[str] = []
    for parte in brutos:
        try:
            ids.append(validation.co_entidade(parte, loc="query"))
        except ProblemError as erro:
            raise invalid(erro.detail, loc=("query", "escolas")) from erro
    if len(set(ids)) != len(ids):
        raise invalid(
            "a comparação precisa de duas escolas diferentes",
            loc=("query", "escolas"),
        )
    return tuple(ids)


def _resultado_comparavel(escola: Any, co_entidade_a: str) -> dict[str, Any]:
    """Resultado da busca já com o link canônico para comparar.

    ``co_entidade`` ausente na resposta não gera link (sem chave não há URL).
    A própria escola A também não: ``?escolas=A,A`` seria ``422`` por id
    repetido — o link existiria para levar a uma página de erro.
    """
    co_entidade = getattr(escola, "co_entidade", None)
    href = None
    if co_entidade and co_entidade != co_entidade_a:
        href = f"{CAMINHO_COMPARAR}?escolas={','.join(sorted((co_entidade_a, co_entidade)))}"
    return {"escola": escola, "href_comparar": href}


@router.get(
    "/mercados",
    response_class=HTMLResponse,
    name="web_mercado_atalho",
    include_in_schema=False,
    summary="Atalho do hero: mercado do município escolhido",
)
def mercado_atalho(request: Request, co_municipio: str | None = None) -> Response:
    """Atalho `GET /app/mercados?co_municipio=` → tela do mercado (spec §6).

    É o segundo botão da barra de busca do hero: o `<form>` é ``GET /app/``, e
    o botão leva ``formaction="/app/mercados"``. A rota **só** redireciona:

    * ``co_municipio`` válido (``^31\\d{5}$``, a mesma validação de
      `core.validation`) → **303** `Location: /app/mercados/{co}`, ignorando
      `q` e qualquer outro parâmetro que o form tenha enviado;
    * ausente, vazio ou inválido → **422** em HTML (`pagina_erro`), com
      "Escolha um município" e a volta para a landing.

    Nenhum caminho consulta o repositório: o código do município é só sintaxe
    de URL, e a tela de destino é quem valida a existência do recorte. O
    `303` é o certo para um GET que só aponta para outra URL (o navegador
    refaz a requisição como `GET` em `/app/mercados/{co}` e nunca reenvia o
    formulário). Como o cache de páginas só trata ``200``, a resposta sai sem
    `ETag` e sem `Cache-Control` de página.
    """
    try:
        codigo = validation.co_municipio(co_municipio or "", loc="query")
    except ProblemError as erro:
        return pagina_erro(
            request,
            erro,
            titulo=TITULO_ATALHO_SEM_MUNICIPIO,
            sugestao=SUGESTAO_ATALHO_SEM_MUNICIPIO,
            acao=ACAO_ATALHO_SEM_MUNICIPIO,
        )
    return RedirectResponse(
        url=f"{PREFIXO_WEB}/mercados/{codigo}", status_code=303
    )


@router.get(
    "/mercados/",
    response_class=HTMLResponse,
    name="web_mercados_indice",
    summary="Índice de municípios: escolher o mercado",
)
def mercados_indice(request: Request, co_municipio: str | None = None) -> Response:
    """Índice de municípios (spec §1): a página que escolhe o mercado a abrir.

    Sem ``co_municipio``, responde ``200`` com o formulário de escolha; com um
    código válido (``^31\\d{5}$``), **303** para ``/app/mercados/{co}``, para que
    recarregar não reenvie o formulário; com código inválido, ``422`` em HTML
    com a volta para este índice.

    Nenhum caminho consulta o repositório: a lista sai de ``municipios_mg()``
    (arquivo versionado de apoio de tela) e o código é só sintaxe de URL — quem
    valida a existência do recorte é a tela de destino. Zero BigQuery.
    """
    if co_municipio is None:
        contexto = {
            **contexto_base(request, pagina="municipios"),
            "municipios": municipios_mg(),
        }
        return templates().TemplateResponse(request, "mercados_indice.html", contexto)

    try:
        codigo = validation.co_municipio(co_municipio, loc="query")
    except ProblemError as erro:
        return pagina_erro(
            request,
            erro,
            acao={
                "href": f"{PREFIXO_WEB}/mercados/",
                "rotulo": "Escolher um município",
            },
        )
    return RedirectResponse(url=f"{PREFIXO_WEB}/mercados/{codigo}", status_code=303)


@router.get(
    "/mercados/{co_municipio}",
    response_class=HTMLResponse,
    name="web_mercado",
    summary="Visão geral do mercado: tamanho, composição e cobertura",
)
def mercado(
    co_municipio: str,
    request: Request,
    ano: int | None = None,
    etapa: str | None = None,
    offset: int | None = None,
) -> Response:
    """**Visão geral** do mercado do município (cards F5 e NAV-3).

    * o ano sai de `APP_ANOS_DISPONIVEIS` (setting validado no boot); sem `ano`,
      o padrão é o **maior** ano da lista, nunca o ano corrente inventado;
    * `ANO_FORA_DO_CONTRATO` (ano fora da lista ou etapa sem linha em
      `mart_mercado`) responde ``404`` com o seletor de outro ano — o recorte é
      substituível pelo usuário, não é erro de sistema;
    * a composição é consultada **sem** recorte de etapa (a tela cobre todas);
      a etapa selecionada vale para cobertura, entrada/saída e denominadores;
    * o top-10 do share é consultado aqui (a mesma etapa do recorte,
      `limit=10`): a tabela do painel "Escolas do mercado por share" sai de
      `dados.share_mercado` e a lista completa e paginada continua em
      `/app/mercados/{co_municipio}/escolas` (card V2 `t_cbd54a92`, rodada 1,
      item 2);
    * ``offset`` não é recorte desta tela: presente, responde ``422``
      `PARAMETRO_INVALIDO` em vez de silêncio — a paginação é do ranking.
    """
    if offset is not None:
        raise invalid(
            "a Visão geral do mercado não pagina; use "
            f"{PREFIXO_WEB}/mercados/{co_municipio}/escolas para o ranking",
            loc=("query", "offset"),
        )

    settings = _settings(request)
    anos = settings.anos_disponiveis
    etapa_ref = (etapa or "").strip() or ETAPA_PADRAO_MERCADO
    caminho = f"{PREFIXO_WEB}/mercados/{co_municipio}"

    contexto: dict[str, Any] = {
        **contexto_base(request, area="municipios"),
        **_contexto_comum_mercado(
            co_municipio=co_municipio,
            anos=anos,
            ano=ano,
            etapa=etapa_ref,
            caminho=caminho,
            caminho_mercado=caminho,
            ativo=VISAO_GERAL,
        ),
    }

    try:
        ano_ref = _ano_do_seletor(ano, anos)
        # `?etapa=` fora do contrato é 422 já aqui: esta rota não consulta o
        # share, que era quem validava a etapa antes da divisão (NAV-3).
        etapa_ref = _etapa_do_seletor(etapa)
        # A composição por etapa é a tela inteira: sem recorte de etapa.
        resposta_mercado = dados.mercado(
            request, co_municipio=co_municipio, ano=ano_ref, etapa=None
        )
        _exige_etapa_publicada(resposta_mercado, etapa_ref)
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

    contexto.update(contexto_mercado_visao_geral(mercado=resposta_mercado, etapa=etapa_ref))
    # Top-10 do share na própria Visão geral (card V2 `t_cbd54a92`, rodada 1,
    # item 2): a mesma etapa do recorte, primeira página. A lista completa e
    # paginada continua em `/app/mercados/{co}/escolas`.
    resposta_share = dados.share_mercado(
        request,
        co_municipio=co_municipio,
        ano=ano_ref,
        etapa=etapa_ref,
        entidade_tipo="escola",
        limit=10,
        offset=0,
    )
    contexto.update(contexto_share_visao_geral(share=resposta_share))
    contexto["kpis"] = kpis_mercado(
        denominadores=contexto["denominadores"], ano=contexto["ano_selecionado"]
    )
    # A identidade do município vem da resposta do `/v1` nesta rota (a lista
    # local só cobre o ranking, cuja resposta de share não traz o nome). Sem
    # nome publicado, o código IBGE ocupa o lugar — nunca um título sem
    # identificação.
    nome_resposta = resposta_mercado.data.no_municipio or co_municipio
    contexto["municipio_nome"] = nome_resposta
    contexto["migalhas"][-1]["rotulo"] = nome_resposta
    return templates().TemplateResponse(request, "mercado.html", contexto)


@router.get(
    "/mercados/{co_municipio}/escolas",
    response_class=HTMLResponse,
    name="web_mercado_escolas",
    summary="Escolas do mercado: ranking de share paginado",
)
def mercado_escolas(
    co_municipio: str,
    request: Request,
    ano: int | None = None,
    etapa: str | None = None,
    offset: int | None = None,
) -> Response:
    """**Escolas do mercado** — ranking de share paginado (card NAV-3, spec §5.3).

    Consulta **só** `dados.share_mercado` (3 consultas / ~203,5 MB); a
    composição por etapa não é recomputada a cada página e o ranking deixou de
    pesar na abertura da Visão geral.

    * o ano sai de `APP_ANOS_DISPONIVEIS`; sem `ano`, o **maior** da lista;
    * `ANO_FORA_DO_CONTRATO` (ano fora da lista ou sem linha para o recorte)
      responde ``404`` com o seletor de outro ano, sem cache;
    * share é sempre de **uma** etapa (`bas` quando não informada) e paginado
      (`limit=50`, só `page.has_more`); ``items: []`` é estado legítimo da tela;
    * ``offset`` é recorte desta rota (a Visão geral responde 422 a ele).
    """
    settings = _settings(request)
    anos = settings.anos_disponiveis
    etapa_ref = (etapa or "").strip() or ETAPA_PADRAO_MERCADO
    caminho_mercado = f"{PREFIXO_WEB}/mercados/{co_municipio}"
    caminho = f"{caminho_mercado}/escolas"
    filtros_pagina = {"ano": "", "etapa": etapa_ref}

    contexto: dict[str, Any] = {
        **contexto_base(request, area="municipios"),
        **_contexto_comum_mercado(
            co_municipio=co_municipio,
            anos=anos,
            ano=ano,
            etapa=etapa_ref,
            caminho=caminho,
            caminho_mercado=caminho_mercado,
            ativo=ESCOLAS,
        ),
    }

    try:
        ano_ref = _ano_do_seletor(ano, anos)
        filtros_pagina["ano"] = str(ano_ref)
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
        contexto.update(
            sem_dados_ano=True,
            ano_selecionado=ano if ano is not None else max(anos),
            detalhe=erro.detail,
            codigo=erro.code.value,
            pagina_erro_titulo=_PAGINAS_ERRO[erro.code][0],
        )
        return templates().TemplateResponse(
            request,
            "mercado_escolas.html",
            contexto,
            status_code=erro.status,
            headers={"Cache-Control": CACHE_CONTROL_ERRO},
        )

    contexto.update(
        contexto_escolas_mercado(
            share=resposta_share,
            caminho=caminho,
            filtros_pagina=filtros_pagina,
            montar_paginacao=montar_paginacao,
            url_lista=url_lista,
        )
    )
    return templates().TemplateResponse(request, "mercado_escolas.html", contexto)


def _contexto_comum_mercado(
    *,
    co_municipio: str,
    anos: tuple[int, ...],
    ano: int | None,
    etapa: str,
    caminho: str,
    caminho_mercado: str,
    ativo: str,
) -> dict[str, Any]:
    """Contexto que o seletor e o subnav precisam nas duas rotas do mercado.

    Vale para a página 200 e para a 404 de `ANO_FORA_DO_CONTRATO`: a 404 também
    oferece outro ano/etapa e a navegação para a outra seção. Os links do
    subnav levam `ano` e `etapa` do recorte atual (sem `offset`); um ano fora de
    `APP_ANOS_DISPONIVEIS` não é propagado — o link usaria um recorte que a
    outra rota recusaria do mesmo jeito.
    """
    filtros_subnav = {
        "ano": str(ano if ano in anos else max(anos)),
        "etapa": etapa,
    }
    nome = _nome_municipio(co_municipio)
    migalhas: list[dict[str, Any]] = [
        {"rotulo": "Busca", "href": f"{PREFIXO_WEB}/"},
    ]
    if ativo == ESCOLAS:
        # O município é link para a Visão geral; a tela atual fecha a trilha.
        migalhas.append({"rotulo": nome, "href": caminho_mercado})
        migalhas.append({"rotulo": ROTULO_ESCOLAS_MERCADO, "href": None})
    else:
        migalhas.append({"rotulo": nome, "href": None})
    return {
        "municipio": co_municipio,
        "municipio_nome": nome,
        "migalhas": migalhas,
        "anos_disponiveis": list(anos),
        "ano_selecionado": ano if ano is not None else max(anos),
        "etapa_selecionada": etapa,
        "etapa_rotulo": rotulo_etapa(etapa),
        "etapas_disponiveis": ETAPAS_ROTULOS,
        "href_base": caminho,
        "sem_dados_ano": False,
        "subnav_itens": itens_subnav(
            caminho=caminho_mercado,
            filtros=filtros_subnav,
            ativo=ativo,
            url_lista=url_lista,
        ),
    }


def _etapa_do_seletor(etapa: str | None) -> str:
    """Etapa do seletor, validada contra o contrato (`422` quando inválida).

    Vazia/ausente → `bas`, a mesma etapa padrão do share. A validação mora no
    `core.validation` usado pelo `/v1`; aqui só se antecipa o 422 que antes
    vinha da consulta de share.
    """
    informada = (etapa or "").strip()
    if not informada:
        return ETAPA_PADRAO_MERCADO
    return validation.etapa(informada, required=True)


def _exige_etapa_publicada(resposta: Any, etapa: str) -> None:
    """404 `ANO_FORA_DO_CONTRATO` quando a etapa não tem linha em `mart_mercado`.

    A composição é consultada sem etapa, então uma etapa válida no contrato mas
    sem publicação não falha sozinha: sem esta checagem a Visão geral mostraria
    cobertura e movimento de uma etapa inexistente. O comportamento é o que o
    share já tinha (`404` com seletor para trocar de etapa).
    """
    if all(item.etapa != etapa for item in resposta.data.items):
        raise ano_fora_do_contrato(
            f"sem linha em mart_mercado para a etapa {etapa} neste município e ano"
        )


def _nome_municipio(co_municipio: str) -> str:
    """Nome de exibição do município — lista IBGE versionada, zero BigQuery.

    O ranking (`/escolas`) só consulta o share, e a resposta do `/v1` não traz
    o nome do município. A lista de apoio das telas resolve `<title>`,
    subtítulo e breadcrumb sem consulta extra; código fora da lista continua
    identificado pelo próprio código, como antes.
    """
    return next(
        (m.no_municipio for m in municipios_mg() if m.co_municipio == co_municipio),
        co_municipio,
    )


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
    "router_inicio",
    "templates",
]
