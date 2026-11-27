"""Router do front SSR sob `/app` e montagem do ambiente de templates.

Esta é a fundação (card F1): layout base, assets versionados por hash,
`/app/metodologia` e as páginas de erro HTML. A tela da escola vive aqui
desde o card F4; busca (F3) e mercado (F5) reutilizam o mesmo ambiente —
por isso os filtros, o registro de assets e as definições ficam num único
módulo.

`/v1/*` não é tocado aqui: nenhum handler deste módulo serve JSON de dados.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode

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
from panorama_api.core.errors import (
    ErrorCode,
    ProblemError,
    UpstreamUnavailable,
    ano_fora_do_contrato,
    invalid,
)
from panorama_api.web import CAMINHO_INICIO, PREFIXO_WEB, dados
from panorama_api.web.assets import CACHE_CONTROL_ASSET, AssetRegistry
from panorama_api.web.conteudo import (
    AVISOS_METODOLOGIA,
    DEFINICAO_CONCORRENCIA,
    DEFINICOES,
    ETAPAS_ROTULOS,
    ETAPA_PADRAO_MERCADO,
    EXPLICACAO_OFERTA_DESCONHECIDA,
    MARQUISE_MUNICIPIOS,
    MOTIVO_SECAO_INDICADORES,
    ROTULO_COMPARAR_COM_ESTA,
    ROTULO_RETENCAO,
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
    contexto_escolas_mercado,
    contexto_visao_geral as contexto_mercado_visao_geral,
    itens_subnav,
    kpis_mercado,
)
from panorama_api.services.indice import IndiceMunicipios
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


#: Município da prancha da landing: Belo Horizonte, o mesmo do design e da
#: marquise (card `t_e06e1ad5`). O nome vem de `municipios_mg()` (lista
#: versionada, sem consulta ao repositório) — vale o mesmo que
#: `get_municipio("3106200").no_municipio` a custo zero.
CO_MUNICIPIO_LANDING = "3106200"
#: Top-N do ranking da landing: a prancha é o 1º, as barras são os 5.
TOP_LANDING = 5


def _nome_municipio_landing() -> str | None:
    """Nome do município da prancha, da lista versionada (sem repositório)."""
    for municipio in municipios_mg():
        if municipio.co_municipio == CO_MUNICIPIO_LANDING:
            return municipio.no_municipio
    return None


def _linha_concentracao_privadas(
    linhas: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Linha de concentração do recorte privado das escolas (o C4 da landing).

    O C4 do contrato é exatamente "as 4 maiores somadas", então a linha
    procurada é a do recorte `privado` no nível `escola`. Sem ela, a
    landing diz "sem dado" — nunca um C4 de outro recorte.
    """
    for linha in linhas:
        if linha.get("recorte") == "privado" and linha.get("nivel") == "escola":
            return linha
    return None


#: Larguras quantizadas das barras da landing (`share/max`, passo 5). A rota
#: emite uma delas por barra via `_classe_largura`, o `landing.css` define
#: `--w` para cada uma, e o conjunto valida a emissão (fora dele cai para
#: `bw-0`). O par `classe` literal mantém a trava de órfãos
#: (`test_app_only_nao_declara_classe_orfa`) ciente das 21 classes dinâmicas.
CLASSES_LARGURA_BW = {
    "classe": "bw-0 bw-5 bw-10 bw-15 bw-20 bw-25 bw-30 bw-35 bw-40 bw-45 bw-50 bw-55 bw-60 bw-65 bw-70 bw-75 bw-80 bw-85 bw-90 bw-95 bw-100"
}


