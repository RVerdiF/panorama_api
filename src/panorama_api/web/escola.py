"""Regras da tela da escola `/app/escolas/{co_entidade}` (card `t_49960786`).

Tudo aqui é **puro**: recebe os objetos do contrato (os mesmos do `/v1`) e
devolve o contexto do template. Nenhum acesso a dado — quem consulta é
`web/dados.py`, chamado pela rota em `web/routes.py`.

Duas decisões moram neste módulo:

1. **Universo de indicadores/competidores.** A comparação municipal só existe
   para escola privada ativa; a decisão sai do item **mais recente** da série de
   `history` (`tp_dependencia == "4"` e `tp_situacao_funcionamento == "1"`).
   Qualquer outro estado — pública, inativa ou campo nulo — não consulta as
   marts privadas (falha fechada: não gasta cota, não inventa seção). Quando a
   escola é privada ativa mas a mart não tem a linha do ano, o `/v1` responde
   404 e a seção diz "não se aplica" — a causa exibida é sempre um texto fixo
   daqui (`conteudo.MOTIVO_SECAO_*`), nunca o detalhe de diagnóstico da API.
2. **Série de matrículas.** O gráfico é SVG inline gerado no servidor
   (`<svg aria-hidden>`) e a leitura assistiva fica com a tabela equivalente:
   ausência de dado é sempre ``sem dado`` com a flag de origem, nunca `0`.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, NamedTuple, Protocol, Sequence, TypeVar

from markupsafe import Markup

from panorama_api.contract import Etapa
from panorama_api.schemas.common import Meta
from panorama_api.schemas.competitors import Competicao
from panorama_api.schemas.indicators import IndicatorItem, IndicatorsResponse
from panorama_api.schemas.schools import HistoryItem, HistoryResponse, School
from panorama_api.web import PREFIXO_WEB
from panorama_api.web.conteudo import (
    DEFINICAO_CONCORRENCIA,
    EXPLICACAO_ABAIXO_PORTE,
    EXPLICACAO_OFERTA_DESCONHECIDA,
    MOTIVO_ANO_AUSENTE,
    MOTIVO_FORA_DO_UNIVERSO_PRIVADO,
    MOTIVO_MUNICIPIOS_DIFERENTES,
    MOTIVO_SECAO_COMPETIDORES,
    MOTIVO_SECAO_ESCOLA_INATIVA,
    MOTIVO_SECAO_ESCOLA_PUBLICA,
    MOTIVO_SECAO_INDICADORES,
    MOTIVO_SEM_ANO_COMUM,
    MOTIVO_SEM_COMPARACAO,
    NAO_SE_APLICA,
    NOTA_GRUPO_ETAPAS,
    NOTA_GRUPO_MODALIDADES,
    NOTA_GRUPO_TOTAL,
    ROTULO_COMPARAR_ENTRADA,
    ROTULO_POSICAO_CRESCIMENTO_MG,
    ROTULO_POSICAO_CRESCIMENTO_MUNICIPIO,
    ROTULO_RETENCAO,
    ROTULO_VISAO_GERAL,
    TEXTO_NESTA_PAGINA,
    TEXTO_VOLTAR_VISAO_GERAL,
    TITULO_COMPARACAO,
    TITULO_GRUPO_ETAPAS,
    TITULO_GRUPO_MODALIDADES,
    TITULO_GRUPO_TOTAL,
    TITULO_SECAO_CONCORRENCIA,
    UNIVERSOS,
    rotulo_etapa,
    traduzir_aviso,
    traduzir_avisos,
)
from panorama_api.web.filters import SEM_DADO, fmt_ano, fmt_nulo
from panorama_api.web.mercado import barra_share

#: Códigos INEP usados na classificação (os mesmos de `services/schools.py`).
DEPENDENCIA_PRIVADA = "4"
SITUACAO_ATIVA = "1"

#: Rótulos completos dos códigos INEP de dependência administrativa
#: (`TP_DEPENDENCIA`). O código continua visível ao lado; o rótulo é a leitura
#: do código, nunca uma classificação inventada (não existe "não privada": 2 é
#: Estadual, 3 é Municipal, 1 é Federal).
ROTULOS_DEPENDENCIA: dict[str, str] = {
    "1": "Federal",
    "2": "Estadual",
    "3": "Municipal",
    "4": "Privada",
}

#: Rótulos completos dos códigos INEP de situação de funcionamento
#: (`TP_SITUACAO_FUNCIONAMENTO`). "não ativa" colapsava 2 (paralisada) e 3
#: (extinta) no mesmo texto; cada código tem sua leitura.
ROTULOS_SITUACAO: dict[str, str] = {
    "1": "Em atividade",
    "2": "Paralisada",
    "3": "Extinta",
    "4": "Extinta no ano anterior",
}

#: Leitura de código ausente ou fora da tabela INEP — nunca deduzida.
ROTULO_NAO_INFORMADO = "não informado"
ROTULO_NAO_RECONHECIDO = "código não reconhecido"

#: Aviso de `meta.avisos` que muda a leitura dos indicadores comparativos.
AVISO_ABAIXO_PORTE = "IS_ABAIXO_PORTE"


class CampoMatricula(NamedTuple):
    """Matrícula de uma etapa: campo do contrato + flag de ausência."""

    etapa: Etapa
    campo: str
    flag: str


class CampoRendimento(NamedTuple):
    """Taxa de rendimento: rótulo de tela, campo e flag de ausência."""

    rotulo: str
    campo: str
    flag: str


#: Matrícula por etapa na ordem do contrato.
MATRICULAS: tuple[CampoMatricula, ...] = (
    CampoMatricula("bas", "qt_mat_bas", "is_qt_mat_bas_missing"),
    CampoMatricula("creche", "qt_mat_creche", "is_qt_mat_creche_missing"),
    CampoMatricula("pre", "qt_mat_pre", "is_qt_mat_pre_missing"),
    CampoMatricula("fund_ai", "qt_mat_fund_ai", "is_qt_mat_fund_ai_missing"),
    CampoMatricula("fund_af", "qt_mat_fund_af", "is_qt_mat_fund_af_missing"),
    CampoMatricula("med", "qt_mat_med", "is_qt_mat_med_missing"),
    CampoMatricula("prof", "qt_mat_prof", "is_qt_mat_prof_missing"),
    CampoMatricula("eja", "qt_mat_eja", "is_qt_mat_eja_missing"),
    CampoMatricula("esp", "qt_mat_esp", "is_qt_mat_esp_missing"),
)

#: Etapa → campo do contrato + flag de ausência, derivado de `MATRICULAS`: o
#: mapa campo/flag não é escrito duas vezes.
CAMPOS_MATRICULA: dict[Etapa, CampoMatricula] = {
    campo.etapa: campo for campo in MATRICULAS
}


class GrupoEtapas(NamedTuple):
    """Grupo semântico da tabela de oferta: título, nota e etapas.

    ``fixa`` marca as etapas que **não** são parcelas comparáveis do grupo: o
    total oficial do Censo (`bas`) fica na posição original quando o leitor
    ordena a tabela no cliente (card `t_ee9b1eec`) — ele não é "mais uma
    etapa" e não pode descer para o meio delas.
    """

    titulo: str
    nota: str
    etapas: tuple[Etapa, ...]
    fixa: bool = False


#: Grupos da tabela "Oferta e matrícula por etapa" (card F11). As linhas não são
#: irmãs somáveis: `bas` é o total oficial do Censo; creche…médio e EJA são
#: parcelas aditivas; `prof` acompanha o médio (o técnico integrado é contado
#: nas duas linhas) e `esp` é modalidade transversal — nenhuma das duas entra na
#: soma. Sem essa separação a escola 31005371 aparecia com 2.061 alunos em 680.
GRUPOS_ETAPAS: tuple[GrupoEtapas, ...] = (
    GrupoEtapas(TITULO_GRUPO_TOTAL, NOTA_GRUPO_TOTAL, ("bas",), fixa=True),
    GrupoEtapas(
        TITULO_GRUPO_ETAPAS,
        NOTA_GRUPO_ETAPAS,
        ("creche", "pre", "fund_ai", "fund_af", "med", "eja"),
    ),
    GrupoEtapas(
        TITULO_GRUPO_MODALIDADES,
        NOTA_GRUPO_MODALIDADES,
        ("prof", "esp"),
    ),
)

#: Rendimento por ano. Nenhum rótulo é "evasão": `tx_aband_*` é taxa de
#: abandono e o proxy de retenção tem rótulo próprio
#: (`conteudo.ROTULO_RETENCAO`).
RENDIMENTO: tuple[CampoRendimento, ...] = (
    CampoRendimento(
        "Aprovação — fundamental (total)", "tx_aprov_fund_t", "is_tx_aprov_fund_t_missing"
    ),
    CampoRendimento(
        "Aprovação — anos iniciais", "tx_aprov_fund_ai", "is_tx_aprov_fund_ai_missing"
    ),
    CampoRendimento(
        "Aprovação — anos finais", "tx_aprov_fund_af", "is_tx_aprov_fund_af_missing"
    ),
    CampoRendimento(
        "Aprovação — ensino médio", "tx_aprov_med_t", "is_tx_aprov_med_t_missing"
    ),
    CampoRendimento(
        "Reprovação — fundamental (total)",
        "tx_reprov_fund_t",
        "is_tx_reprov_fund_t_missing",
    ),
    CampoRendimento(
        "Abandono — fundamental (total)", "tx_aband_fund_t", "is_tx_aband_fund_t_missing"
    ),
)

#: Concorrentes com matrícula observada por etapa (mesmo município e ano).
CONCORRENTES_POR_ETAPA: tuple[tuple[Etapa, str], ...] = (
    ("creche", "n_concorrentes_creche_xself"),
    ("pre", "n_concorrentes_pre_xself"),
    ("fund_ai", "n_concorrentes_fund_ai_xself"),
    ("fund_af", "n_concorrentes_fund_af_xself"),
    ("med", "n_concorrentes_med_xself"),
)

#: Dimensões do gráfico da série (SVG inline, gerado no servidor).
LARGURA_SVG = 640
ALTURA_SVG = 200
#: Altura mínima de uma barra: zero declarado continua visível (não é lacuna).
ALTURA_MINIMA_BARRA = 2.0


class ComAno(Protocol):
    """Item de série com ano censitário (history, indicators e competitors)."""

    nu_ano_censo: int


ItemT = TypeVar("ItemT", bound=ComAno)


def item_mais_recente(items: Sequence[ItemT]) -> ItemT | None:
    """Item de maior `nu_ano_censo` (a série vem ASC; não confiar só na ordem)."""
    return max(items, key=lambda item: item.nu_ano_censo) if items else None


def pertence_ao_universo_privado(item: HistoryItem | None) -> bool:
    """Escola privada **e** ativa segundo o item mais recente da série.

    Campo ausente nunca é lido como "privada": só o par explícito habilita as
    consultas de indicadores/competidores.
    """
    if item is None:
        return False
    return (
        item.tp_dependencia == DEPENDENCIA_PRIVADA
        and item.tp_situacao_funcionamento == SITUACAO_ATIVA
    )


def _motivo(flag: bool | None, nome_flag: str) -> str | None:
    return nome_flag if flag else None


def rotulo_dependencia(codigo: str | None) -> str:
    """Leitura do código INEP de dependência (1 Federal … 4 Privada).

    Código ausente é "não informado" e código fora da tabela é "código não
    reconhecido": nenhum dos dois vira "não privada", que colapsaria Federal,
    Estadual e Municipal numa classificação que o INEP não usa.
    """
    if not codigo:
        return ROTULO_NAO_INFORMADO
    return ROTULOS_DEPENDENCIA.get(codigo, ROTULO_NAO_RECONHECIDO)


def rotulo_situacao(codigo: str | None) -> str:
    """Leitura do código INEP de situação de funcionamento.

    Cada código tem seu texto (2 Paralisada e 3 Extinta não são o mesmo estado);
    ausência e código desconhecido também não se confundem.
    """
    if not codigo:
        return ROTULO_NAO_INFORMADO
    return ROTULOS_SITUACAO.get(codigo, ROTULO_NAO_RECONHECIDO)


def _celula(valor: Any, *, motivo: str | None = None, unidade: str = "") -> dict[str, Any]:
    """Célula exibida pelo template: valor, motivo da ausência e unidade."""
    return {"valor": valor, "motivo": motivo, "unidade": unidade}


def serie_matriculas(items: Sequence[HistoryItem]) -> dict[str, Any]:
    """Série de matrícula da educação básica + o SVG do gráfico.

    A tabela (e o gráfico) cobre **todo ano entre o primeiro e o último da
    série**, não só os anos que têm registro: um ano censitário ausente da
    fonte continua visível com ``sem dado (ano ausente na fonte)``. Sem isso a
    lacuna desaparece e o leitor lê a série como se fosse contínua (e nunca
    como ``0``).

    `svg` é ``None`` quando não há **nenhum** ano com matrícula observada: o
    template mostra "sem dado" em vez de um gráfico de zeros.
    """
    pontos = _pontos_da_serie(items)
    return {"pontos": pontos, "svg": svg_serie(pontos), "ilha": _ilha_serie(pontos)}


def _ilha_serie(pontos: Sequence[dict[str, Any]]) -> Markup:
    """Ilha JSON da série para hidratação no cliente (`static/app.js`).

    ``{"anos": [...], "valores": [...]}`` com os números do SSR — ``null``
    onde falta dado, nunca ``0``. O `app.js` lê a ilha por
    ``JSON.parse(textContent)`` dentro da `section#serie` e desenha linha/área
    com dica `aria-live`; sem ilha válida, ele usa a tabela SSR da seção.
    O JSON nasce só de inteiros/`None` (`json.dumps`), então o ``Markup`` é
    seguro sem escape adicional.
    """
    anos = [int(ponto["ano"]) for ponto in pontos]
    valores = [
        int(ponto["valor"]) if ponto["valor"] is not None else None
        for ponto in pontos
    ]
    return Markup(json.dumps({"anos": anos, "valores": valores}))


def _pontos_da_serie(items: Sequence[HistoryItem]) -> list[dict[str, Any]]:
    """Um ponto por ano do intervalo da série, com o registro quando existir."""
    registros = {item.nu_ano_censo: item for item in items}
    if not registros:
        return []
    primeiro, ultimo = min(registros), max(registros)
    pontos: list[dict[str, Any]] = []
    for ano in range(primeiro, ultimo + 1):
        item = registros.get(ano)
        pontos.append(
            {
                "ano": ano,
                "valor": item.qt_mat_bas if item is not None else None,
                "motivo": (
                    _motivo(item.is_qt_mat_bas_missing, "is_qt_mat_bas_missing")
                    if item is not None
                    else MOTIVO_ANO_AUSENTE
                ),
            }
        )
    _acrescentar_variacoes(pontos)
    return pontos


def _acrescentar_variacoes(pontos: list[dict[str, Any]]) -> None:
    """Variação ano a ano de cada ponto (card V2 `t_cbd54a92`).

    Compara cada ano observado com o **ano observado anterior** (não o ano
    anterior no calendário): uma lacuna no meio da série não transforma a
    variação seguinte numa taxa contra zero. Sem ano anterior observado, ou com
    base zero, a variação é ``None`` — nunca ``0`` nem ``100%`` inventado.
    """
    anterior: int | None = None
    for ponto in pontos:
        valor = ponto["valor"]
        if valor is None or anterior is None or not anterior:
            ponto["variacao"] = None
        else:
            ponto["variacao"] = (valor - anterior) / anterior * 100
        if valor is not None:
            anterior = valor


# -- ficha consolidada (V2 `t_cbd54a92`): KPIs, posição e ranking municipal ---


def texto_variacao(pct: float | None) -> str:
    """Variação anual com sinal tipográfico; ausência continua ``sem dado``."""
    if pct is None:
        return SEM_DADO
    return f"{'+' if pct >= 0 else '−'}{fmt_nulo(abs(pct))}%"


def _classe_variacao(pct: float | None) -> str:
    """Classe de cor do valor: ``var-pos``/``var-neg``; vazio quando sem dado."""
    if pct is None:
        return ""
    return "var-pos" if pct >= 0 else "var-neg"


def total_privadas_ativas(competicao: Competicao | None) -> int | None:
    """Privadas ativas do município/ano contando a própria escola.

    `n_concorrentes_privados_municipio` exclui esta escola; a posição ("de N
    escolas privadas ativas") conta todas. ``None`` quando a base não traz a
    contagem — nunca ``1`` por suposição.
    """
    if competicao is None or competicao.n_concorrentes_privados_municipio is None:
        return None
    return competicao.n_concorrentes_privados_municipio + 1


def kpis_da_escola(
    *,
    recente: HistoryItem | None,
    item: IndicatorItem | None,
    competicao: Competicao | None,
) -> list[dict[str, Any]]:
    """Os quatro KPIs do topo da ficha (card V2 `t_cbd54a92`).

    Matrícula BAS do ano recente, variação anual, posição municipal por
    matrícula e o gap para o líder. Cada número sai da resposta de indicadores
    quando ela existe; a matrícula cai na série (`history`) quando não há linha
    na mart. Ausência é sempre ``sem dado``, nunca ``0``.
    """
    ano = getattr(recente, "nu_ano_censo", None)
    qt_mat = (
        getattr(item, "qt_mat_bas", None)
        if item is not None
        else getattr(recente, "qt_mat_bas", None)
    )
    prev = getattr(item, "prev_qt_mat_bas", None) if item is not None else None
    variacao = getattr(item, "crescimento_yoy_pct", None) if item is not None else None
    if variacao is None and qt_mat is not None and prev:
        variacao = (qt_mat - prev) / prev * 100

    rank = competicao.rank_mat_bas_municipio if competicao is not None else None
    total = total_privadas_ativas(competicao)
    gap = competicao.gap_mat_bas_para_lider if competicao is not None else None
    lider = competicao.lider_no_entidade if competicao is not None else None
    lider_mat = competicao.lider_qt_mat_bas if competicao is not None else None

    if gap is None:
        nota_gap = SEM_DADO
    elif gap == 0:
        nota_gap = "a escola é a maior do município"
    elif lider:
        nota_gap = f"matrículas atrás de {lider}"
        if lider_mat is not None:
            nota_gap += f" ({fmt_nulo(lider_mat)} matrículas)"
    else:
        nota_gap = "escola líder do município sem nome publicado"

    return [
        {
            "rotulo": f"Matrícula {fmt_ano(ano)}",
            "valor": fmt_nulo(qt_mat),
            "classe": "",
            "nota": "educação básica · total oficial do Censo",
        },
        {
            "rotulo": "Variação anual",
            "valor": texto_variacao(variacao),
            "classe": _classe_variacao(variacao),
            "nota": (
                f"matrícula vs. {fmt_ano(ano - 1)}"
                if variacao is not None and ano is not None
                else "sem ano anterior observado para comparar"
            ),
        },
        {
            "rotulo": "Posição no município",
            "valor": f"{rank}.º" if rank is not None else SEM_DADO,
            "classe": "",
            "nota": (
                f"de {total} escolas privadas ativas"
                if total is not None
                else "sem comparação municipal para este ano"
            ),
        },
        {
            "rotulo": "Gap para o líder",
            "valor": "lidera" if gap == 0 else fmt_nulo(gap),
            "classe": "",
            "nota": nota_gap,
        },
    ]


def posicao_crescimento(
    *, item: IndicatorItem | None, total: int | None
) -> dict[str, Any]:
    """Posições por **crescimento** (município e MG) para a lista de posição.

    `rank_crec_*` é posição por crescimento anual da matrícula, não por
    matrícula nem de creche (`conteudo.ROTULO_POSICAO_CRESCIMENTO_*`).
    """
    return {
        "municipio": {
            "rank": getattr(item, "rank_crec_municipio", None),
            "total": total,
        },
        "mg": {"rank": getattr(item, "rank_crec_mg", None), "total": None},
    }


def ranking_municipal(
    *,
    cabecalho: Mapping[str, Any],
    item: IndicatorItem | None,
    competicao: Competicao | None,
) -> dict[str, Any]:
    """Ranking municipal por matrícula reduzido à **própria escola**.

    `mart_competidores` publica contagens e a posição da escola, mas **não** a
    lista nominal de concorrentes (ver `schemas/competitors.py`). Por isso o
    `<ul class="ranking">` traz só a linha desta escola, com a posição, o nome
    (link para a ficha) e a matrícula; a lista completa vive no ranking de share
    do mercado (`/app/mercados/{co}/escolas`), que é quem consulta
    `mart_market_share`. Inventar as demais linhas não é uma opção.
    """
    rank = competicao.rank_mat_bas_municipio if competicao is not None else None
    qt_mat = (
        getattr(item, "qt_mat_bas", None)
        if item is not None
        else None
    )
    share = getattr(item, "share_privado_pct", None) if item is not None else None
    linhas: list[dict[str, Any]] = []
    if rank is not None or qt_mat is not None:
        linhas.append(
            {
                "posicao": rank,
                "id_entidade": cabecalho["co_entidade"],
                "no_entidade": cabecalho.get("no_entidade"),
                "matricula": qt_mat,
                "share_privado_pct": share,
                "barra": barra_share(share),
                "destaque": True,
            }
        )
    return {
        "linhas": linhas,
        "total": total_privadas_ativas(competicao),
        "co_municipio": cabecalho.get("co_municipio"),
    }


def contexto_concorrencia_na_ficha(
    *,
    item: IndicatorItem | None,
    competicao: Competicao | None,
    cabecalho: Mapping[str, Any],
    aviso_abaixo_porte: bool,
) -> dict[str, Any]:
    """Bloco ``#concorrencia`` da ficha: posição por crescimento e ranking."""
    total = total_privadas_ativas(competicao)
    return {
        "indicador": item,
        "competicao": competicao,
        "posicao": posicao_crescimento(item=item, total=total),
        "rotulo_posicao_municipio": ROTULO_POSICAO_CRESCIMENTO_MUNICIPIO,
        "rotulo_posicao_mg": ROTULO_POSICAO_CRESCIMENTO_MG,
        "ranking": ranking_municipal(
            cabecalho=cabecalho, item=item, competicao=competicao
        ),
        "definicao_concorrencia": DEFINICAO_CONCORRENCIA,
        "aviso_abaixo_porte": aviso_abaixo_porte,
        "texto_abaixo_porte": EXPLICACAO_ABAIXO_PORTE,
        "motivo_sem_comparacao": (
            None
            if competicao is not None
            else MOTIVO_SECAO_COMPETIDORES
        ),
    }



def _valor_bruto(valor: int) -> str:
    """Número inteiro no formato de tela (milhar com ponto)."""
    return f"{valor:,}".replace(",", ".")


def svg_serie(pontos: Sequence[dict[str, Any]]) -> Markup | None:
    """Gráfico de barras em SVG inline, sem JS e sem eixo de zero inventado.

    Só anos com matrícula observada ganham barra; os demais ficam como lacuna
    marcada (a tabela ao lado informa "sem dado" e o motivo). O elemento é
    decorativo (`aria-hidden`): o equivalente acessível é a tabela renderizada
    junto. Só inteiros entram no markup — nenhuma string externa é interpolada.
    """
    observados = [ponto for ponto in pontos if ponto["valor"] is not None]
    if not observados:
        return None

    maximo = max(int(ponto["valor"]) for ponto in observados) or 1
    margem_esq, margem_dir = 8, 8
    margem_topo, margem_base = 18, 26
    largura_util = LARGURA_SVG - margem_esq - margem_dir
    altura_util = ALTURA_SVG - margem_topo - margem_base
    passo = largura_util / max(len(pontos), 1)
    largura_barra = min(56.0, passo * 0.62)
    base = margem_topo + altura_util

    partes: list[str] = [
        f'<line x1="{margem_esq}" y1="{base:.1f}" '
        f'x2="{LARGURA_SVG - margem_dir}" y2="{base:.1f}" class="serie__eixo"/>'
    ]
    for indice, ponto in enumerate(pontos):
        centro = margem_esq + passo * (indice + 0.5)
        partes.append(
            f'<text x="{centro:.1f}" y="{ALTURA_SVG - 8}" text-anchor="middle" '
            f'class="serie__ano">{int(ponto["ano"])}</text>'
        )
        if ponto["valor"] is None:
            # Lacuna: marca a ausência sem desenhar barra de altura zero.
            partes.append(
                f'<line x1="{centro:.1f}" y1="{base:.1f}" '
                f'x2="{centro:.1f}" y2="{base - 6:.1f}" class="serie__ausente"/>'
            )
            continue
        valor = int(ponto["valor"])
        altura = max(altura_util * valor / maximo, ALTURA_MINIMA_BARRA)
        x = centro - largura_barra / 2
        y = base - altura
        partes.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{largura_barra:.1f}" '
            f'height="{altura:.1f}" class="serie__barra"/>'
        )
        partes.append(
            f'<text x="{centro:.1f}" y="{y - 5:.1f}" text-anchor="middle" '
            f'class="serie__valor">{_valor_bruto(valor)}</text>'
        )

    return Markup(
        f'<svg class="serie" viewBox="0 0 {LARGURA_SVG} {ALTURA_SVG}" '
        f'aria-hidden="true" xmlns="http://www.w3.org/2000/svg">'
        f'{"".join(partes)}</svg>'
    )


