"""Schemas de `/v1/schools` e `/v1/schools/{co_entidade}/history`."""

from __future__ import annotations

from pydantic import BaseModel, Field

from panorama_api.schemas.common import Envelope, PagedEnvelope


class Oferta(BaseModel):
    """Oferta tri-estado: `true` = matrícula > 0, `false` = zero declarado,
    `null` = desconhecido. `null` **não** significa "sem oferta".
    """

    bas: bool | None = None
    creche: bool | None = None
    pre: bool | None = None
    fund_ai: bool | None = None
    fund_af: bool | None = None
    med: bool | None = None
    prof: bool | None = None
    eja: bool | None = None
    esp: bool | None = None


class School(BaseModel):
    """Linha de `dim_escola` (1 linha por escola; último ano observado)."""

    co_entidade: str
    no_entidade: str | None
    co_municipio: str | None
    no_municipio: str | None
    sg_uf: str | None
    tp_dependencia: str | None
    tp_categoria_escola_privada: str | None
    tp_localizacao: str | None
    tp_situacao_funcionamento: str | None
    cnpj_raiz_mantenedora: str | None
    is_cnpj_generic: bool | None
    oferta: Oferta
    is_oferta_desconhecida: bool | None
    nu_ano_ultimo_registro: int | None
    n_anos_serie: int | None
    ano_primeiro_registro: int | None
    ano_ultimo_registro: int | None


class HistoryItem(BaseModel):
    """Uma linha de `mart_escola` (grão `co_entidade × nu_ano_censo`), sem `geom`."""

    nu_ano_censo: int
    tp_dependencia: str | None
    tp_categoria_escola_privada: str | None
    tp_localizacao: str | None
    tp_situacao_funcionamento: str | None
    cnpj_raiz_mantenedora: str | None
    is_cnpj_generic: bool | None

    oferta: Oferta
    is_oferta_desconhecida: bool | None

    # matrícula (NULL preservado + flag real)
    qt_mat_bas: int | None
    is_qt_mat_bas_missing: bool | None
    qt_mat_creche: int | None
    is_qt_mat_creche_missing: bool | None
    qt_mat_pre: int | None
    is_qt_mat_pre_missing: bool | None
    qt_mat_fund_ai: int | None
    is_qt_mat_fund_ai_missing: bool | None
    qt_mat_fund_af: int | None
    is_qt_mat_fund_af_missing: bool | None
    qt_mat_med: int | None
    is_qt_mat_med_missing: bool | None
    qt_mat_prof: int | None
    is_qt_mat_prof_missing: bool | None
    qt_mat_eja: int | None
    is_qt_mat_eja_missing: bool | None
    qt_mat_esp: int | None
    is_qt_mat_esp_missing: bool | None
    n_etapas_metodologia_incomparavel: int | None

    # rendimento (taxa de abandono; nunca "evasão")
    tx_aprov_fund_t: float | None
    tx_aprov_fund_ai: float | None
    tx_aprov_fund_af: float | None
    tx_aprov_med_t: float | None
    tx_reprov_fund_t: float | None
    tx_reprov_fund_ai: float | None
    tx_reprov_fund_af: float | None
    tx_reprov_med_t: float | None
    tx_aband_fund_t: float | None
    tx_aband_fund_ai: float | None
    tx_aband_fund_af: float | None
    tx_aband_med_t: float | None
    is_tx_aprov_fund_t_missing: bool | None
    is_tx_aprov_fund_ai_missing: bool | None
    is_tx_aprov_fund_af_missing: bool | None
    is_tx_aprov_med_t_missing: bool | None
    is_tx_reprov_fund_t_missing: bool | None
    is_tx_aband_fund_t_missing: bool | None

    # geolocalização (dimensão corrente, repete por ano)
    latitude: float | None
    longitude: float | None
    geocode_precision: str | None
    confidence_score: float | None
    needs_review: int | None


class History(BaseModel):
    """Série histórica da escola. Cabeçalho vem do ano mais recente da resposta."""

    co_entidade: str
    no_entidade: str | None
    co_municipio: str | None
    no_municipio: str | None
    items: list[HistoryItem] = Field(description="Ordenado por nu_ano_censo ASC.")


class SchoolsResponse(PagedEnvelope[list[School]]):
    pass


class HistoryResponse(Envelope[History]):
    pass
