"""Regras da tela de mercado `/app/mercados/{co_municipio}` (card `t_c06ff921`).

Tudo aqui é **puro**: recebe as respostas do contrato (as mesmas do `/v1`) e
devolve o contexto do template. Nenhum acesso a dado — quem consulta é
`web/dados.py`, chamado pela rota em `web/routes.py`.

Decisões que moram neste módulo:

1. **Sem concentração (HHI/C4).** Decisão D4 do plano: fora do MVP. A tela
   mostra tamanho e composição por etapa e o share de matrícula; os campos
   `concentracao` do contrato não são exibidos nem consultados à parte.
2. **Concorrência é municipal.** A contagem vem de `n_escolas_privadas`/
   `n_escolas_ativas` do mesmo município e ano — vocabulário de raio/proximidade
   não existe aqui (`docs/escopo-adiado-v1.md`). Essas duas contagens **não**
   variam por etapa na mart (a escola ativa entra em todas), então a tela as
   mostra uma única vez, como total do município; repeti-las em cada linha da
   composição por etapa daria a impressão de nove totais distintos.
3. **Ausência nunca vira zero.** `share_privado_pct`/`share_total_pct` nulos e
   os campos de entrada/saída do primeiro ano da série saem como "sem dado"
   com o motivo; escola ausente do share **não é** 0%.
"""

from __future__ import annotations

from typing import Any, Sequence

from panorama_api.schemas.markets import MarketItem, MarketsResponse, ShareResponse
from panorama_api.web.conteudo import (
    DEFINICAO_CONCORRENCIA,
    MOTIVO_ALEM_DO_FIM,
    MOTIVO_ENTRADA_SAIDA,
    MOTIVO_SEM_PRIVADAS,
    TEXTO_ABAIXO_PORTE,
    UNIVERSOS,
    rotulo_etapa,
    traduzir_aviso,
)

#: Colunas de cobertura de matrícula por etapa (`MarketItem.cobertura`).
COBERTURA: tuple[tuple[str, str], ...] = (
    ("Com linha de matrícula", "n_escolas_com_linha_matricula"),
    ("Sem linha de matrícula", "n_escolas_mat_linha_missing"),
    ("Linha com matrícula faltante", "n_escolas_mat_valor_missing"),
    ("Sem matrícula em qualquer etapa", "n_escolas_mat_missing"),
)

#: Campos de entrada/saída: `null` no primeiro ano da série (sem baseline).
MOVIMENTO: tuple[tuple[str, str], ...] = (
    ("Escolas que entraram", "n_escolas_entraram"),
    ("Escolas comparáveis (com baseline)", "n_escolas_ativas_com_baseline"),
    ("Escolas que saíram", "n_escolas_sairam"),
)


def _linhas_por_etapa(items: Sequence[MarketItem]) -> list[dict[str, Any]]:
    """Uma linha por etapa servida por `mart_mercado` (ordem do contrato).

    `n_escolas_ativas`/`n_escolas_privadas` **não** entram aqui: a mart repete o
    total do município em todas as etapas e repeti-lo linha a linha sugere nove
    números diferentes. O total aparece uma única vez no resumo da página
    (`denominadores`), que vem de `share.data.mercado`.
    """
    return [
        {
            "etapa": item.etapa,
            "rotulo": rotulo_etapa(item.etapa),
            "n_escolas_publicas": item.n_escolas_publicas,
            "qt_mat_total": item.qt_mat_total,
            "qt_mat_publica": item.qt_mat_publica,
            "qt_mat_privada": item.qt_mat_privada,
            "pct_privada_no_total_pct": item.pct_privada_no_total_pct,
            "movimento": [
                {"rotulo": rotulo, "valor": getattr(item, campo)}
                for rotulo, campo in MOVIMENTO
            ],
            "cobertura": [
                {"rotulo": rotulo, "valor": item.cobertura.get(campo)}
                for rotulo, campo in COBERTURA
            ],
        }
        for item in items
    ]


def _linha_da_etapa(linhas: Sequence[dict[str, Any]], etapa: str) -> dict[str, Any] | None:
    """Linha da etapa selecionada (o share é sempre de uma etapa)."""
    return next((linha for linha in linhas if linha["etapa"] == etapa), None)


def _linhas_share(share: ShareResponse) -> list[dict[str, Any]]:
    """Ranking do share na página, com a posição explícita (o contrato não tem `total`)."""
    offset = share.page.offset
    return [
        {
            "posicao": offset + indice + 1,
            "id_entidade": item.id_entidade,
            "no_entidade": item.no_entidade,
            "mat_entidade": item.mat_entidade,
            "share_privado_pct": item.share_privado_pct,
            "share_total_pct": item.share_total_pct,
            "is_abaixo_porte": item.is_abaixo_porte,
        }
        for indice, item in enumerate(share.data.items)
    ]