def _linha_etapa(item: HistoryItem, campo: CampoMatricula) -> dict[str, Any]:
    """Linha de etapa: rótulo, oferta tri-estado e matrícula com a flag."""
    return {
        "rotulo": rotulo_etapa(campo.etapa),
        "oferta": getattr(item.oferta, campo.etapa),
        "matricula": _celula(
            getattr(item, campo.campo),
            motivo=_motivo(getattr(item, campo.flag), campo.flag),
        ),
    }


def etapas_do_ano(item: HistoryItem) -> list[dict[str, Any]]:
    """Oferta e matrícula do ano, agrupadas pela natureza de cada linha.

    Oferta e matrícula vêm do MESMO item (mesmo ano censitário); a matrícula
    carrega a flag de ausência para que `null` nunca vire `0`. Os grupos
    (`GRUPOS_ETAPAS`) existem para que total oficial, etapas aditivas e
    modalidades/subconjuntos não sejam lidos como irmãos somáveis: somar as
    nove linhas triplicava a matrícula da escola (card F11).
    """
    return [
        {
            "titulo": grupo.titulo,
            "nota": grupo.nota,
            "fixa": grupo.fixa,
            "linhas": [
                _linha_etapa(item, CAMPOS_MATRICULA[etapa]) for etapa in grupo.etapas
            ],
        }
        for grupo in GRUPOS_ETAPAS
    ]


