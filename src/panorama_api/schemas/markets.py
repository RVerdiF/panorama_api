"""Schemas de `/v1/markets/{co_municipio}` e `/v1/markets/{co_municipio}/share`."""

from __future__ import annotations

from pydantic import BaseModel, Field

from panorama_api.contract import Etapa, EntidadeTipo
from panorama_api.schemas.common import Envelope, PagedEnvelope


class Concentracao(BaseModel):
    """Linha de `mart_concentracao` para a etapa."""

    recorte: str | None
    nivel: str | None
    n_competidores: int | None
    hhi: float | None
    share_lider_pct: float | None
    c4_pct: float | None
    soma_share_pct: float | None


class MarketItem(BaseModel):
    """Linha de `mart_mercado` (grão `co_municipio × nu_ano_censo × etapa`)."""

    co_municipio: str
    nu_ano_censo: int
    etapa: Etapa

    n_escolas_ativas: int | None
    n_escolas_publicas: int | None
    n_escolas_privadas: int | None
    n_escolas_mat_linha_missing: int | None
    n_escolas_mat_valor_missing: int | None
    n_escolas_mat_missing: int | None
    n_escolas_com_linha_matricula: int | None

    qt_mat_total: float | None
    qt_mat_publica: float | None
    qt_mat_privada: float | None
    pct_privada_no_total_pct: float | None

    # NULL no 1º ano da série (sem baseline) — repassado como null.
    n_escolas_entraram: float | None
    n_escolas_ativas_com_baseline: float | None
    n_escolas_sairam: int | None

    cobertura: dict[str, int | float | None] = Field(
        description="Cobertura da linha: n_escolas_ativas, n_escolas_com_linha_matricula, "
        "n_escolas_mat_linha_missing, n_escolas_mat_valor_missing, n_escolas_mat_missing."
    )
    concentracao: list[Concentracao] = Field(default_factory=list)


class Market(BaseModel):
    co_municipio: str
    no_municipio: str | None
    items: list[MarketItem] = Field(description="Ordenado por etapa ASC (≤ 9 linhas).")


class MercadoDenominadores(BaseModel):
    """Denominadores do mercado (iguais em todas as linhas de share)."""

    n_escolas_privadas: int | None
    n_escolas_ativas: int | None
    qt_mat_privada: float | None
    qt_mat_total: float | None


class ShareItem(BaseModel):
    id_entidade: str
    no_entidade: str | None = Field(
        description=(
            "Nome da entidade. Para `entidade_tipo=mantenedora` vem de "
            "`dim_mantenedora.no_grupo`; `null` quando não há grupo identificado."
        )
    )
    n_unidades: int | None = Field(description="NULL para `escola`.")
    mat_entidade: float | None
    share_privado_pct: float | None
    share_total_pct: float | None = Field(
        description=(
            "Escolas ausentes desta tabela **não** são 0%: a ausência significa "
            "matrícula não observada, não share nulo."
        )
    )
    is_abaixo_porte: bool | None


class Share(BaseModel):
    co_municipio: str
    nu_ano_censo: int
    etapa: Etapa
    entidade_tipo: EntidadeTipo
    mercado: MercadoDenominadores
    items: list[ShareItem]


class MarketsResponse(Envelope[Market]):
    pass


class ShareResponse(PagedEnvelope[Share]):
    pass
