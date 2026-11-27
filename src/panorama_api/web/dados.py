"""Seam de dados do front: **único** caminho por onde o `/app` lê dados.

Toda tela do front (busca, escola, mercado) chama ``dados.*`` e **nunca**
``panorama_api.services`` diretamente. As funções aqui são repasse fino:

1. validam a entrada com :mod:`panorama_api.core.validation` (a mesma validação
   das rotas `/v1`, sem regra nova);
2. delegam ao caso de uso de :mod:`panorama_api.services`;
3. devolvem o mesmo envelope Pydantic que `/v1` devolve.

Por isso uma tela não pode divergir do contrato sem quebrar teste, e a extração
do front para `panorama_web` (ver ``docs/desacoplamento-web.md``) consiste em
**trocar este módulo** por um cliente HTTP do `/v1` — sem tocar em tela, filtro
ou template.

Proibido neste pacote: ``panorama_api.repositories``, ``panorama_api.api``,
``google.cloud``/BigQuery. Quem consulta o BigQuery é o repositório, injetado em
``request.app.state.repo``; a fachada só o repassa.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from panorama_api.config import Settings
from panorama_api.core import validation
from panorama_api.core.errors import bad_request, invalid
from panorama_api.schemas.competitors import CompetitorsResponse
from panorama_api.schemas.indicators import IndicatorsResponse
from panorama_api.schemas.markets import MarketsResponse, ShareResponse
from panorama_api.schemas.schools import HistoryResponse, SchoolsResponse
from panorama_api.services import markets as service_markets
from panorama_api.services import schools as service_schools
from panorama_api.services import indice as service_indice
from panorama_api.services.indice import IndiceMunicipios
from panorama_api.services.schools import DESCRICAO_COMPETIDORES

#: Reexport (abaixo em `__all__`) do texto servido em `meta.definicoes.competidores`
#: pelo `/v1`: as telas (rótulos em `conteudo.py`) não importam `services` direto.

#: Máximos de paginação de cada tela do front. São os mesmos limites do `/v1`
#: (busca: `limit<=100`, share: `limit<=200`); o front usa 20 e 50 por página.
LIMITE_BUSCA_PADRAO = 20
LIMITE_BUSCA_MAXIMO = 100
LIMITE_SHARE_PADRAO = 50
LIMITE_SHARE_MAXIMO = 200


def fonte(request: Request) -> tuple[Any, Settings]:
    """Resolve ``(repositório, settings)`` injetados em ``create_app``.

    Ponto único de acoplamento com o processo da API. Na extração do front, este
    helper (e não as telas) vira a construção do cliente HTTP do `/v1`.
    """
    return request.app.state.repo, request.app.state.settings


def buscar_escolas(
    request: Request,
    *,
    q: str | None = None,
    co_entidade: str | None = None,
    co_municipio: str | None = None,
    tp_dependencia: str | None = None,
    apenas_ativas: bool = False,
    limit: int | None = None,
    offset: int | None = None,
) -> SchoolsResponse:
    """Busca de escolas (= ``GET /v1/schools``).

    Ao menos um critério (`q`, `co_entidade` ou `co_municipio`) é obrigatório:
    sem critério a consulta seria um scan da mart inteira (``400``, falha
    fechada). A tela de busca trata a busca vazia **antes** de chamar aqui.
    """
    termo = validation.search_term(q)
    entidade = (
        validation.co_entidade(co_entidade, loc="query")
        if co_entidade is not None
        else None
    )
    municipio = (
        validation.co_municipio(co_municipio, loc="query")
        if co_municipio is not None
        else None
    )
    dependencia = validation.tp_dependencia(tp_dependencia)
    limite = validation.limit(limit, default=LIMITE_BUSCA_PADRAO, maximum=LIMITE_BUSCA_MAXIMO)
    deslocamento = validation.offset(offset)

    if termo is None and entidade is None and municipio is None:
        raise bad_request(
            "informe ao menos um critério de busca: q, co_entidade ou co_municipio",
            loc=("query", "q"),
        )

    repository, settings = fonte(request)
    return service_schools.search_schools(
        repository,
        settings,
        q=termo,
        co_entidade=entidade,
        co_municipio=municipio,
        tp_dependencia=dependencia,
        apenas_ativas=apenas_ativas,
        limit=limite,
        offset=deslocamento,
    )


def historico_escola(
    request: Request,
    *,
    co_entidade: str,
    ano_inicio: int | None = None,
    ano_fim: int | None = None,
) -> HistoryResponse:
    """Série histórica da escola (= ``GET /v1/schools/{co_entidade}/history``)."""
    entidade = validation.co_entidade(co_entidade)
    inicio = validation.ano(ano_inicio)
    fim = validation.ano(ano_fim)
    if inicio is not None and fim is not None and inicio > fim:
        raise invalid("ano_inicio não pode ser maior que ano_fim", loc=("query", "ano_inicio"))

    repository, settings = fonte(request)
    return service_schools.school_history(
        repository, settings, co_entidade=entidade, ano_inicio=inicio, ano_fim=fim
    )


def indicadores_escola(
    request: Request,
    *,
    co_entidade: str,
    ano: int | None = None,
) -> IndicatorsResponse:
    """Indicadores da escola privada ativa (= ``GET /v1/schools/{co_entidade}/indicators``)."""
    entidade = validation.co_entidade(co_entidade)
    ano_ref = validation.ano(ano)

    repository, settings = fonte(request)
    return service_schools.school_indicators(
        repository, settings, co_entidade=entidade, ano=ano_ref
    )


def concorrentes_escola(
    request: Request,
    *,
    co_entidade: str,
) -> CompetitorsResponse:
    """Comparação municipal da escola (= ``GET /v1/schools/{co_entidade}/competitors``)."""
    entidade = validation.co_entidade(co_entidade)

    repository, settings = fonte(request)
    return service_schools.school_competitors(
        repository, settings, co_entidade=entidade
    )


def mercado(
    request: Request,
    *,
    co_municipio: str,
    ano: int,
    etapa: str | None = None,
) -> MarketsResponse:
    """Recorte municipal por etapa (= ``GET /v1/markets/{co_municipio}``)."""
    municipio = validation.co_municipio(co_municipio)
    ano_ref = validation.ano(ano, required=True)
    etapa_ref = validation.etapa(etapa)

    repository, settings = fonte(request)
    return service_markets.market(
        repository,
        settings,
        co_municipio=municipio,
        ano=ano_ref,
        etapa=etapa_ref,
    )


def share_mercado(
    request: Request,
    *,
    co_municipio: str,
    ano: int,
    etapa: str,
    entidade_tipo: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> ShareResponse:
    """Market share do município (= ``GET /v1/markets/{co_municipio}/share``)."""
    municipio = validation.co_municipio(co_municipio)
    ano_ref = validation.ano(ano, required=True)
    etapa_ref = validation.etapa(etapa, required=True)
    tipo = validation.entidade_tipo(entidade_tipo)
    limite = validation.limit(limit, default=LIMITE_SHARE_PADRAO, maximum=LIMITE_SHARE_MAXIMO)
    deslocamento = validation.offset(offset)

    repository, settings = fonte(request)
    return service_markets.market_share(
        repository,
        settings,
        co_municipio=municipio,
        ano=ano_ref,
        etapa=etapa_ref,
        entidade_tipo=tipo,
        limit=limite,
        offset=deslocamento,
    )


def indice_municipios(request: Request, *, ano: int) -> IndiceMunicipios:
    """Índice de municípios (= 1 linha por município de MG, etapa `bas`)."""
    ano_ref = validation.ano(ano, required=True)

    repository, settings = fonte(request)
    return service_indice.indice_municipios(repository, settings, ano=ano_ref)


__all__ = [
    "DESCRICAO_COMPETIDORES",
    "LIMITE_BUSCA_MAXIMO",
    "LIMITE_BUSCA_PADRAO",
    "LIMITE_SHARE_MAXIMO",
    "LIMITE_SHARE_PADRAO",
    "buscar_escolas",
    "concorrentes_escola",
    "fonte",
    "historico_escola",
    "indicadores_escola",
    "indice_municipios",
    "mercado",
    "share_mercado",
]