def rendimento_por_ano(items: Sequence[HistoryItem]) -> list[dict[str, Any]]:
    """Rendimento por ano, com a flag de ausência em cada taxa."""
    return [
        {
            "ano": item.nu_ano_censo,
            "celulas": [
                _celula(
                    getattr(item, campo.campo),
                    motivo=_motivo(getattr(item, campo.flag), campo.flag),
                    unidade="%",
                )
                for campo in RENDIMENTO
            ],
        }
        for item in items
    ]


def contexto_indicadores(item: IndicatorItem | None) -> list[dict[str, Any]]:
    """Indicadores do ano mais recente da mart de privadas ativas.

    O proxy de retenção entra com o rótulo canônico (`ROTULO_RETENCAO`), que
    declara explicitamente que a métrica **não é** taxa de evasão.
    """
    if item is None:
        return []

    def linha(rotulo: str, valor: Any, *, unidade: str = "") -> dict[str, Any]:
        return {"rotulo": rotulo, "valor": valor, "motivo": None, "unidade": unidade}

    linhas = [
        {
            "rotulo": "Matrícula — educação básica",
            "valor": item.qt_mat_bas,
            "motivo": _motivo(item.is_qt_mat_bas_missing, "is_qt_mat_bas_missing"),
            "unidade": "",
        },
        linha("Matrícula — ano anterior (proxy de série)", item.prev_qt_mat_bas),
        linha("Crescimento ano a ano", item.crescimento_yoy_pct, unidade="%"),
        linha("Saldo da série de matrículas", item.saldo_serie_matriculas),
        linha(
            ROTULO_RETENCAO, item.retencao_liquida_proxy_pct, unidade="%"
        ),
    ]
    if item.ano_ini_cagr is not None and item.ano_fim_cagr is not None:
        linhas.append(
            linha(
                f"CAGR da série ({item.ano_ini_cagr}–{item.ano_fim_cagr})",
                item.cagr_pct,
                unidade="%",
            )
        )
    else:
        linhas.append(linha("CAGR da série", item.cagr_pct, unidade="%"))
    linhas += [
        linha(
            "Participação na matrícula privada do município",
            item.share_privado_pct,
            unidade="%",
        ),
        linha(
            "Participação na matrícula total do município",
            item.share_total_pct,
            unidade="%",
        ),
        # `rank_crec_*` são posições por **crescimento** da matrícula
        # (`crescimento_yoy_pct`), não por matrícula: a posição municipal por
        # matrícula BAS vem de `/competitors`, em seção própria. O sufixo ".º"
        # é o ordinal da posição; `null` continua "sem dado", nunca 0.º.
        linha(
            ROTULO_POSICAO_CRESCIMENTO_MUNICIPIO,
            item.rank_crec_municipio,
            unidade=".º",
        ),
        linha(ROTULO_POSICAO_CRESCIMENTO_MG, item.rank_crec_mg, unidade=".º"),
    ]
    return linhas


