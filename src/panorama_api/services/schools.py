"""Casos de uso de escola: busca, histórico e indicadores."""

from __future__ import annotations

from typing import Any, Mapping

from panorama_api.config import Settings
from panorama_api.contract import (
    DEFINICAO_RETENCAO,
    UNIVERSO_ESCOLAS_MG,
    UNIVERSO_PRIVADAS_ATIVAS_MG,
)
from panorama_api.core.errors import ano_fora_do_contrato, not_found
from panorama_api.repositories.serving import ServingRepository
from panorama_api.schemas.common import avisos_metodologia, build_meta, page_from
from panorama_api.schemas.competitors import (
    Competitors,
    CompetitorsResponse,
    CompetitorItem,
)
from panorama_api.schemas.indicators import (
    Competicao,
    IndicatorItem,
    Indicators,
    IndicatorsResponse,
)
from panorama_api.schemas.schools import (
    History,
    HistoryItem,
    HistoryResponse,
    School,
    SchoolsResponse,
)
from panorama_api.services.mappers import flags_abaixo_porte, oferta

TABELA_ESCOLA = "dim_escola"
TABELA_HISTORICO = "mart_escola"
TABELA_INDICADORES = "mart_escola_indicadores"
TABELA_COMPETIDORES = "mart_competidores"

#: Descrição obrigatória da comparação servida por `/competitors` (card t_318e6f3e):
#: a unidade de comparação é o município e o ano censitário.
DESCRICAO_COMPETIDORES = "Escolas privadas ativas no mesmo município e ano censitário (MG)"


def _school(row: Mapping[str, Any]) -> School:
    return School(
        co_entidade=row["co_entidade"],
        no_entidade=row.get("no_entidade"),
        co_municipio=row.get("co_municipio"),
        no_municipio=row.get("no_municipio"),
        sg_uf=row.get("sg_uf"),
        tp_dependencia=row.get("tp_dependencia"),
        tp_categoria_escola_privada=row.get("tp_categoria_escola_privada"),
        tp_localizacao=row.get("tp_localizacao"),
        tp_situacao_funcionamento=row.get("tp_situacao_funcionamento"),
        cnpj_raiz_mantenedora=row.get("cnpj_raiz_mantenedora"),
        is_cnpj_generic=row.get("is_cnpj_generic"),
        oferta=oferta(row),
        is_oferta_desconhecida=row.get("is_oferta_desconhecida"),
        nu_ano_ultimo_registro=row.get("nu_ano_ultimo_registro"),
        n_anos_serie=row.get("n_anos_serie"),
        ano_primeiro_registro=row.get("ano_primeiro_registro"),
        ano_ultimo_registro=row.get("ano_ultimo_registro"),
    )


def _ano_mais_recente(rows: list[Mapping[str, Any]], campo: str) -> int | None:
    anos = [row[campo] for row in rows if row.get(campo) is not None]
    return max(anos) if anos else None


def search_schools(
    repository: ServingRepository,
    settings: Settings,
    *,
    q: str | None,
    co_entidade: str | None,
    co_municipio: str | None,
    tp_dependencia: str | None,
    apenas_ativas: bool,
    limit: int,
    offset: int,
) -> SchoolsResponse:
    fetched = repository.search_schools(
        q=q,
        co_entidade=co_entidade,
        co_municipio=co_municipio,
        tp_dependencia=tp_dependencia,
        apenas_ativas=apenas_ativas,
        limit=limit,
        offset=offset,
    )
    if not fetched and co_entidade is not None:
        # Lookup por identidade (código INEP): vazio é ausência, não busca sem resultado.
        raise not_found(f"escola {co_entidade} não encontrada no recorte MG")

    rows, page = page_from(fetched, limit=limit, offset=offset)
    meta = build_meta(
        contract_version=settings.contract_version,
        ano_referencia=_ano_mais_recente(rows, "nu_ano_ultimo_registro"),
        etapa="bas",
        universo=UNIVERSO_ESCOLAS_MG,
        tabela=TABELA_ESCOLA,
    )
    return SchoolsResponse(data=[_school(row) for row in rows], meta=meta, page=page)


