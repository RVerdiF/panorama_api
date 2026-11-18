"""Schemas de `/v1/schools/{co_entidade}/competitors` — comparação MUNICIPAL.

Fonte: `mart_competidores` (grão `co_entidade × nu_ano_censo`). Concorrentes são
escolas privadas ativas no mesmo município e ano censitário; a mart não expõe
lista nominal de concorrentes, apenas contagens e a posição da própria escola.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from panorama_api.schemas.common import Envelope


class Competicao(BaseModel):
    """Linha de `mart_competidores` (mesmo grão da escola-ano, nível BAS)."""

    no_entidade: str | None
    co_municipio: str | None
    qt_mat_bas: int | None = Field(
        description="Matrícula BAS observada da própria escola; `null` não é zero."
    )
    rank_mat_bas_municipio: int | None = Field(
        description="Posição da escola por matrícula BAS entre as privadas ativas do município/ano."
    )
    n_concorrentes_privados_municipio: int | None = Field(
        description=(
            "Privadas ativas no mesmo município e ano, excluindo a própria escola. "
            "Inclui privadas ativas sem matrícula observada."
        )
    )
    n_concorrentes_com_matricula_bas: int | None = Field(
        description=(
            "Privadas ativas com matrícula BAS observada no município/ano, excluindo a "
            "própria. Ausência de matrícula não conta como zero."
        )
    )
    n_concorrentes_creche_xself: int | None = Field(
        description="Privadas com matrícula observada em creche no município/ano, excluindo a própria quando a oferece."
    )
    n_concorrentes_pre_xself: int | None = Field(
        description="Privadas com matrícula observada em pré-escola no município/ano, excluindo a própria quando a oferece."
    )
    n_concorrentes_fund_ai_xself: int | None = Field(
        description="Privadas com matrícula observada nos anos iniciais do fundamental no município/ano, excluindo a própria quando a oferece."
    )
    n_concorrentes_fund_af_xself: int | None = Field(
        description="Privadas com matrícula observada nos anos finais do fundamental no município/ano, excluindo a própria quando a oferece."
    )
    n_concorrentes_med_xself: int | None = Field(
        description="Privadas com matrícula observada no ensino médio no município/ano, excluindo a própria quando a oferece."
    )
    lider_no_entidade: str | None = Field(
        description="Nome da escola líder do município/ano (maior matrícula BAS observada)."
    )
    lider_qt_mat_bas: int | None = Field(
        description="Matrícula BAS do líder do município/ano."
    )
    gap_mat_bas_para_lider: int | None = Field(
        description=(
            "Saldo de matrícula BAS para o líder: `lider_qt_mat_bas - qt_mat_bas`. "
            "`0` quando a própria escola é a líder; `null` quando não há líder observado."
        )
    )


class CompetitorItem(Competicao):
    """Linha da mart identificada pelo ano censitário."""

    nu_ano_censo: int


class Competitors(BaseModel):
    """Comparação municipal da escola. Cabeçalho vem do ano mais recente da resposta."""

    co_entidade: str
    no_entidade: str | None
    co_municipio: str | None
    items: list[CompetitorItem] = Field(
        description="Uma linha por ano censitário, ordenada por `nu_ano_censo` ASC."
    )


class CompetitorsResponse(Envelope[Competitors]):
    pass