def contexto_competicao(item: Competicao | None, *, ano: int | None) -> dict[str, Any] | None:
    """Posição municipal do **mesmo ano** dos indicadores (spec §5.2).

    A linha de `mart_competidores` vem dentro do item de indicadores: não existe
    segunda leitura da mart nem chamada a `/competitors` para montar esta seção.
    ``item is None`` é ausência de comparação naquele ano — a tela mostra
    "sem dado" com o motivo (`MOTIVO_SEM_COMPARACAO`), nunca 0.
    """
    if item is None:
        return None
    return {
        "ano": ano,
        "rank": item.rank_mat_bas_municipio,
        "n_concorrentes": item.n_concorrentes_privados_municipio,
        "n_com_matricula": item.n_concorrentes_com_matricula_bas,
        "por_etapa": [
            {"rotulo": rotulo_etapa(etapa), "valor": getattr(item, campo)}
            for etapa, campo in CONCORRENTES_POR_ETAPA
        ],
        "lider": item.lider_no_entidade,
        "lider_matricula": item.lider_qt_mat_bas,
        "gap": item.gap_mat_bas_para_lider,
    }



def resumo_meta(meta: Meta) -> dict[str, Any]:
    """Recorte obrigatório de toda tela: ano, etapa, universo, fonte e avisos."""
    return {
        "ano_referencia": meta.ano_referencia,
        "etapa": rotulo_etapa(meta.etapa),
        "universo": meta.universo,
        "universo_texto": UNIVERSOS.get(meta.universo),
        "orgao": meta.fonte.orgao,
        "base": meta.fonte.base,
        "tabela": meta.fonte.tabela,
        "avisos": [
            {"codigo": codigo, "texto": traduzir_aviso(codigo)}
            for codigo in meta.avisos
        ],
    }