def _history_item(row: Mapping[str, Any]) -> HistoryItem:
    return HistoryItem(
        nu_ano_censo=row["nu_ano_censo"],
        tp_dependencia=row.get("tp_dependencia"),
        tp_categoria_escola_privada=row.get("tp_categoria_escola_privada"),
        tp_localizacao=row.get("tp_localizacao"),
        tp_situacao_funcionamento=row.get("tp_situacao_funcionamento"),
        cnpj_raiz_mantenedora=row.get("cnpj_raiz_mantenedora"),
        is_cnpj_generic=row.get("is_cnpj_generic"),
        oferta=oferta(row),
        is_oferta_desconhecida=row.get("is_oferta_desconhecida"),
        qt_mat_bas=row.get("qt_mat_bas"),
        is_qt_mat_bas_missing=row.get("is_qt_mat_bas_missing"),
        qt_mat_creche=row.get("qt_mat_creche"),
        is_qt_mat_creche_missing=row.get("is_qt_mat_creche_missing"),
        qt_mat_pre=row.get("qt_mat_pre"),
        is_qt_mat_pre_missing=row.get("is_qt_mat_pre_missing"),
        qt_mat_fund_ai=row.get("qt_mat_fund_ai"),
        is_qt_mat_fund_ai_missing=row.get("is_qt_mat_fund_ai_missing"),
        qt_mat_fund_af=row.get("qt_mat_fund_af"),
        is_qt_mat_fund_af_missing=row.get("is_qt_mat_fund_af_missing"),
        qt_mat_med=row.get("qt_mat_med"),
        is_qt_mat_med_missing=row.get("is_qt_mat_med_missing"),
        qt_mat_prof=row.get("qt_mat_prof"),
        is_qt_mat_prof_missing=row.get("is_qt_mat_prof_missing"),
        qt_mat_eja=row.get("qt_mat_eja"),
        is_qt_mat_eja_missing=row.get("is_qt_mat_eja_missing"),
        qt_mat_esp=row.get("qt_mat_esp"),
        is_qt_mat_esp_missing=row.get("is_qt_mat_esp_missing"),
        n_etapas_metodologia_incomparavel=row.get("n_etapas_metodologia_incomparavel"),
        tx_aprov_fund_t=row.get("tx_aprov_fund_t"),
        tx_aprov_fund_ai=row.get("tx_aprov_fund_ai"),
        tx_aprov_fund_af=row.get("tx_aprov_fund_af"),
        tx_aprov_med_t=row.get("tx_aprov_med_t"),
        tx_reprov_fund_t=row.get("tx_reprov_fund_t"),
        tx_reprov_fund_ai=row.get("tx_reprov_fund_ai"),
        tx_reprov_fund_af=row.get("tx_reprov_fund_af"),
        tx_reprov_med_t=row.get("tx_reprov_med_t"),
        tx_aband_fund_t=row.get("tx_aband_fund_t"),
        tx_aband_fund_ai=row.get("tx_aband_fund_ai"),
        tx_aband_fund_af=row.get("tx_aband_fund_af"),
        tx_aband_med_t=row.get("tx_aband_med_t"),
        is_tx_aprov_fund_t_missing=row.get("is_tx_aprov_fund_t_missing"),
        is_tx_aprov_fund_ai_missing=row.get("is_tx_aprov_fund_ai_missing"),
        is_tx_aprov_fund_af_missing=row.get("is_tx_aprov_fund_af_missing"),
        is_tx_aprov_med_t_missing=row.get("is_tx_aprov_med_t_missing"),
        is_tx_reprov_fund_t_missing=row.get("is_tx_reprov_fund_t_missing"),
        is_tx_aband_fund_t_missing=row.get("is_tx_aband_fund_t_missing"),
        latitude=row.get("latitude"),
        longitude=row.get("longitude"),
        geocode_precision=row.get("geocode_precision"),
        confidence_score=row.get("confidence_score"),
        needs_review=row.get("needs_review"),
    )


def school_history(
    repository: ServingRepository,
    settings: Settings,
    *,
    co_entidade: str,
    ano_inicio: int | None,
    ano_fim: int | None,
) -> HistoryResponse:
    rows = repository.get_school_history(
        co_entidade=co_entidade, ano_inicio=ano_inicio, ano_fim=ano_fim
    )
    if not rows:
        raise not_found(
            f"escola {co_entidade} não encontrada no recorte MG"
            + (" para o intervalo pedido" if ano_inicio or ano_fim else "")
        )

    mais_recente = rows[-1]  # ORDER BY nu_ano_censo ASC
    meta = build_meta(
        contract_version=settings.contract_version,
        ano_referencia=mais_recente["nu_ano_censo"],
        etapa="bas",
        universo=UNIVERSO_ESCOLAS_MG,
        tabela=TABELA_HISTORICO,
        avisos=avisos_metodologia(rows),
    )
    data = History(
        co_entidade=mais_recente["co_entidade"],
        no_entidade=mais_recente.get("no_entidade"),
        co_municipio=mais_recente.get("co_municipio"),
        no_municipio=mais_recente.get("no_municipio"),
        items=[_history_item(row) for row in rows],
    )
    return HistoryResponse(data=data, meta=meta)


