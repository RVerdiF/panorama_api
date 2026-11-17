"""Schemas de `/v1/schools/{co_entidade}/indicators`."""

from __future__ import annotations

from pydantic import BaseModel, Field

from panorama_api.schemas.common import Envelope


class Competicao(BaseModel):
    """Linha de `mart_competidores` (mesmo grão da escola-ano)."""

    no_entidade: str | None
    co_municipio: str | None
    qt_mat_bas: int | None
    rank_mat_bas_municipio: int | None
    n_concorrentes_privados_municipio: int | None
    n_concorrentes_com_matricula_bas: int | None
    n_concorrentes_creche_xself: int | None
    n_concorrentes_pre_xself: int | None
    n_concorrentes_fund_ai_xself: int | None
    n_concorrentes_fund_af_xself: int | None
    n_concorrentes_med_xself: int | None
    lider_no_entidade: str | None
    lider_qt_mat_bas: int | None
    gap_mat_bas_para_lider: int | None


class IndicatorItem(BaseModel):
    """Linha de `mart_escola_indicadores` (privadas ativas MG, base BAS)."""

    co_entidade: str
    nu_ano_censo: int
    no_entidade: str | None
    co_municipio: str | None
    no_municipio: str | None
    cnpj_raiz_mantenedora: str | None
    is_cnpj_generic: bool | None
    is_oferta_desconhecida: bool | None

    qt_mat_bas: int | None
    is_qt_mat_bas_missing: bool | None
    qt_mat_creche: int | None
    qt_mat_pre: int | None
    qt_mat_fund_ai: int | None
    qt_mat_fund_af: int | None
    qt_mat_med: int | None
    qt_mat_prof: int | None
    qt_mat_eja: int | None
    qt_mat_esp: int | None

    prev_qt_mat_bas: int | None
    crescimento_yoy_pct: float | None
    saldo_serie_matriculas: int | None
    retencao_liquida_proxy_pct: float | None = Field(
        description=(
            "Proxy de retenção líquida (saldo de série): mat_t / mat_{t-1} × 100. "
            "Não é taxa de evasão."
        )
    )
    cagr_pct: float | None
    ano_ini_cagr: int | None
    ano_fim_cagr: int | None

    tx_aprov_fund_t: float | None
    tx_reprov_fund_t: float | None
    tx_aband_fund_t: float | None
    tx_aprov_med_t: float | None
    tx_reprov_med_t: float | None
    tx_aband_med_t: float | None
    is_tx_aprov_fund_t_missing: bool | None
    is_tx_aprov_med_t_missing: bool | None
    is_tx_reprov_fund_t_missing: bool | None
    is_tx_aband_fund_t_missing: bool | None

    share_privado_pct: float | None
    share_total_pct: float | None
    is_abaixo_porte: bool | None
    hhi_municipio_priv_escola_bas: float | None
    rank_mat_municipio: int | None
    rank_crec_municipio: int | None
    rank_crec_mg: int | None
    flg_entrou_mercado: bool | None
    n_etapas_metodologia_incomparavel: int | None

    competicao: Competicao | None = Field(
        default=None,
        description=(
            "Ranking só com matrícula observada; `null` quando a escola-ano não tem "
            "linha em `mart_competidores`."
        ),
    )


class Indicators(BaseModel):
    co_entidade: str
    no_entidade: str | None
    co_municipio: str | None
    no_municipio: str | None
    items: list[IndicatorItem] = Field(description="Ordenado por nu_ano_censo ASC.")


class IndicatorsResponse(Envelope[Indicators]):
    pass