#: Ativo/identificador de cada seção da ficha no subnav (spec §2.2).
VISAO_GERAL = "visao_geral"
CONCORRENCIA = "concorrencia"


def motivo_concorrencia_nao_se_aplica(
    item: Any | None, *, padrao: str = MOTIVO_FORA_DO_UNIVERSO_PRIVADO
) -> str:
    """Por que a rota de indicadores não existe para esta escola (sem consulta).

    A decisão sai do item mais recente da série (`history`): dependência
    diferente de privada é escola **pública**; privada que não está em atividade
    é **inativa**. Campo ausente não vira rótulo de terceiro estado — cai em
    ``padrao``, a explicação de quem chamou:

    * Visão geral (`history`) → ``MOTIVO_FORA_DO_UNIVERSO_PRIVADO``: a escola não
      é privada ativa **ou** a série não traz os campos;
    * rota de concorrência (`get_school` já disse privada ativa) →
      ``MOTIVO_SECAO_INDICADORES``: o universo está certo, falta a linha da mart.
      Dizer "fora do universo" aqui afirmaria o contrário do que a própria
      consulta de identidade respondeu.
    """
    if item is None:
        return padrao
    dependencia = getattr(item, "tp_dependencia", None)
    situacao = getattr(item, "tp_situacao_funcionamento", None)
    if dependencia and dependencia != DEPENDENCIA_PRIVADA:
        return MOTIVO_SECAO_ESCOLA_PUBLICA
    if dependencia == DEPENDENCIA_PRIVADA and situacao and situacao != SITUACAO_ATIVA:
        return MOTIVO_SECAO_ESCOLA_INATIVA
    return padrao


def _campos_do_cabecalho(escola: Any) -> dict[str, Any]:
    """Campos de cabeçalho comuns às duas rotas da ficha (nome e município)."""
    return {
        "co_entidade": escola.co_entidade,
        "no_entidade": getattr(escola, "no_entidade", None),
        "co_municipio": getattr(escola, "co_municipio", None),
        "no_municipio": getattr(escola, "no_municipio", None),
    }