def contexto_mercado(
    *,
    mercado: MarketsResponse,
    share: ShareResponse,
    anos_disponiveis: Sequence[int],
    caminho: str,
    filtros_pagina: dict[str, str],
    montar_paginacao: Any,
    url_lista: Any,
) -> dict[str, Any]:
    """Contexto completo do template a partir das respostas (já obtidas) do `/v1`.

    `mercado` é consultado **sem** recorte de etapa: a composição por etapa é o
    conteúdo da tela. O share é sempre de uma etapa (o `/v1` exige `etapa`).

    `share.data.items` vazio é estado legítimo e tem **dois** significados que a
    tela não pode confundir (card `t_3ea9454f`, achado C2):

    * `offset == 0` → o município não tem escola privada com matrícula nesta
      etapa: "mercado sem escolas privadas com matrícula";
    * `offset > 0` → o `offset` passou do fim da lista (o mercado tem escolas;
      só não nesta página): "não há mais escolas nesta página" + volta à 1ª.

    O contrato não tem `total`, então `items: []` com `offset > 0` **nunca**
    prova ausência de mercado — só prova que a página está além do fim.
    """
    itens = list(mercado.data.items)
    etapas = _linhas_por_etapa(itens)
    selecionada = share.data.etapa
    denominadores = share.data.mercado
    vazia = not share.data.items
    alem_do_fim = vazia and share.page.offset > 0

    return {
        "mercado": mercado.data,
        "share": share.data,
        "anos_disponiveis": list(anos_disponiveis),
        "ano_selecionado": mercado.meta.ano_referencia,
        "etapa_selecionada": selecionada,
        "etapa_rotulo": rotulo_etapa(selecionada),
        "etapas": etapas,
        # O seletor oferece só as etapas publicadas para este município/ano
        # (linhas de `mart_mercado`), não as 9 do contrato: etapa sem linha
        # seria um 404 anunciado na própria tela.
        "etapas_disponiveis": {linha["etapa"]: linha["rotulo"] for linha in etapas},
        "item_etapa": _linha_da_etapa(etapas, selecionada),
        "linhas_share": _linhas_share(share),
        # Página além do fim e mercado sem privadas são estados distintos: a
        # mensagem de ausência só vale na 1ª página (offset == 0).
        "sem_privadas": vazia and not alem_do_fim,
        "alem_do_fim": alem_do_fim,
        "motivo_sem_privadas": MOTIVO_SEM_PRIVADAS,
        "motivo_alem_do_fim": MOTIVO_ALEM_DO_FIM,
        # Mesmo ano e etapa, sem `offset`: a URL canônica da 1ª página. Só é
        # calculada quando faz falta (página além do fim) — o link não existe em
        # nenhuma outra situação da tela.
        "url_primeira_pagina": (
            url_lista(caminho, filtros_pagina, offset=0) if alem_do_fim else None
        ),
        "motivo_entrada_saida": MOTIVO_ENTRADA_SAIDA,
        "texto_abaixo_porte": TEXTO_ABAIXO_PORTE,
        "denominadores": {
            "n_escolas_privadas": denominadores.n_escolas_privadas,
            "n_escolas_ativas": denominadores.n_escolas_ativas,
            "qt_mat_privada": denominadores.qt_mat_privada,
            "qt_mat_total": denominadores.qt_mat_total,
        },
        "definicao_concorrencia": DEFINICAO_CONCORRENCIA,
        "meta": {
            "ano_referencia": mercado.meta.ano_referencia,
            "etapa": rotulo_etapa(mercado.meta.etapa),
            "universo": mercado.meta.universo,
            "universo_texto": UNIVERSOS.get(mercado.meta.universo),
            "orgao": mercado.meta.fonte.orgao,
            "base": mercado.meta.fonte.base,
            "tabela": mercado.meta.fonte.tabela,
            "avisos": [
                {"codigo": codigo, "texto": traduzir_aviso(codigo)}
                for codigo in mercado.meta.avisos
            ],
        },
        "meta_share": {
            "ano_referencia": share.meta.ano_referencia,
            "etapa": rotulo_etapa(share.meta.etapa),
            "universo": share.meta.universo,
            "universo_texto": UNIVERSOS.get(share.meta.universo),
            "orgao": share.meta.fonte.orgao,
            "base": share.meta.fonte.base,
            "tabela": share.meta.fonte.tabela,
            "avisos": [
                {"codigo": codigo, "texto": traduzir_aviso(codigo)}
                for codigo in share.meta.avisos
            ],
        },
        "universo_texto": UNIVERSOS.get(mercado.meta.universo),
        "paginacao": montar_paginacao(
            share.page, caminho=caminho, filtros=filtros_pagina
        ),
    }


__all__ = ["COBERTURA", "MOVIMENTO", "contexto_mercado"]