def _classe_largura(share: float | None, max_share: float | None) -> str:
    """Classe quantizada da largura da barra (`bw-0` a `bw-100`, passo 5).

    A largura é `share/max_share`, quantizada em passos de 5 pontos (o CSS
    define `--w` por classe, sem `style=` inline — a CSP é `style-src 'self'`).
    Sem dado (`None`), sem máximo ou máximo zerado: `bw-0`. Fração positiva
    que quantiza para 0 ganha o mínimo visível `bw-5`. A classe emitida é
    sempre uma das declaradas em `CLASSES_LARGURA_BW` (o `landing.css`
    define `--w` para cada uma); fora do conjunto, `bw-0`.
    """
    if share is None or max_share is None:
        return "bw-0"
    try:
        fracao = float(share) / float(max_share)
    except (TypeError, ValueError, ZeroDivisionError):
        return "bw-0"
    if not fracao > 0:
        return "bw-0"
    quantizada = int(round(fracao * 100 / 5)) * 5
    quantizada = max(0, min(100, quantizada))
    if quantizada == 0:
        return "bw-5"
    classe = f"bw-{quantizada}"
    return classe if classe in CLASSES_LARGURA_BW["classe"].split() else "bw-0"


def _cache_landing(request: Request) -> dict[tuple[str, str], dict[str, Any]]:
    """Cache em processo da landing, invalidado por `DATA_VERSION`.

    A chave é `(data_version, anos)`: dado novo invalida sozinho, e cada app
    (cada teste hermético) tem o próprio dict — sem vazar linha entre apps.
    Só o sucesso é guardado; falha ou parcial recalcula no próximo render
    (para a página se recuperar sozinha quando o BigQuery voltar).
    """
    cache = getattr(request.app.state, "landing_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        request.app.state.landing_cache = cache
    return cache


def _contar(valor: int | float | None) -> str:
    """Número cru para `data-contar` (o `landing.js` ignora vazio/NaN).

    `float` integral vira inteiro (`1140`, não `1140.0`); ausência vira string
    vazia — o texto "sem dado" fica intacto e o contador não anima. Nunca `0`
    por ausência: o atributo some junto com o dado.
    """
    if valor is None or isinstance(valor, bool):
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor)


#: Abscissas da prancha para os 5 anos do recorte (o `viewBox` tem 480 de
#: largura; os rótulos de ano usam as mesmas posições via `anos_svg`).
_XS_PRANCHA = (84, 176, 268, 360, 452)
#: Ordenadas do gráfico: do topo (25) à base (175) das linhas de grade.
_Y_TOPO_PRANCHA = 25
_Y_BASE_PRANCHA = 175


def _serie_prancha(
    linhas: list[dict[str, Any]],
    *,
    anos: list[int],
    nome_destaque: str | None,
) -> tuple[dict[str, Any] | None, str, str]:
    """Série da prancha a partir do `get_school_history` da escola em destaque.

    Devolve `(serie_dados, delta_texto, serie_desc)`: os pontos `(x, y)` na
    escala do `viewBox`, a variação anual calculada da própria série (último
    ano contra o anterior, via `texto_variacao`) e o texto do `<desc>`.
    Qualquer ausência (sem destaque, sem linha, valor ausente ou nulo) vira
    `(None, "sem dado no ano", ...)` — nunca ponto inventado, nunca `0`.
    """
    por_ano = {linha.get("nu_ano_censo"): linha for linha in linhas}
    valores: list[float | None] = []
    for ano in anos:
        linha = por_ano.get(ano)
        valor = linha.get("qt_mat_bas") if linha else None
        if isinstance(valor, bool):
            valor = None
        valores.append(valor if valor is None else float(valor))
    if nome_destaque:
        desc = f"Série de matrícula de {nome_destaque}: "
    else:
        desc = "Série de matrícula: "
    if any(valor is None for valor in valores):
        return None, "sem dado no ano", desc + "sem dado."
    assert all(valor is not None for valor in valores)
    reais = [float(valor) for valor in valores]  # type: ignore[misc]
    minimo, maximo = min(reais), max(reais)
    if maximo == minimo:
        ordenadas = [100.0 for _ in reais]
    else:
        amplitude = maximo - minimo
        ordenadas = [
            _Y_BASE_PRANCHA
            - (valor - minimo) / amplitude * (_Y_BASE_PRANCHA - _Y_TOPO_PRANCHA)
            for valor in reais
        ]
    if len(anos) == len(_XS_PRANCHA):
        xs = list(_XS_PRANCHA)
    elif len(anos) == 1:
        xs = [268]
    else:
        passo = (_XS_PRANCHA[-1] - _XS_PRANCHA[0]) / (len(anos) - 1)
        xs = [_XS_PRANCHA[0] + round(i * passo) for i in range(len(anos))]
    pontos = [[x, round(y, 1)] for x, y in zip(xs, ordenadas)]
    linha_path = "M " + " L ".join(f"{x},{y:.1f}" for x, y in pontos)
    area_path = (
        f"{linha_path} L {xs[-1]},{_Y_BASE_PRANCHA} L {xs[0]},{_Y_BASE_PRANCHA} Z"
    )
    anterior, ultimo = reais[-2], reais[-1]
    variacao = (ultimo - anterior) / anterior * 100 if anterior else None
    desc += ", ".join(f"{ano}={int(valor)}" for ano, valor in zip(anos, reais))
    return (
        {"area": area_path, "linha": linha_path, "pontos": pontos},
        texto_variacao(variacao),
        desc + ".",
    )