def _migalhas(
    cabecalho: Mapping[str, Any], *, href_escola: str | None, ultimo: str | None
) -> list[dict[str, Any]]:
    """Itens da trilha: Escolas › município › escola [› seção atual].

    O município é link para o mercado, a escola é link para a Visão geral e o
    último item (a tela atual) não é link. Nome ausente continua ``sem dado``.
    """
    itens: list[dict[str, Any]] = [{"rotulo": "Escolas", "href": f"{PREFIXO_WEB}/"}]
    if cabecalho["co_municipio"]:
        itens.append(
            {
                "rotulo": fmt_nulo(cabecalho["no_municipio"]),
                "href": f"{PREFIXO_WEB}/mercados/{cabecalho['co_municipio']}",
            }
        )
    rotulo_escola = cabecalho["no_entidade"] or f"Escola {cabecalho['co_entidade']}"
    itens.append({"rotulo": rotulo_escola, "href": href_escola})
    if ultimo is not None:
        itens.append({"rotulo": ultimo, "href": None})
    return itens


def itens_subnav(
    *,
    cabecalho: Mapping[str, Any],
    ativo: str,
    mostra_concorrencia: bool,
) -> list[dict[str, Any]]:
    """Itens do subnav de seções da ficha — âncoras na **mesma** página (V2).

    A ficha e os indicadores viraram uma única página (card V2 `t_cbd54a92`):
    o subnav aponta para as âncoras internas ``#resumo`` e ``#concorrencia`` em
    vez de rotas separadas. "Indicadores e concorrência" só entra quando a seção
    existe para a escola (`mostra_concorrencia`); o link de saída para o mercado
    acompanha o município. ``ativo`` é mantido por compatibilidade da assinatura
    (as duas âncoras vivem na mesma tela).
    """
    itens: list[dict[str, Any]] = [
        {
            "rotulo": ROTULO_VISAO_GERAL,
            "href": "#resumo",
            "ativo": True,
            "classe": "",
        }
    ]
    if mostra_concorrencia:
        itens.append(
            {
                "rotulo": TITULO_SECAO_CONCORRENCIA,
                "href": "#concorrencia",
                "ativo": False,
                "classe": "",
            }
        )
    if cabecalho["co_municipio"]:
        itens.append(
            {
                "rotulo": (
                    "Mercado de "
                    f"{cabecalho['no_municipio'] or cabecalho['co_municipio']} →"
                ),
                "href": f"{PREFIXO_WEB}/mercados/{cabecalho['co_municipio']}",
                "ativo": False,
                "classe": "subnav__saida",
            }
        )
    return itens


def contexto_visao_geral(*, historico: HistoryResponse) -> dict[str, Any]:
    """Contexto da **Visão geral** — tudo sai da série de `history` (1 consulta).

    Indicadores e comparação municipal não vivem mais aqui: a rota própria
    (`/app/escolas/{id}/concorrencia`) é quem consulta as marts privadas. Quando
    a escola está fora do universo de privadas ativas, a página explica a
    ausência da seção sem gastar consulta — a decisão sai do item mais recente
    da série.
    """
    itens: list[HistoryItem] = list(historico.data.items)
    recente = item_mais_recente(itens)
    privada_ativa = pertence_ao_universo_privado(recente)
    cabecalho = _campos_do_cabecalho(historico.data)

    return {
        "escola": historico.data,
        "cabecalho": cabecalho,
        "sem_nome": SEM_DADO,
        "migalhas": _migalhas(cabecalho, href_escola=None, ultimo=None),
        # Entrada da comparação lado a lado (card C4): a ficha já tem o id, e o
        # destino é a página com **um** id, que oferece a busca da segunda.
        "href_comparar": (
            f"{PREFIXO_WEB}/comparar?escolas={cabecalho['co_entidade']}"
        ),
        "rotulo_comparar": ROTULO_COMPARAR_ENTRADA,
        "subnav_itens": itens_subnav(
            cabecalho=cabecalho,
            ativo=VISAO_GERAL,
            mostra_concorrencia=privada_ativa,
        ),
        "itens": itens,
        "recente": recente,
        "ano_inicial": min((item.nu_ano_censo for item in itens), default=None),
        "dependencia_rotulo": (
            rotulo_dependencia(recente.tp_dependencia) if recente else None
        ),
        "situacao_rotulo": (
            rotulo_situacao(recente.tp_situacao_funcionamento) if recente else None
        ),
        "serie": serie_matriculas(itens),
        "etapas": etapas_do_ano(recente) if recente is not None else [],
        "rendimento": rendimento_por_ano(itens),
        "colunas_rendimento": [campo.rotulo for campo in RENDIMENTO],
        # Nota fixa quando a seção de indicadores não existe para a escola.
        "motivo_concorrencia": (
            None if privada_ativa else motivo_concorrencia_nao_se_aplica(recente)
        ),
        "texto_nesta_pagina": TEXTO_NESTA_PAGINA,
        "nao_se_aplica_titulo": NAO_SE_APLICA,
        "meta": resumo_meta(historico.meta),
        "texto_oferta_desconhecida": EXPLICACAO_OFERTA_DESCONHECIDA,
    }


def contexto_concorrencia(*, indicadores: IndicatorsResponse) -> dict[str, Any]:
    """Contexto de **Indicadores e concorrência** (fonte única: indicadores).

    A comparação municipal vem da própria resposta de indicadores
    (`items[-1].competicao`, alimentada por `mart_competidores` no mesmo
    ano) — nenhuma segunda leitura da mart. Sem essa linha no ano mais recente,
    a seção mostra "sem dado" e o motivo fixo, nunca 0 (AGENTS.md §6).
    """
    itens = list(indicadores.data.items)
    recente = item_mais_recente(itens)
    ano = recente.nu_ano_censo if recente is not None else None
    competicao = contexto_competicao(
        recente.competicao if recente is not None else None, ano=ano
    )
    cabecalho = _campos_do_cabecalho(indicadores.data)

    return {
        "escola": indicadores.data,
        "cabecalho": cabecalho,
        "sem_nome": f"Escola {cabecalho['co_entidade']}",
        "migalhas": _migalhas(
            cabecalho,
            href_escola=f"{PREFIXO_WEB}/escolas/{cabecalho['co_entidade']}",
            ultimo=TITULO_SECAO_CONCORRENCIA,
        ),
        "subnav_itens": itens_subnav(
            cabecalho=cabecalho, ativo=CONCORRENCIA, mostra_concorrencia=True
        ),
        "nao_se_aplica": False,
        "ano_indicadores": ano,
        "indicadores": contexto_indicadores(recente),
        "competicao": competicao,
        "motivo_sem_comparacao": (
            None
            if competicao is not None
            else (
                MOTIVO_SEM_COMPARACAO.format(ano=ano)
                if ano is not None
                else MOTIVO_SECAO_COMPETIDORES
            )
        ),
        "meta_indicadores": resumo_meta(indicadores.meta),
        "definicao_concorrencia": DEFINICAO_CONCORRENCIA,
        "texto_abaixo_porte": EXPLICACAO_ABAIXO_PORTE,
        "aviso_abaixo_porte": AVISO_ABAIXO_PORTE in indicadores.meta.avisos,
        "nao_se_aplica_titulo": NAO_SE_APLICA,
        "titulo_secao": TITULO_SECAO_CONCORRENCIA,
    }


