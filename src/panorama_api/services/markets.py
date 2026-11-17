"""Casos de uso de mercado: recorte municipal e market share."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from panorama_api.config import Settings
from panorama_api.contract import (
    UNIVERSO_ESCOLAS_ATIVAS_MG,
    EntidadeTipo,
    Etapa,
)
from panorama_api.core.errors import ano_fora_do_contrato, not_found
from panorama_api.repositories.serving import ServingRepository
from panorama_api.schemas.common import build_meta, page_from
from panorama_api.schemas.markets import (
    Concentracao,
    Market,
    MarketItem,
    MarketsResponse,
    MercadoDenominadores,
    Share,
    ShareItem,
    ShareResponse,
)
from panorama_api.services.mappers import flags_abaixo_porte

TABELA_MERCADO = "mart_mercado"
TABELA_SHARE = "mart_market_share"

COBERTURA_KEYS = (
    "n_escolas_ativas",
    "n_escolas_com_linha_matricula",
    "n_escolas_mat_linha_missing",
    "n_escolas_mat_valor_missing",
    "n_escolas_mat_missing",
)


def _cobertura(row: Mapping[str, Any]) -> dict[str, int | float | None]:
    return {key: row.get(key) for key in COBERTURA_KEYS}


def _concentracao(row: Mapping[str, Any]) -> Concentracao:
    return Concentracao(
        recorte=row.get("recorte"),
        nivel=row.get("nivel"),
        n_competidores=row.get("n_competidores"),
        hhi=row.get("hhi"),
        share_lider_pct=row.get("share_lider_pct"),
        c4_pct=row.get("c4_pct"),
        soma_share_pct=row.get("soma_share_pct"),
    )


def _market_item(
    row: Mapping[str, Any], concentracao: list[Concentracao]
) -> MarketItem:
    return MarketItem(
        co_municipio=row["co_municipio"],
        nu_ano_censo=row["nu_ano_censo"],
        etapa=row["etapa"],
        n_escolas_ativas=row.get("n_escolas_ativas"),
        n_escolas_publicas=row.get("n_escolas_publicas"),
        n_escolas_privadas=row.get("n_escolas_privadas"),
        n_escolas_mat_linha_missing=row.get("n_escolas_mat_linha_missing"),
        n_escolas_mat_valor_missing=row.get("n_escolas_mat_valor_missing"),
        n_escolas_mat_missing=row.get("n_escolas_mat_missing"),
        n_escolas_com_linha_matricula=row.get("n_escolas_com_linha_matricula"),
        qt_mat_total=row.get("qt_mat_total"),
        qt_mat_publica=row.get("qt_mat_publica"),
        qt_mat_privada=row.get("qt_mat_privada"),
        pct_privada_no_total_pct=row.get("pct_privada_no_total_pct"),
        n_escolas_entraram=row.get("n_escolas_entraram"),
        n_escolas_ativas_com_baseline=row.get("n_escolas_ativas_com_baseline"),
        n_escolas_sairam=row.get("n_escolas_sairam"),
        cobertura=_cobertura(row),
        concentracao=concentracao,
    )


def market(
    repository: ServingRepository,
    settings: Settings,
    *,
    co_municipio: str,
    ano: int,
    etapa: Etapa | None,
) -> MarketsResponse:
    municipio = repository.get_municipio(co_municipio)
    if municipio is None:
        raise not_found(f"município {co_municipio} não encontrado no recorte MG")

    rows = repository.get_market(co_municipio=co_municipio, ano=ano, etapa=etapa)
    if not rows:
        raise ano_fora_do_contrato(
            f"sem linha em mart_mercado para município {co_municipio}, "
            f"ano {ano}" + (f", etapa {etapa}" if etapa else "")
        )

    por_etapa: dict[Any, list[Concentracao]] = defaultdict(list)
    for row in repository.get_concentracao(
        co_municipio=co_municipio, ano=ano, etapa=etapa
    ):
        por_etapa[row.get("etapa")].append(_concentracao(row))

    items = [_market_item(row, por_etapa.get(row["etapa"], [])) for row in rows]
    meta = build_meta(
        contract_version=settings.contract_version,
        ano_referencia=ano,
        etapa=etapa,
        universo=UNIVERSO_ESCOLAS_ATIVAS_MG,
        tabela=TABELA_MERCADO,
        # `cobertura` é por etapa: só é agregável quando a resposta tem 1 linha.
        cobertura=items[0].cobertura if len(items) == 1 else None,
    )
    data = Market(
        co_municipio=co_municipio,
        no_municipio=municipio.get("no_municipio"),
        items=items,
    )
    return MarketsResponse(data=data, meta=meta)


def _share_item(row: Mapping[str, Any], entidade_tipo: EntidadeTipo) -> ShareItem:
    nome = row.get("no_grupo") if entidade_tipo == "mantenedora" else row.get("no_entidade")
    return ShareItem(
        id_entidade=row["id_entidade"],
        no_entidade=nome,
        n_unidades=row.get("n_unidades"),
        mat_entidade=row.get("mat_entidade"),
        share_privado_pct=row.get("share_privado_pct"),
        share_total_pct=row.get("share_total_pct"),
        is_abaixo_porte=row.get("is_abaixo_porte"),
    )


def market_share(
    repository: ServingRepository,
    settings: Settings,
    *,
    co_municipio: str,
    ano: int,
    etapa: Etapa,
    entidade_tipo: EntidadeTipo,
    limit: int,
    offset: int,
) -> ShareResponse:
    municipio = repository.get_municipio(co_municipio)
    if municipio is None:
        raise not_found(f"município {co_municipio} não encontrado no recorte MG")

    # Mercado existente sem linhas de share ⇒ 200 com items: []; inexistente ⇒ 404.
    mercado = repository.get_market(co_municipio=co_municipio, ano=ano, etapa=etapa)
    if not mercado:
        raise ano_fora_do_contrato(
            f"sem mercado para município {co_municipio}, ano {ano}, etapa {etapa}"
        )

    fetched = repository.get_market_share(
        co_municipio=co_municipio,
        ano=ano,
        etapa=etapa,
        entidade_tipo=entidade_tipo,
        limit=limit,
        offset=offset,
    )
    rows, page = page_from(fetched, limit=limit, offset=offset)

    # Denominadores são iguais em todas as linhas; vêm do share e, sem linhas de
    # share, do próprio mart_mercado (nunca zero inventado).
    base: Mapping[str, Any] = rows[0] if rows else mercado[0]
    denominadores = MercadoDenominadores(
        n_escolas_privadas=base.get("n_escolas_privadas"),
        n_escolas_ativas=base.get("n_escolas_ativas"),
        qt_mat_privada=base.get("qt_mat_privada"),
        qt_mat_total=base.get("qt_mat_total"),
    )
    meta = build_meta(
        contract_version=settings.contract_version,
        ano_referencia=ano,
        etapa=etapa,
        universo=UNIVERSO_ESCOLAS_ATIVAS_MG,
        tabela=TABELA_SHARE,
        cobertura={
            "n_escolas_privadas": denominadores.n_escolas_privadas,
            "n_escolas_ativas": denominadores.n_escolas_ativas,
        },
        avisos=flags_abaixo_porte(rows),
    )
    data = Share(
        co_municipio=co_municipio,
        nu_ano_censo=ano,
        etapa=etapa,
        entidade_tipo=entidade_tipo,
        mercado=denominadores,
        items=[_share_item(row, entidade_tipo) for row in rows],
    )
    return ShareResponse(data=data, meta=meta, page=page)