def _contexto_landing(
    *,
    ano_ref: int,
    anos: list[int],
    nome_municipio: str | None,
    destaque: dict[str, Any] | None,
    barras: list[dict[str, Any]],
    total_privadas: int | float | None,
    c4_pct: float | None,
    serie_dados: dict[str, Any] | None,
    delta_texto: str,
    serie_desc: str,
) -> dict[str, Any]:
    """Monta o contexto da landing a partir das 4 consultas (ou do vazio).

    Ausência é `None` do início ao fim: o template formata com os filtros de
    `web/filters.py` (`None` vira "sem dado", nunca `0`).
    """
    destaque = destaque or {}
    return {
        "ano_ref": ano_ref,
        "anos": anos,
        "anos_svg": list(zip(anos, (84, 176, 268, 360, 452))),
        "nome_municipio": nome_municipio,
        "destaque_nome": destaque.get("no_entidade"),
        "destaque_mat": destaque.get("mat_entidade"),
        "destaque_mat_contar": _contar(destaque.get("mat_entidade")),
        "destaque_share": destaque.get("share_privado_pct"),
        "barras": barras,
        "total_privadas": total_privadas,
        "total_contar": _contar(total_privadas),
        "c4_pct": c4_pct,
        "c4_contar": _contar(c4_pct),
        # A série histórica e a variação anual vêm do `get_school_history`
        # da escola em destaque (a 4ª consulta). Sem ela, "sem dado".
        # A oferta por etapa continua fora do orçamento: a matriz usa o
        # estado "desconhecido" do próprio design (o "sem dado" da oferta).
        "serie_dados": serie_dados,
        "delta_texto": delta_texto,
        "serie_desc": serie_desc,
        "proveniencia": f"Fonte: {FONTE_BASE} ({FONTE_ORGAO}) · {ano_ref}",
    }