def contexto_concorrencia_nao_se_aplica(
    *, co_entidade: str, escola: School | None
) -> dict[str, Any]:
    """Contexto da rota de concorrência quando a seção não se aplica (200).

    O 404 de **universo** do `/v1` é estado legítimo: a página diz "não se
    aplica", explica o motivo e oferece a volta para a Visão geral. `escola`
    ausente (nada além do código INEP) mantém o cabeçalho como
    ``Escola {co_entidade}``.

    `escola` presente e **privada ativa** significa que o universo está certo e
    o que falta é a linha da mart de indicadores: o motivo é
    ``MOTIVO_SECAO_INDICADORES``, nunca ``MOTIVO_FORA_DO_UNIVERSO_PRIVADO``.
    """
    dados_escola: dict[str, Any] = {
        "co_entidade": co_entidade,
        "no_entidade": None,
        "co_municipio": None,
        "no_municipio": None,
    }
    motivo = MOTIVO_SECAO_INDICADORES
    if escola is not None:
        dados_escola.update(_campos_do_cabecalho(escola))
        motivo = motivo_concorrencia_nao_se_aplica(
            escola, padrao=MOTIVO_SECAO_INDICADORES
        )

    return {
        "escola": None,
        "cabecalho": dados_escola,
        "sem_nome": f"Escola {co_entidade}",
        "migalhas": _migalhas(
            dados_escola,
            href_escola=f"{PREFIXO_WEB}/escolas/{co_entidade}",
            ultimo=TITULO_SECAO_CONCORRENCIA,
        ),
        "subnav_itens": itens_subnav(
            cabecalho=dados_escola, ativo=CONCORRENCIA, mostra_concorrencia=True
        ),
        "nao_se_aplica": True,
        "motivo": motivo,
        "href_visao_geral": f"{PREFIXO_WEB}/escolas/{co_entidade}",
        "texto_voltar": TEXTO_VOLTAR_VISAO_GERAL,
        "nao_se_aplica_titulo": NAO_SE_APLICA,
        "titulo_secao": TITULO_SECAO_CONCORRENCIA,
        "indicadores": [],
        "competicao": None,
        "motivo_sem_comparacao": None,
        "meta_indicadores": None,
    }


# -- comparação entre duas escolas (card C4, `t_58f9adbb`) --------------------
#
# A página `/app/comparar?escolas=A,B` reusa **as mesmas** respostas de
# `history` da ficha (`dados.historico_escola`): série e oferta saem do mesmo
# item, então o custo é o da ficha por escola e nunca há consulta nova. As
# funções abaixo são puras, como as da ficha.


def _celula_por_ano(itens: Sequence[HistoryItem]) -> dict[int, dict[str, Any]]:
    """Matrícula BAS de cada ano da série, com a flag de ausência."""
    return {
        item.nu_ano_censo: {
            "valor": item.qt_mat_bas,
            "motivo": _motivo(item.is_qt_mat_bas_missing, "is_qt_mat_bas_missing"),
        }
        for item in itens
    }


def serie_comparada(
    itens_a: Sequence[HistoryItem], itens_b: Sequence[HistoryItem]
) -> dict[str, Any]:
    """Série das duas escolas, ano a ano, cobrindo a **união dos intervalos**.

    Cada ponto traz a célula de cada escola (``{"valor", "motivo"}``). Ano que
    só uma delas tem vira ``sem dado (ano ausente na fonte)`` do outro lado —
    nunca ``0`` —, e a lacuna fica visível nos dois sentidos (tabela e SVG).
    Sem nenhum ano em nenhuma das séries, não há pontos nem gráfico.
    """
    registros_a = _celula_por_ano(itens_a)
    registros_b = _celula_por_ano(itens_b)
    anos = set(registros_a) | set(registros_b)
    if not anos:
        return {"pontos": [], "svg": None}

    vazio = {"valor": None, "motivo": MOTIVO_ANO_AUSENTE}
    pontos = [
        {
            "ano": ano,
            "a": registros_a.get(ano, vazio),
            "b": registros_b.get(ano, vazio),
        }
        for ano in range(min(anos), max(anos) + 1)
    ]
    return {"pontos": pontos, "svg": svg_serie_comparada(pontos)}


def svg_serie_comparada(pontos: Sequence[dict[str, Any]]) -> Markup | None:
    """Barras agrupadas por ano, duas séries, geradas no servidor (sem JS).

    As duas séries se distinguem **também sem cor**: a de A é preenchimento
    sólido (`.serie__barra`) e a de B é só contorno tracejado
    (`.serie__barra--b`). A legenda textual fica na figura e o equivalente
    acessível é a tabela; o SVG é decorativo (`aria-hidden`), como na ficha.
    ``None`` quando nenhuma das escolas tem matrícula observada.
    """
    observados = [
        int(celula["valor"])
        for ponto in pontos
        for celula in (ponto["a"], ponto["b"])
        if celula["valor"] is not None
    ]
    if not observados:
        return None

    maximo = max(observados) or 1
    margem_esq, margem_dir = 8, 8
    margem_topo, margem_base = 18, 26
    largura_util = LARGURA_SVG - margem_esq - margem_dir
    altura_util = ALTURA_SVG - margem_topo - margem_base
    passo = largura_util / max(len(pontos), 1)
    largura_barra = max(min(22.0, passo * 0.26), 3.0)
    base = margem_topo + altura_util

    partes: list[str] = [
        f'<line x1="{margem_esq}" y1="{base:.1f}" '
        f'x2="{LARGURA_SVG - margem_dir}" y2="{base:.1f}" class="serie__eixo"/>'
    ]
    series = ((-0.62, "a", "serie__barra"), (0.62, "b", "serie__barra serie__barra--b"))
    for indice, ponto in enumerate(pontos):
        centro = margem_esq + passo * (indice + 0.5)
        partes.append(
            f'<text x="{centro:.1f}" y="{ALTURA_SVG - 8}" text-anchor="middle" '
            f'class="serie__ano">{int(ponto["ano"])}</text>'
        )
        for deslocamento, chave, classe in series:
            eixo_barra = centro + deslocamento * largura_barra
            valor = ponto[chave]["valor"]
            if valor is None:
                # Lacuna: marca a ausência sem desenhar barra de altura zero.
                partes.append(
                    f'<line x1="{eixo_barra:.1f}" y1="{base:.1f}" '
                    f'x2="{eixo_barra:.1f}" y2="{base - 6:.1f}" class="serie__ausente"/>'
                )
                continue
            altura = max(altura_util * int(valor) / maximo, ALTURA_MINIMA_BARRA)
            partes.append(
                f'<rect x="{eixo_barra - largura_barra / 2:.1f}" '
                f'y="{base - altura:.1f}" width="{largura_barra:.1f}" '
                f'height="{altura:.1f}" class="{classe}"/>'
            )

    return Markup(
        f'<svg class="serie" viewBox="0 0 {LARGURA_SVG} {ALTURA_SVG}" '
        f'aria-hidden="true" xmlns="http://www.w3.org/2000/svg">'
        f'{"".join(partes)}</svg>'
    )


