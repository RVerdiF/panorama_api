"""Recorte da busca web `/app/` (card `t_6a9f6b6f`, decisões V6-P4).

Lista as escolas de MG de `dim_escola` com as métricas do ano vindas de
`mart_escola_indicadores` (LEFT JOIN): matrícula, share municipal e variação
anual. **Não** é o `/v1/schools` — aquele continua exigindo critério (400) e
servindo só `dim_escola`; este caso de uso existe só para a tela.

Ausência nunca vira zero: escola fora do universo de indicadores (pública,
paralisada, sem matrícula BAS) volta com as três métricas `None`, e a
matrícula marcada `is_qt_mat_bas_missing` também sai `None`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from panorama_api.config import Settings
from panorama_api.contract import UNIVERSO_ESCOLAS_MG
from panorama_api.core.errors import ano_fora_do_contrato
from panorama_api.repositories.queries import (
    DIRECOES_RECORTE,
    ETAPAS_RECORTE,
    ORDENACAO_RECORTE,
    SITUACOES_RECORTE,
)
from panorama_api.repositories.serving import ServingRepository
from panorama_api.schemas.common import Meta, Page, build_meta, page_from

#: Vocabulário aceito pela tela (a allowlist SQL é a fonte; aqui só as chaves).
ORDENS: frozenset[str] = frozenset(ORDENACAO_RECORTE)
DIRECOES: frozenset[str] = frozenset(DIRECOES_RECORTE)
ETAPAS: frozenset[str] = frozenset(ETAPAS_RECORTE)
SITUACOES: frozenset[str] = SITUACOES_RECORTE
#: Abertura da tela: matrícula desc (`NULLS LAST`), como o protótipo.
ORDEM_PADRAO = "matricula"
DIRECAO_PADRAO = "desc"
TABELA_RECORTE = "dim_escola + mart_escola_indicadores"


@dataclass(frozen=True, slots=True)
class LinhaRecorte:
    """Uma escola do recorte com as métricas do ano (`None` = sem dado)."""

    co_entidade: str
    no_entidade: str | None
    co_municipio: str | None
    no_municipio: str | None
    tp_dependencia: str | None
    tp_situacao_funcionamento: str | None
    qt_mat_bas: int | None
    share_privado_pct: float | None
    crescimento_yoy_pct: float | None


@dataclass(frozen=True, slots=True)
class RecorteEscolas:
    ano: int
    linhas: list[LinhaRecorte]
    page: Page
    meta: Meta


def _linha(row: Mapping[str, Any]) -> LinhaRecorte:
    matricula = None if row.get("is_qt_mat_bas_missing") else row.get("qt_mat_bas")
    return LinhaRecorte(
        co_entidade=row["co_entidade"],
        no_entidade=row.get("no_entidade"),
        co_municipio=row.get("co_municipio"),
        no_municipio=row.get("no_municipio"),
        tp_dependencia=row.get("tp_dependencia"),
        tp_situacao_funcionamento=row.get("tp_situacao_funcionamento"),
        qt_mat_bas=matricula,
        share_privado_pct=row.get("share_privado_pct"),
        crescimento_yoy_pct=row.get("crescimento_yoy_pct"),
    )


def escolas_recorte(
    repository: ServingRepository,
    settings: Settings,
    *,
    ano: int,
    q: str | None,
    co_municipio: str | None,
    etapa: str | None,
    situacao: str | None,
    ordem: str,
    direcao: str,
    limit: int,
    offset: int,
) -> RecorteEscolas:
    """Uma consulta: a página do recorte, com `has_more` por `LIMIT L+1`."""
    if ano not in settings.anos_disponiveis:
        raise ano_fora_do_contrato(
            f"ano {ano} fora de APP_ANOS_DISPONIVEIS "
            f"({', '.join(str(item) for item in settings.anos_disponiveis)})"
        )

    fetched = repository.list_escolas_recorte(
        ano=ano,
        q=q,
        co_municipio=co_municipio,
        etapa=etapa,
        situacao=situacao,
        ordem=ordem,
        direcao=direcao,
        limit=limit,
        offset=offset,
    )
    rows, page = page_from(fetched, limit=limit, offset=offset)
    meta = build_meta(
        contract_version=settings.contract_version,
        ano_referencia=ano,
        etapa="bas",
        universo=UNIVERSO_ESCOLAS_MG,
        tabela=TABELA_RECORTE,
    )
    return RecorteEscolas(ano=ano, linhas=[_linha(row) for row in rows], page=page, meta=meta)


__all__ = [
    "DIRECAO_PADRAO",
    "DIRECOES",
    "ETAPAS",
    "LinhaRecorte",
    "ORDEM_PADRAO",
    "ORDENS",
    "RecorteEscolas",
    "SITUACOES",
    "TABELA_RECORTE",
    "escolas_recorte",
]