@router_inicio.api_route(
    CAMINHO_INICIO,
    methods=["GET", "HEAD"],
    response_class=HTMLResponse,
    name="web_inicio",
    summary="Página de entrada (landing)",
)
def inicio(request: Request) -> Response:
    """Landing em `/`: estrutura literal do protótipo, valores do repositório.

    O HTML é o `<body>` de `panorama-escola-landing.html` (card `t_e42049c1`):
    copy, classes, `id`, `aria-*`, `data-reveal`, `data-od-id` — verbatim.
    Os valores que eram mock do protótipo (card `t_e06e1ad5`) agora vêm do
    repositório, no máximo 4 consultas por render, todas do recorte fixo
    (Belo Horizonte, maior ano de `APP_ANOS_DISPONIVEIS`, etapa padrão):

    1. `get_market_share(..., limit=5)` — escola em destaque (a 1ª) e as 5
       barras do ranking (nome + `mat_entidade` + `share_privado_pct`);
    2. `get_market(...)` — total de privadas (`n_escolas_privadas`, o "de N"
       da posição e o KPI de escolas);
    3. `get_concentracao(...)` — `c4_pct` do recorte privado das escolas (o KPI
       "participação somada das 4 maiores escolas");
    4. `get_school_history(...)` — série de matrícula da escola em destaque
       (o gráfico da prancha e a variação anual, calculada da própria série).

    O nome do município vem de `municipios_mg()` (lista versionada, custo
    zero) e o resultado é cacheado em processo por `DATA_VERSION` — mas só o
    sucesso completo: com escola em destaque, o histórico (`serie_dados`)
    precisa existir para cachear; sem ele o parcial recalcula no próximo
    render e a página se recupera sozinha quando o BigQuery voltar. Se o
    BigQuery falhar, `/` continua `200` e cada bloco cai para "sem dado" —
    nunca `500`, nunca `0`. Como :func:`panorama_api.web.e_caminho_web`
    inclui a raiz, a resposta ganha gzip, `ETag`/`Cache-Control: private,
    no-cache` com 304 e a linha `page_view`, e um erro inesperado fora das
    consultas vira página HTML (nunca `application/problem+json`).
    """
    settings = _settings(request)
    anos = list(settings.anos_disponiveis)
    ano_ref = max(anos)
    chave = (settings.data_version, settings.app_anos_disponiveis)
    cache = _cache_landing(request)
    if chave in cache:
        landing = cache[chave]
    else:
        repositorio, _ = dados.fonte(request)
        try:
            linhas_share = repositorio.get_market_share(
                co_municipio=CO_MUNICIPIO_LANDING,
                ano=ano_ref,
                etapa=ETAPA_PADRAO_MERCADO,
                entidade_tipo="escola",
                limit=TOP_LANDING,
                offset=0,
            )
        except Exception:
            linhas_share = []
        try:
            linhas_market = repositorio.get_market(
                co_municipio=CO_MUNICIPIO_LANDING,
                ano=ano_ref,
                etapa=ETAPA_PADRAO_MERCADO,
            )
        except Exception:
            linhas_market = []
        try:
            linhas_conc = repositorio.get_concentracao(
                co_municipio=CO_MUNICIPIO_LANDING,
                ano=ano_ref,
                etapa=ETAPA_PADRAO_MERCADO,
            )
        except Exception:
            linhas_conc = []
        destaque = linhas_share[0] if linhas_share else None
        barras = [
            {
                "nome": linha.get("no_entidade"),
                "share": linha.get("share_privado_pct"),
            }
            for linha in linhas_share[:TOP_LANDING]
        ]
        while len(barras) < TOP_LANDING:
            barras.append({"nome": None, "share": None})
        max_share = max(
            (float(barra["share"]) for barra in barras if barra["share"] is not None),
            default=None,
        )
        for barra in barras:
            barra["classe"] = _classe_largura(barra["share"], max_share)
        linha_market = next(
            (
                linha
                for linha in linhas_market
                if linha.get("etapa") == ETAPA_PADRAO_MERCADO
            ),
            linhas_market[0] if linhas_market else None,
        )
        linha_conc = _linha_concentracao_privadas(linhas_conc)
        try:
            co_destaque = (destaque or {}).get("id_entidade")
            linhas_hist = (
                repositorio.get_school_history(
                    co_entidade=co_destaque,
                    ano_inicio=anos[0],
                    ano_fim=anos[-1],
                )
                if co_destaque
                else []
            )
        except Exception:
            linhas_hist = []
        serie_dados, delta_texto, serie_desc = _serie_prancha(
            linhas_hist,
            anos=anos,
            nome_destaque=(destaque or {}).get("no_entidade"),
        )
        landing = _contexto_landing(
            ano_ref=ano_ref,
            anos=anos,
            nome_municipio=_nome_municipio_landing(),
            destaque=destaque,
            barras=barras,
            total_privadas=(linha_market or {}).get("n_escolas_privadas"),
            c4_pct=(linha_conc or {}).get("c4_pct"),
            serie_dados=serie_dados,
            delta_texto=delta_texto,
            serie_desc=serie_desc,
        )
        if linhas_share and linhas_market and linhas_conc and (
            serie_dados is not None if destaque else True
        ):
            cache[chave] = landing
    contexto = contexto_base(request)
    municipios = municipios_mg()
    # Marquise da landing: a tupla versionada é de códigos IBGE; o nome sai da
    # mesma lista de `municipios_mg()`, então o template não escreve topônimo
    # nenhum. O design repete a sequência duas vezes no trilho (loop do
    # marquee) — o template itera a lista duas vezes.
    por_codigo = {m.co_municipio: m.no_municipio for m in municipios}
    contexto.update(
        # Assets da landing: a camada visual, o JS de revelação/contadores e
        # a foto entram pelo mesmo registro com hash que o resto do front,
        # só nesta tela.
        css_landing_url=assets().url("landing.css"),
        js_landing_url=assets().url("landing.js"),
        foto_landing_url=assets().url("escola-felisburgo-mg.webp"),
        # A marquise é decorativa: código que não esteja na lista versionada é
        # ignorado aqui em vez de derrubar a landing (500). O teste
        # `test_todo_codigo_da_marquise_existe_na_lista` trava o cadastro.
        marquise_municipios=[
            por_codigo[codigo] for codigo in MARQUISE_MUNICIPIOS if codigo in por_codigo
        ],
        **landing,
    )
    return templates().TemplateResponse(request, "inicio.html", contexto)


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

    # Lista IBGE versionada: alimenta o `select` do SSR e a ilha JSON
    # `dados-municipios` ([nome, codigo]) que a combobox do `app.js` filtra.
    municipios = municipios_mg()
    contexto: dict[str, Any] = {
        **contexto_base(request, pagina="escolas"),
        "filtros": {
            "q": termo,
            "co_municipio": municipio,
            "apenas_ativas": apenas_ativas,
        },
        "municipios": municipios,
        "ilha_municipios": json.dumps(
            [[m.no_municipio, m.co_municipio] for m in municipios],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        # Nome do município escolhido, para o chip e para a combobox
        # reabrir com o texto visível (o `hidden` leva o código).
        "nome_municipio": next(
            (m.no_municipio for m in municipios if m.co_municipio == municipio),
            "",
        ),
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
        # Rótulos dos códigos INEP por linha: a busca mostra só a leitura
        # ("Privada"), sem o código cru (D5).
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
def mercado_atalho(
    request: Request,
    co_municipio: str | None = None,
    ano: int | None = None,
    etapa: str | None = None,
) -> Response:
    """Atalho `GET /app/mercados?co_municipio=` → tela do mercado (spec §6).

    É o segundo botão da barra de busca do hero: o `<form>` é ``GET /app/``, e
    o botão leva ``formaction="/app/mercados"``. A rota **só** redireciona:

    * ``co_municipio`` válido (``^31\\d{5}$``, a mesma validação de
      `core.validation`) → **303** `Location: /app/mercados/{co}`, ignorando
      `q` e qualquer outro parâmetro que o form tenha enviado, mas repassa
      `ano`/`etapa` quando presentes (a validação deles continua na tela de
      destino);
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
    destino = f"{PREFIXO_WEB}/mercados/{codigo}"
    repasse = urlencode(
        [
            (chave, valor)
            for chave, valor in (("ano", ano), ("etapa", (etapa or "").strip()))
            if valor is not None and str(valor) != ""
        ]
    )
    return RedirectResponse(
        url=f"{destino}?{repasse}" if repasse else destino,
        status_code=303,
    )


#: Motivo das células sem dado do índice quando o município não tem escola
#: privada ativa (decisão P-V-1, variante A). Nunca vira `0` (AGENTS.md §6).
MOTIVO_SEM_ESCOLA_PRIVADA = "sem escola privada ativa"
#: Variação nula com matrícula no ano mas sem ano anterior: a base existe, só
#: não há par para comparar (o SQL devolve NULL sem base no ano anterior).
MOTIVO_SEM_ANO_ANTERIOR = "sem ano anterior"


def _linhas_indice(
    indice: IndiceMunicipios, nomes: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Linhas da tabela já na ordem do SQL (matrícula desc, nulos por último).

    Cada linha carrega o texto pronto de variação (sinal tipográfico do
    protótipo) e o motivo da ausência, para o template não decidir regra de
    exibição. A largura da barra espelha o mock (`Math.max(2, …)`, 1 casa).
    """
    max_qt = max(
        (
            linha.qt_mat_privada
            for linha in indice.linhas
            if linha.qt_mat_privada is not None
        ),
        default=None,
    )
    prontas: list[dict[str, Any]] = []
    for posicao, linha in enumerate(indice.linhas, start=1):
        qt = linha.qt_mat_privada
        anterior = linha.qt_mat_privada_anterior
        variacao = linha.variacao_pct
        if variacao is None:
            if qt is None:
                motivo_variacao: str | None = MOTIVO_SEM_ESCOLA_PRIVADA
            elif anterior is None:
                motivo_variacao = MOTIVO_SEM_ANO_ANTERIOR
            else:
                motivo_variacao = None
        else:
            motivo_variacao = None
        prontas.append(
            {
                "posicao": posicao,
                "co_municipio": linha.co_municipio,
                "nome": nomes[linha.co_municipio],
                "qt_mat_privada": qt,
                "largura": (
                    f"{max(2.0, qt / max_qt * 100):.1f}%"
                    if qt is not None and max_qt
                    else None
                ),
                "n_escolas": linha.n_escolas_privadas,
                "motivo_escolas": (
                    MOTIVO_SEM_ESCOLA_PRIVADA
                    if linha.n_escolas_privadas is None and qt is None
                    else None
                ),
                "variacao_pct": variacao,
                "texto_variacao": texto_variacao(variacao),
                "classe_variacao": (
                    ""
                    if variacao is None
                    else ("var-pos" if variacao >= 0 else "var-neg")
                ),
                "motivo_variacao": motivo_variacao,
                "share_lider_pct": linha.share_lider_pct,
                "motivo_share": (
                    MOTIVO_SEM_ESCOLA_PRIVADA
                    if linha.share_lider_pct is None and qt is None
                    else None
                ),
            }
        )
    return prontas


def _kpis_indice(indice: IndiceMunicipios) -> list[dict[str, Any]]:
    """Os 4 KPIs do topo (plano §4.5): somas que ignoram `None`, nunca 0."""
    totais = indice.kpis
    variacao = totais.variacao_pct
    return [
        {
            "rotulo": "Municípios no recorte",
            "valor": fmt_contagem(totais.n_municipios),
            "classe": "",
            "nota": "mercados publicados no índice",
        },
        {
            "rotulo": f"Matrícula privada {fmt_ano(indice.ano)}",
            "valor": fmt_contagem(totais.qt_mat_privada_total),
            "classe": "",
            "nota": "soma dos municípios listados",
        },
        {
            "rotulo": "Escolas privadas ativas",
            "valor": fmt_contagem(totais.n_escolas_privadas_total),
            "classe": "",
            "nota": "no conjunto do recorte",
        },
        {
            "rotulo": "Variação do recorte",
            "valor": texto_variacao(variacao),
            "classe": (
                "" if variacao is None else ("var-pos" if variacao >= 0 else "var-neg")
            ),
            "nota": (
                f"matrícula privada vs. {fmt_ano(indice.ano - 1)}, "
                "só municípios com os dois anos"
            ),
        },
    ]


@router.get(
    "/mercados/",
    response_class=HTMLResponse,
    name="web_mercados_indice",
    summary="Índice de municípios: escolher o mercado",
)
def mercados_indice(request: Request, co_municipio: str | None = None) -> Response:
    """Índice de municípios (4b, cards V4-I0/V4-I): a página que escolhe o mercado.

    Sem ``co_municipio``, responde ``200`` com o índice no DOM do protótipo
    (7 colunas, 853 linhas em matrícula desc): **1 consulta** BigQuery via
    :func:`dados.indice_municipios` (ano = maior de `APP_ANOS_DISPONIVEIS`,
    etapa `bas` fixa); com um
    código válido (``^31\\d{5}$``), **303** para ``/app/mercados/{co}``, para que
    recarregar não reenvie o formulário; com código inválido, ``422`` em HTML
    com a volta para este índice.

    Se o BigQuery falhar, a página **degrada para o 4a** (lista com 853
    links, sem colunas numéricas nem KPIs) com um ``div.aviso``: status 200,
    mas sem ``ETag`` e fora do LRU (o mesmo caminho dos erros —
    ``Cache-Control: no-store``), para a falha não ficar pinada.
    """
    if co_municipio is None:
        base = contexto_base(request, pagina="municipios")
        migalhas = [
            {"rotulo": "Início", "href": base["href_inicio"]},
            {"rotulo": "Municípios", "href": None},
        ]
        subnav_indice = [
            {
                "rotulo": "Índice de mercados",
                "href": "#indice-municipios",
                "ativo": True,
                "classe": "",
            },
            {
                "rotulo": "Busca de escolas",
                "href": f"{PREFIXO_WEB}/",
                "ativo": False,
                "classe": "",
            },
        ]
        try:
            anos = list(_settings(request).anos_disponiveis)
            indice = dados.indice_municipios(request, ano=max(anos))
        except UpstreamUnavailable:
            contexto_degradado = {
                **base,
                "migalhas": migalhas,
                "subnav_itens": subnav_indice,
                "indisponivel": True,
                "municipios": municipios_mg(),
            }
            return templates().TemplateResponse(
                request,
                "mercados_indice.html",
                contexto_degradado,
                headers={"Cache-Control": CACHE_CONTROL_ERRO},
            )
        nomes = {m.co_municipio: m.no_municipio for m in municipios_mg()}
        ausentes = [
            linha.co_municipio for linha in indice.linhas if linha.co_municipio not in nomes
        ]
        if ausentes:
            raise ValueError(
                "índice com co_municipio sem nome em municipios_mg.json: "
                f"{ausentes!r}"
            )
        linhas = _linhas_indice(indice, nomes)
        contexto = {
            **base,
            "migalhas": migalhas,
            "subnav_itens": subnav_indice,
            "indisponivel": False,
            "linhas": linhas,
            "kpis": _kpis_indice(indice),
            "ano": indice.ano,
            "total_linhas": len(linhas),
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
    """**Mercado** do município (cards F5, V2 e D1-E3).

    * o ano sai de `APP_ANOS_DISPONIVEIS` (setting validado no boot); sem `ano`,
      o padrão é o **maior** ano da lista, nunca o ano corrente inventado;
    * `ANO_FORA_DO_CONTRATO` (ano fora da lista ou etapa sem linha em
      `mart_mercado`) responde ``404`` com o seletor de outro ano — o recorte é
      substituível pelo usuário, não é erro de sistema;
    * a composição é consultada **sem** recorte de etapa (a tela cobre todas);
      a etapa selecionada vale para o movimento e os denominadores;
    * o ranking de share (`section#escolas`) é paginado **na própria página**:
      `dados.share_mercado` com `limit=10` e o `offset` do recorte (decisão
      D4 — o 301 de `/escolas` cai aqui). `offset` fora de `0..1000` responde
      ``422`` `PARAMETRO_INVALIDO` pela validação de `core.validation`, sem
      consultar o repositório.
    """
    # `offset` recorta a `section#escolas` desta página (decisão D4, registrada
    # em D1-g): fora de `0..1000` é `422` sem consultar nada; o ranking
    # completo vive na própria página, não numa rota separada.
    deslocamento = validation.offset(offset)

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
            prefixo=PREFIXO_WEB,
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

    contexto.update(
        contexto_mercado_visao_geral(mercado=resposta_mercado, etapa=etapa_ref, anos=anos)
    )
    # O ranking de share mora na `section#escolas` da própria página (decisão
    # D4): a mesma etapa do recorte, 10 linhas, deslocadas por `offset`.
    resposta_share = dados.share_mercado(
        request,
        co_municipio=co_municipio,
        ano=ano_ref,
        etapa=etapa_ref,
        entidade_tipo="escola",
        limit=10,
        offset=deslocamento,
    )
    contexto.update(
        contexto_escolas_mercado(
            share=resposta_share,
            caminho=caminho,
            filtros_pagina={"ano": str(ano_ref), "etapa": etapa_ref},
            montar_paginacao=montar_paginacao,
            url_lista=url_lista,
        )
    )
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
    """**301** da rota antiga do ranking para a `section#escolas` (decisão D4).

    O ranking de share agora é paginado na própria página do mercado
    (`/app/mercados/{co}?ano&etapa&offset#escolas`, 10 linhas por página).
    Este handler só redireciona, preservando os parâmetros válidos:

    * `etapa` é validada (`_etapa_do_seletor`, `422` se inválida) e `offset`
      também (`validation.offset`, `422` fora de `0..1000`) — parâmetro
      inválido nunca vira redirect;
    * `ano` passa cru: quem valida contra o contrato é a tela de destino
      (`404` se fora de `APP_ANOS_DISPONIVEIS`);
    * só entram na query os parâmetros presentes e não-vazios, com `#escolas`
      no `Location` permanente (`301`, que o navegador pode cachear).
    """
    # Validação antes do redirect: parâmetro inválido é `422`, nunca `301`.
    # Só entram na query os parâmetros presentes e não-vazios (`offset=0` é a
    # 1ª página canônica, sem `offset` — como em `web/paginacao.url`).
    etapa_ref = _etapa_do_seletor(etapa)
    validation.offset(offset)
    consulta = urlencode(
        [
            (chave, valor)
            for chave, valor in (
                ("ano", ano),
                ("etapa", etapa_ref if etapa and etapa.strip() else None),
                ("offset", offset or None),
            )
            if valor is not None and str(valor) != ""
        ]
    )
    destino = f"{PREFIXO_WEB}/mercados/{co_municipio}"
    return RedirectResponse(
        url=f"{destino}?{consulta}#escolas" if consulta else f"{destino}#escolas",
        status_code=301,
    )


def _contexto_comum_mercado(
    *,
    co_municipio: str,
    anos: tuple[int, ...],
    ano: int | None,
    etapa: str,
    prefixo: str,
) -> dict[str, Any]:
    """Contexto que o seletor e o subnav precisam na tela do mercado.

    Vale para a página 200 e para a 404 de `ANO_FORA_DO_CONTRATO`: a 404 também
    oferece outro ano/etapa e a navegação. O `href_base` do formulário é a
    rota de atalho (`/app/mercados`): ela resolve o município e repassa
    `ano`/`etapa` em 303. O seletor oferece as 9 etapas do contrato e a lista
    de municípios (com o atual selecionado); etapa sem linha em `mart_mercado`
    é `404` com este mesmo seletor.
    """
    nome = _nome_municipio(co_municipio)
    return {
        "municipio": co_municipio,
        "municipio_nome": nome,
        "migalhas": [
            {"rotulo": "Busca", "href": f"{prefixo}/"},
            {"rotulo": nome, "href": None},
        ],
        "anos_disponiveis": list(anos),
        "ano_selecionado": ano if ano is not None else max(anos),
        "etapa_selecionada": etapa,
        "etapa_rotulo": rotulo_etapa(etapa),
        "etapas_disponiveis": ETAPAS_ROTULOS,
        "municipios": municipios_mg(),
        "href_base": f"{prefixo}/mercados",
        "sem_dados_ano": False,
        "subnav_itens": itens_subnav(prefixo=prefixo),
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
    subtítulo e trilha sem consulta extra; código fora da lista continua
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
