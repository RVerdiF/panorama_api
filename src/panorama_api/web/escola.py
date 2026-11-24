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

from typing import Any, NamedTuple, Protocol, Sequence, TypeVar

from markupsafe import Markup

from panorama_api.contract import Etapa
from panorama_api.schemas.common import Meta
from panorama_api.schemas.competitors import CompetitorsResponse
from panorama_api.schemas.indicators import IndicatorItem, IndicatorsResponse
from panorama_api.schemas.schools import HistoryItem, HistoryResponse
from panorama_api.web.conteudo import (
    DEFINICAO_CONCORRENCIA,
    EXPLICACAO_ABAIXO_PORTE,
    EXPLICACAO_OFERTA_DESCONHECIDA,
    MOTIVO_ANO_AUSENTE,
    MOTIVO_FORA_DO_UNIVERSO_PRIVADO,
    MOTIVO_SECAO_COMPETIDORES,
    MOTIVO_SECAO_INDICADORES,
    NAO_SE_APLICA,
    ROTULO_POSICAO_CRESCIMENTO_MG,
    ROTULO_POSICAO_CRESCIMENTO_MUNICIPIO,
    ROTULO_RETENCAO,
    UNIVERSOS,
    rotulo_etapa,
    traduzir_aviso,
)

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


def _rotulo_dependencia(codigo: str | None) -> str:
    """Leitura do código INEP de dependência (1 Federal … 4 Privada).

    Código ausente é "não informado" e código fora da tabela é "código não
    reconhecido": nenhum dos dois vira "não privada", que colapsaria Federal,
    Estadual e Municipal numa classificação que o INEP não usa.
    """
    if not codigo:
        return ROTULO_NAO_INFORMADO
    return ROTULOS_DEPENDENCIA.get(codigo, ROTULO_NAO_RECONHECIDO)


def _rotulo_situacao(codigo: str | None) -> str:
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
    return {"pontos": pontos, "svg": svg_serie(pontos)}


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
    return pontos


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


def etapas_do_ano(item: HistoryItem) -> list[dict[str, Any]]:
    """Uma linha por etapa do ano de referência: oferta tri-estado + matrícula.

    Oferta e matrícula vêm do MESMO item (mesmo ano censitário); a matrícula
    carrega a flag de ausência para que `null` nunca vire `0`.
    """
    return [
        {
            "rotulo": rotulo_etapa(campo.etapa),
            "oferta": getattr(item.oferta, campo.etapa),
            "matricula": _celula(
                getattr(item, campo.campo),
                motivo=_motivo(getattr(item, campo.flag), campo.flag),
            ),
        }
        for campo in MATRICULAS
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


def contexto_competicao(item: Any | None) -> dict[str, Any] | None:
    """Posição municipal do ano mais recente de `mart_competidores`."""
    if item is None:
        return None
    return {
        "ano": item.nu_ano_censo,
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


def _motivo_da_secao(
    *, privada_ativa: bool, nao_se_aplica: bool, motivo_mart: str
) -> str | None:
    """Texto único da seção que não se aplica (``None`` = seção existe).

    Três estados, sem misturar diagnóstico da API com a explicação da tela:
    fora do universo de privadas ativas, 404 residual da mart, ou seção normal.
    """
    if not privada_ativa:
        return MOTIVO_FORA_DO_UNIVERSO_PRIVADO
    if nao_se_aplica:
        return motivo_mart
    return None


def contexto_escola(
    *,
    historico: HistoryResponse,
    indicadores: IndicatorsResponse | None,
    concorrentes: CompetitorsResponse | None,
    nao_se_aplica: Sequence[str],
) -> dict[str, Any]:
    """Contexto completo do template a partir das respostas (já obtidas) do `/v1`.

    `nao_se_aplica` lista as seções cujo `/v1` respondeu 404 de universo
    (escola privada ativa sem a linha do ano nas marts).
    """
    itens: list[HistoryItem] = list(historico.data.items)
    recente = item_mais_recente(itens)
    privada_ativa = pertence_ao_universo_privado(recente)
    sem_secao = set(nao_se_aplica)

    indicador_recente = (
        item_mais_recente(indicadores.data.items) if indicadores is not None else None
    )
    competidor_recente = (
        item_mais_recente(concorrentes.data.items) if concorrentes is not None else None
    )

    return {
        "escola": historico.data,
        "itens": itens,
        "recente": recente,
        "ano_inicial": min((item.nu_ano_censo for item in itens), default=None),
        "dependencia_rotulo": (
            _rotulo_dependencia(recente.tp_dependencia) if recente else None
        ),
        "situacao_rotulo": (
            _rotulo_situacao(recente.tp_situacao_funcionamento) if recente else None
        ),
        "serie": serie_matriculas(itens),
        "etapas": etapas_do_ano(recente) if recente is not None else [],
        "rendimento": rendimento_por_ano(itens),
        "colunas_rendimento": [campo.rotulo for campo in RENDIMENTO],
        "indicadores": contexto_indicadores(indicador_recente),
        "competicao": contexto_competicao(competidor_recente),
        "motivo_indicadores": _motivo_da_secao(
            privada_ativa=privada_ativa,
            nao_se_aplica="indicadores" in sem_secao,
            motivo_mart=MOTIVO_SECAO_INDICADORES,
        ),
        "motivo_competidores": _motivo_da_secao(
            privada_ativa=privada_ativa,
            nao_se_aplica="competidores" in sem_secao,
            motivo_mart=MOTIVO_SECAO_COMPETIDORES,
        ),
        "nao_se_aplica_titulo": NAO_SE_APLICA,
        "meta": resumo_meta(historico.meta),
        "meta_indicadores": resumo_meta(indicadores.meta) if indicadores else None,
        "meta_competidores": resumo_meta(concorrentes.meta) if concorrentes else None,
        "definicao_concorrencia": DEFINICAO_CONCORRENCIA,
        "texto_oferta_desconhecida": EXPLICACAO_OFERTA_DESCONHECIDA,
        "texto_abaixo_porte": EXPLICACAO_ABAIXO_PORTE,
        "aviso_abaixo_porte": bool(
            indicadores is not None and AVISO_ABAIXO_PORTE in indicadores.meta.avisos
        ),
    }


__all__ = ["contexto_escola", "item_mais_recente", "pertence_ao_universo_privado"]
