"""Índice de municípios (V4-4b): 1 linha por município de MG, etapa `bas` fixa.

Uma consulta por ano; os KPIs da página são somas feitas aqui em Python
sobre as linhas devolvidas pelo repositório.
"""

from __future__ import annotations

from dataclasses import dataclass

from panorama_api.config import Settings
from panorama_api.core.errors import ano_fora_do_contrato
from panorama_api.repositories.serving import ServingRepository


@dataclass(frozen=True)
class IndiceLinha:
    """Linha do índice: grão `co_municipio × ano`, etapa `bas`."""

    co_municipio: str
    qt_mat_privada: float | None
    qt_mat_privada_anterior: float | None
    n_escolas_privadas: int | None
    variacao_pct: float | None
    share_lider_pct: float | None


@dataclass(frozen=True)
class IndiceKpis:
    """Totais do recorte: somas ignorando `None` (`None` nunca vira `0`)."""

    n_municipios: int
    qt_mat_privada_total: float | None
    qt_mat_privada_anterior_total: float | None
    n_escolas_privadas_total: int | None
    variacao_pct: float | None


@dataclass(frozen=True)
class IndiceMunicipios:
    ano: int
    linhas: list[IndiceLinha]
    kpis: IndiceKpis


def _soma(valores: list[float | int | None]) -> float | int | None:
    presentes = [v for v in valores if v is not None]
    if not presentes:
        return None
    total: float | int = 0
    for valor in presentes:
        total += valor  # type: ignore[operator]
    return total


def _kpis(linhas: list[IndiceLinha]) -> IndiceKpis:
    qt_total = _soma([l.qt_mat_privada for l in linhas])
    qt_ant_total = _soma([l.qt_mat_privada_anterior for l in linhas])
    escolas_total = _soma([l.n_escolas_privadas for l in linhas])

    # Variação do recorte só sobre linhas com ambos os anos (com base).
    pares = [
        (l.qt_mat_privada, l.qt_mat_privada_anterior)
        for l in linhas
        if l.qt_mat_privada is not None and l.qt_mat_privada_anterior is not None
    ]
    variacao: float | None = None
    if pares:
        soma_atual = sum(a for a, _ in pares)  # type: ignore[misc]
        soma_base = sum(b for _, b in pares)  # type: ignore[misc]
        if soma_base:
            variacao = (soma_atual - soma_base) / soma_base * 100

    return IndiceKpis(
        n_municipios=len(linhas),
        qt_mat_privada_total=qt_total,  # type: ignore[arg-type]
        qt_mat_privada_anterior_total=qt_ant_total,  # type: ignore[arg-type]
        n_escolas_privadas_total=escolas_total,  # type: ignore[arg-type]
        variacao_pct=variacao,
    )


def indice_municipios(
    repository: ServingRepository,
    settings: Settings,
    *,
    ano: int,
) -> IndiceMunicipios:
    """Devolve o índice de municípios do ano, com KPIs somados em Python."""
    if ano not in settings.anos_disponiveis:
        raise ano_fora_do_contrato(
            f"ano {ano} fora de APP_ANOS_DISPONIVEIS "
            f"({', '.join(str(item) for item in settings.anos_disponiveis)})"
        )

    rows = repository.get_indice_municipios(ano=ano)

    linhas = [
        IndiceLinha(
            co_municipio=row["co_municipio"],
            qt_mat_privada=row.get("qt_mat_privada"),
            qt_mat_privada_anterior=row.get("qt_mat_privada_anterior"),
            n_escolas_privadas=row.get("n_escolas_privadas"),
            variacao_pct=row.get("variacao_pct"),
            share_lider_pct=row.get("share_lider_pct"),
        )
        for row in rows
    ]
    return IndiceMunicipios(ano=ano, linhas=linhas, kpis=_kpis(linhas))