def etapas_comparadas(escola_a: HistoryItem, escola_b: HistoryItem) -> list[dict[str, Any]]:
    """Oferta e matrícula por etapa das duas escolas **no mesmo ano**.

    Reusa `_linha_etapa` (a mesma leitura tri-estado da ficha) para cada lado e
    mantém os grupos de `GRUPOS_ETAPAS`: total oficial, etapas que somam e
    modalidades que não somam continuam separados — lado a lado, somar as nove
    linhas somaria duas vezes.
    """
    grupos: list[dict[str, Any]] = []
    for grupo in GRUPOS_ETAPAS:
        linhas: list[dict[str, Any]] = []
        for etapa in grupo.etapas:
            campo = CAMPOS_MATRICULA[etapa]
            linha_a = _linha_etapa(escola_a, campo)
            linha_b = _linha_etapa(escola_b, campo)
            linhas.append(
                {
                    "rotulo": linha_a["rotulo"],
                    "oferta_a": linha_a["oferta"],
                    "matricula_a": linha_a["matricula"],
                    "oferta_b": linha_b["oferta"],
                    "matricula_b": linha_b["matricula"],
                }
            )
        grupos.append({"titulo": grupo.titulo, "nota": grupo.nota, "linhas": linhas})
    return grupos


def _escola_comparada(escola: Any) -> dict[str, Any]:
    """Identificação de um lado da comparação (nome, município e link da ficha)."""
    cabecalho = _campos_do_cabecalho(escola)
    co_entidade = cabecalho["co_entidade"]
    return {
        **cabecalho,
        "rotulo": cabecalho["no_entidade"] or f"Escola {co_entidade}",
        "href": f"{PREFIXO_WEB}/escolas/{co_entidade}",
    }


def _recorte_comparacao(historicos: Sequence[HistoryResponse]) -> dict[str, Any]:
    """Recorte da comparação: universo, fonte e avisos das duas respostas.

    Não existe "ano de referência" único (cada série tem o seu), então o bloco
    declara o recorte comum — universo, fonte e avisos, na ordem em que
    aparecem — em vez de repetir um ano que valeria só para um dos lados.
    """
    meta = historicos[0].meta
    avisos: list[str] = []
    for historico in historicos:
        for texto in traduzir_avisos(historico.meta.avisos):
            if texto not in avisos:
                avisos.append(texto)
    return {
        "universo": meta.universo,
        "universo_texto": UNIVERSOS.get(meta.universo),
        "orgao": meta.fonte.orgao,
        "base": meta.fonte.base,
        "tabela": meta.fonte.tabela,
        "avisos": avisos,
    }


def _escola_unica(historico: HistoryResponse) -> dict[str, Any]:
    """Escola A da página com um só id: identificação, série e leitura INEP."""
    itens = list(historico.data.items)
    recente = item_mais_recente(itens)
    return {
        "cabecalho": _campos_do_cabecalho(historico.data),
        "recente": recente,
        "itens": itens,
        "serie": serie_matriculas(itens),
        "dependencia_rotulo": (
            rotulo_dependencia(recente.tp_dependencia) if recente is not None else None
        ),
        "situacao_rotulo": (
            rotulo_situacao(recente.tp_situacao_funcionamento)
            if recente is not None
            else None
        ),
    }


def contexto_comparacao(
    *, historicos: Sequence[HistoryResponse]
) -> dict[str, Any]:
    """Contexto de `/app/comparar?escolas=` com um ou dois ids.

    Com **dois** ids: série comparada (união dos intervalos), oferta por etapa
    do ano mais recente **comum** às duas escolas e o aviso de municípios
    diferentes. Com **um** id: a escola A (identificação + série) e nada de
    comparação — quem escolhe a segunda escola é o formulário de busca da
    própria página.
    """
    escolas = [_escola_comparada(historico.data) for historico in historicos]
    contexto: dict[str, Any] = {
        "escolas": escolas,
        "duas": len(historicos) == 2,
        "escola_unica": None,
        "titulo_secao": TITULO_COMPARACAO,
        "migalhas": [
            {"rotulo": "Escolas", "href": f"{PREFIXO_WEB}/"},
            {"rotulo": TITULO_COMPARACAO, "href": None},
        ],
        "recorte": _recorte_comparacao(historicos),
        "aviso_municipios": None,
        "serie": {"pontos": [], "svg": None},
        "ano_comum": None,
        "motivo_sem_ano_comum": None,
        "etapas": [],
    }
    if len(historicos) == 1:
        contexto["escola_unica"] = _escola_unica(historicos[0])
        return contexto

    itens_a = list(historicos[0].data.items)
    itens_b = list(historicos[1].data.items)
    contexto["serie"] = serie_comparada(itens_a, itens_b)

    anos_a = {item.nu_ano_censo for item in itens_a}
    anos_b = {item.nu_ano_censo for item in itens_b}
    comuns = sorted(anos_a & anos_b)
    if not comuns:
        contexto["motivo_sem_ano_comum"] = MOTIVO_SEM_ANO_COMUM
    else:
        ano_comum = comuns[-1]
        contexto["ano_comum"] = ano_comum
        contexto["etapas"] = etapas_comparadas(
            next(item for item in itens_a if item.nu_ano_censo == ano_comum),
            next(item for item in itens_b if item.nu_ano_censo == ano_comum),
        )

    municipios = {escola["co_municipio"] for escola in escolas if escola["co_municipio"]}
    if len(municipios) > 1:
        contexto["aviso_municipios"] = MOTIVO_MUNICIPIOS_DIFERENTES
    return contexto


__all__ = [
    "CONCORRENCIA",
    "VISAO_GERAL",
    "contexto_comparacao",
    "contexto_concorrencia",
    "contexto_concorrencia_na_ficha",
    "contexto_concorrencia_nao_se_aplica",
    "contexto_visao_geral",
    "etapas_comparadas",
    "item_mais_recente",
    "itens_subnav",
    "kpis_da_escola",
    "motivo_concorrencia_nao_se_aplica",
    "pertence_ao_universo_privado",
    "posicao_crescimento",
    "ranking_municipal",
    "rotulo_dependencia",
    "rotulo_situacao",
    "serie_comparada",
    "texto_variacao",
    "total_privadas_ativas",
    "svg_serie_comparada",
]
