"""Envelope, `meta`, paginação e problem+json (contrato comum)."""

from __future__ import annotations

from typing import Any, Generic, Literal, Mapping, Sequence, TypeVar

from pydantic import BaseModel, Field

from panorama_api.contract import CONTRACT, FONTE_BASE, FONTE_ORGAO, Etapa

DataT = TypeVar("DataT")


class Fonte(BaseModel):
    orgao: str = Field(examples=[FONTE_ORGAO])
    base: str = Field(examples=[FONTE_BASE])
    tabela: str = Field(description="View do contrato de onde os dados vieram")


class Meta(BaseModel):
    """Metadados obrigatórios de todo payload de dados."""

    contract: str = Field(default=CONTRACT, examples=[CONTRACT])
    contract_version: str = Field(examples=["mvp-1"])
    ano_referencia: int | None = Field(
        description="Ano efetivamente servido; `null` quando a resposta não tem recorte de ano."
    )
    etapa: Etapa | None = Field(
        description=(
            "Etapa do recorte. `bas` é o total oficial (nunca somar subetapas); "
            "`null` quando a resposta cobre as 9 etapas."
        )
    )
    universo: str = Field(
        description="Recorte populacional: escolas_mg, privadas_ativas_mg, escolas_ativas_mg."
    )
    fonte: Fonte
    cobertura: dict[str, int | float | None] | None = Field(
        default=None,
        description="Contagens de cobertura do agregado; obrigatório onde houver agregado.",
    )
    avisos: list[str] = Field(
        default_factory=list,
        description="Códigos de aviso aplicáveis (ex.: IS_ABAIXO_PORTE, METODOLOGIA_INCOMPARAVEL_2025).",
    )
    definicoes: dict[str, str] | None = Field(
        default=None, description="Definições semânticas obrigatórias do payload."
    )


class Page(BaseModel):
    """Paginação por cursor de offset. `total` não existe: COUNT no BQ é scan extra."""

    limit: int
    offset: int
    returned: int
    has_more: bool = Field(description="true quando existe ao menos uma linha além de `returned`.")


class Envelope(BaseModel, Generic[DataT]):
    """Payload de dados. `page` só existe em endpoints de lista."""

    data: DataT
    meta: Meta


class PagedEnvelope(Envelope[DataT], Generic[DataT]):
    """Envelope de lista: `{data, meta, page}` — sem `total` (COUNT é scan extra)."""

    page: Page


class ProblemErrorItem(BaseModel):
    loc: list[str]
    msg: str


class Problem(BaseModel):
    """RFC 9457 (`application/problem+json`)."""

    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: Literal[
        "PARAMETRO_INVALIDO",
        "NAO_ENCONTRADO",
        "ANO_FORA_DO_CONTRATO",
        "FONTE_INDISPONIVEL",
        "ERRO_INTERNO",
    ]
    errors: list[ProblemErrorItem] = Field(default_factory=list)


def build_meta(
    *,
    contract_version: str,
    ano_referencia: int | None,
    etapa: Etapa | None,
    universo: str,
    tabela: str,
    cobertura: dict[str, int | float | None] | None = None,
    avisos: Sequence[str] = (),
    definicoes: dict[str, str] | None = None,
) -> Meta:
    return Meta(
        contract=CONTRACT,
        contract_version=contract_version,
        ano_referencia=ano_referencia,
        etapa=etapa,
        universo=universo,
        fonte=Fonte(orgao=FONTE_ORGAO, base=FONTE_BASE, tabela=tabela),
        cobertura=cobertura,
        avisos=list(avisos),
        definicoes=definicoes,
    )


def page_from(fetched: Sequence[object], *, limit: int, offset: int) -> tuple[list, Page]:
    """Aplica a paginação de `LIMIT L+1`: a linha extra vira `has_more`."""
    has_more = len(fetched) > limit
    rows = list(fetched[:limit])
    return rows, Page(limit=limit, offset=offset, returned=len(rows), has_more=has_more)


def avisos_metodologia(rows: Sequence[Mapping[str, Any]], campo: str = "n_etapas_metodologia_incomparavel") -> list[str]:
    """`METODOLOGIA_INCOMPARAVEL_<ano>` para cada ano com etapas não comparáveis."""
    avisos: list[str] = []
    for row in rows:
        valor = row.get(campo)
        ano = row.get("nu_ano_censo")
        if valor and ano is not None:
            aviso = f"METODOLOGIA_INCOMPARAVEL_{ano}"
            if aviso not in avisos:
                avisos.append(aviso)
    return avisos