def _competicao_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """Campos de `mart_competidores` comuns a `/indicators` e `/competitors`."""
    return {
        "no_entidade": row.get("no_entidade"),
        "co_municipio": row.get("co_municipio"),
        "qt_mat_bas": row.get("qt_mat_bas"),
        "rank_mat_bas_municipio": row.get("rank_mat_bas_municipio"),
        "n_concorrentes_privados_municipio": row.get("n_concorrentes_privados_municipio"),
        "n_concorrentes_com_matricula_bas": row.get("n_concorrentes_com_matricula_bas"),
        "n_concorrentes_creche_xself": row.get("n_concorrentes_creche_xself"),
        "n_concorrentes_pre_xself": row.get("n_concorrentes_pre_xself"),
        "n_concorrentes_fund_ai_xself": row.get("n_concorrentes_fund_ai_xself"),
        "n_concorrentes_fund_af_xself": row.get("n_concorrentes_fund_af_xself"),
        "n_concorrentes_med_xself": row.get("n_concorrentes_med_xself"),
        "lider_no_entidade": row.get("lider_no_entidade"),
        "lider_qt_mat_bas": row.get("lider_qt_mat_bas"),
        "gap_mat_bas_para_lider": row.get("gap_mat_bas_para_lider"),
    }


def _competicao(row: Mapping[str, Any] | None) -> Competicao | None:
    if row is None:
        return None
    return Competicao(**_competicao_fields(row))


def school_competitors(
    repository: ServingRepository,
    settings: Settings,
    *,
    co_entidade: str,
) -> CompetitorsResponse:
    """Comparação MUNICIPAL da escola (privadas ativas no mesmo município/ano).

    Escola fora do recorte da mart — pública, inativa, fora de MG ou sem matrícula
    BAS — não tem linha: 404, nunca 200 com zeros ou lista vazia. Pública/inativa
    é distinguível em `dim_escola` e recebe detalhe explicando o universo.
    """
    rows = repository.get_school_competidores(co_entidade=co_entidade)
    if not rows:
        school = repository.get_school(co_entidade)
        if school is None:
            raise not_found(f"escola {co_entidade} não encontrada no recorte MG")
        if school.get("tp_dependencia") != "4":
            raise not_found(
                f"escola {co_entidade} não pertence ao universo de competidores "
                "(privadas ativas MG)"
            )
        if school.get("tp_situacao_funcionamento") != "1":
            raise not_found(
                f"escola {co_entidade} não pertence ao universo de competidores "
                "(privadas ativas MG)"
            )
        # Privada ativa em MG sem linha na mart: sem matrícula BAS observada —
        # ausência de dado nunca vira 0 concorrentes.
        raise not_found(
            f"escola {co_entidade} não tem matrícula BAS observada para comparar "
            "no município"
        )

    mais_recente = rows[-1]  # ORDER BY nu_ano_censo ASC
    meta = build_meta(
        contract_version=settings.contract_version,
        ano_referencia=mais_recente["nu_ano_censo"],
        etapa="bas",
        universo=UNIVERSO_PRIVADAS_ATIVAS_MG,
        tabela=TABELA_COMPETIDORES,
        definicoes={"competidores": DESCRICAO_COMPETIDORES},
    )
    data = Competitors(
        co_entidade=mais_recente["co_entidade"],
        no_entidade=mais_recente.get("no_entidade"),
        co_municipio=mais_recente.get("co_municipio"),
        items=[
            CompetitorItem(
                nu_ano_censo=row["nu_ano_censo"], **_competicao_fields(row)
            )
            for row in rows
        ],
    )
    return CompetitorsResponse(data=data, meta=meta)


def _indicator(row: Mapping[str, Any], competidores: Mapping[int, Mapping[str, Any]]) -> IndicatorItem:
    return IndicatorItem(
        co_entidade=row["co_entidade"],
        nu_ano_censo=row["nu_ano_censo"],
        no_entidade=row.get("no_entidade"),
        co_municipio=row.get("co_municipio"),
        no_municipio=row.get("no_municipio"),
        cnpj_raiz_mantenedora=row.get("cnpj_raiz_mantenedora"),
        is_cnpj_generic=row.get("is_cnpj_generic"),
        is_oferta_desconhecida=row.get("is_oferta_desconhecida"),
        qt_mat_bas=row.get("qt_mat_bas"),
        is_qt_mat_bas_missing=row.get("is_qt_mat_bas_missing"),
        qt_mat_creche=row.get("qt_mat_creche"),
        qt_mat_pre=row.get("qt_mat_pre"),
        qt_mat_fund_ai=row.get("qt_mat_fund_ai"),
        qt_mat_fund_af=row.get("qt_mat_fund_af"),
        qt_mat_med=row.get("qt_mat_med"),
        qt_mat_prof=row.get("qt_mat_prof"),
        qt_mat_eja=row.get("qt_mat_eja"),
        qt_mat_esp=row.get("qt_mat_esp"),
        prev_qt_mat_bas=row.get("prev_qt_mat_bas"),
        crescimento_yoy_pct=row.get("crescimento_yoy_pct"),
        saldo_serie_matriculas=row.get("saldo_serie_matriculas"),
        retencao_liquida_proxy_pct=row.get("retencao_liquida_proxy_pct"),
        cagr_pct=row.get("cagr_pct"),
        ano_ini_cagr=row.get("ano_ini_cagr"),
        ano_fim_cagr=row.get("ano_fim_cagr"),
        tx_aprov_fund_t=row.get("tx_aprov_fund_t"),
        tx_reprov_fund_t=row.get("tx_reprov_fund_t"),
        tx_aband_fund_t=row.get("tx_aband_fund_t"),
        tx_aprov_med_t=row.get("tx_aprov_med_t"),
        tx_reprov_med_t=row.get("tx_reprov_med_t"),
        tx_aband_med_t=row.get("tx_aband_med_t"),
        is_tx_aprov_fund_t_missing=row.get("is_tx_aprov_fund_t_missing"),
        is_tx_aprov_med_t_missing=row.get("is_tx_aprov_med_t_missing"),
        is_tx_reprov_fund_t_missing=row.get("is_tx_reprov_fund_t_missing"),
        is_tx_aband_fund_t_missing=row.get("is_tx_aband_fund_t_missing"),
        share_privado_pct=row.get("share_privado_pct"),
        share_total_pct=row.get("share_total_pct"),
        is_abaixo_porte=row.get("is_abaixo_porte"),
        hhi_municipio_priv_escola_bas=row.get("hhi_municipio_priv_escola_bas"),
        rank_mat_municipio=row.get("rank_mat_municipio"),
        rank_crec_municipio=row.get("rank_crec_municipio"),
        rank_crec_mg=row.get("rank_crec_mg"),
        flg_entrou_mercado=row.get("flg_entrou_mercado"),
        n_etapas_metodologia_incomparavel=row.get("n_etapas_metodologia_incomparavel"),
        competicao=_competicao(competidores.get(row["nu_ano_censo"])),
    )


def school_indicators(
    repository: ServingRepository,
    settings: Settings,
    *,
    co_entidade: str,
    ano: int | None,
) -> IndicatorsResponse:
    rows = repository.get_school_indicators(co_entidade=co_entidade, ano=ano)
    if not rows:
        school = repository.get_school(co_entidade)
        if school is None:
            raise not_found(f"escola {co_entidade} não encontrada no recorte MG")
        if ano is not None:
            disponiveis = repository.get_school_indicators(co_entidade=co_entidade, ano=None)
            if disponiveis:
                anos = sorted(row["nu_ano_censo"] for row in disponiveis)
                raise ano_fora_do_contrato(
                    f"escola {co_entidade} não tem indicadores em {ano}; "
                    f"anos disponíveis: {', '.join(str(a) for a in anos)}"
                )
        # Escola existe em MG mas fora do universo de indicadores (ex.: pública/inativa).
        raise not_found(
            f"escola {co_entidade} não pertence ao universo de indicadores "
            "(privadas ativas MG)"
        )

    competidores = {
        row["nu_ano_censo"]: row
        for row in repository.get_school_competidores(co_entidade=co_entidade)
    }
    mais_recente = rows[-1]
    meta = build_meta(
        contract_version=settings.contract_version,
        ano_referencia=mais_recente["nu_ano_censo"],
        etapa="bas",
        universo=UNIVERSO_PRIVADAS_ATIVAS_MG,
        tabela=TABELA_INDICADORES,
        avisos=avisos_metodologia(rows) + flags_abaixo_porte(rows),
        definicoes={"retencao_liquida_proxy_pct": DEFINICAO_RETENCAO},
    )
    data = Indicators(
        co_entidade=mais_recente["co_entidade"],
        no_entidade=mais_recente.get("no_entidade"),
        co_municipio=mais_recente.get("co_municipio"),
        no_municipio=mais_recente.get("no_municipio"),
        items=[_indicator(row, competidores) for row in rows],
    )
    return IndicatorsResponse(data=data, meta=meta)
