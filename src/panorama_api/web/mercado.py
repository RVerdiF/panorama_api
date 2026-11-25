"""Regras das telas de mercado: Visão geral e Escolas do mercado (card NAV-3).

Tudo aqui é **puro**: recebe as respostas do contrato (as mesmas do `/v1`) e
devolve o contexto do template. Nenhum acesso a dado — quem consulta é
`web/dados.py`, chamado pela rota em `web/routes.py`.

Duas rotas, uma consulta cara cada (spec §5.3):

* `/app/mercados/{co_municipio}` — **Visão geral**: tamanho, composição,
  cobertura e entrada/saída. Consulta só `dados.mercado` (3 consultas,
  ~63,7 MB).
* `/app/mercados/{co_municipio}/escolas` — **Escolas do mercado**: o ranking de
  share paginado. Consulta só `dados.share_mercado` (3 consultas, ~203,5 MB).

O ranking saiu da abertura porque era a consulta mais cara do produto
(`mart_market_share` ≈ 181 MB): antes, toda abertura, troca de etapa ou página
do ranking custava 6 consultas / ~267 MB. Agora a abertura custa 3 / 63,7 MB e
cada página do ranking 3 / 203,5 MB, sem recomputar a composição.

Decisões que moram neste módulo:

1. **Sem concentração (HHI/C4) na tela.** Decisão D4 do plano: fora do MVP. Os
   campos `concentracao` do contrato são consultados pelo `/v1` e não exibidos;
   a Visão geral não os usa.
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

import math
from typing import Any, Sequence

from markupsafe import Markup

from panorama_api.schemas.markets import MarketItem, MarketsResponse, ShareResponse
from panorama_api.web.conteudo import (
    DEFINICAO_CONCORRENCIA,
    ETAPA_PADRAO_MERCADO,
    MOTIVO_ALEM_DO_FIM,
    MOTIVO_ENTRADA_SAIDA,
    MOTIVO_SEM_PRIVADAS,
    ROTULO_VISAO_GERAL,
    TEXTO_ABAIXO_PORTE,
    UNIVERSOS,
    rotulo_etapa,
    traduzir_aviso,
)

from panorama_api.web.filters import SEM_DADO, fmt_ano, fmt_contagem, fmt_nulo

#: Identificador de cada seção do mercado no subnav (spec §2.2).
VISAO_GERAL = "visao_geral"
ESCOLAS = "escolas"

#: Rótulo do item do subnav que leva ao ranking (spec §1).
ROTULO_ESCOLAS_MERCADO = "Escolas do mercado"

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


def itens_subnav(
    *,
    caminho: str,
    filtros: dict[str, str],
    ativo: str,
    url_lista: Any,
) -> list[dict[str, Any]]:
    """Itens do subnav do mercado — macro única, sem JS (spec §2.2).

    Os dois links levam o recorte atual (`ano` e `etapa`) e **nunca** `offset`:
    a página do ranking é a sua própria URL canônica, e trocar de seção recomeça
    na primeira página. A rota ativa leva `aria-current="page"` (macro
    `partials/subnav.html`).
    """
    return [
        {
            "rotulo": ROTULO_VISAO_GERAL,
            "href": url_lista(caminho, filtros),
            "ativo": ativo == VISAO_GERAL,
            "classe": "",
        },
        {
            "rotulo": ROTULO_ESCOLAS_MERCADO,
            "href": url_lista(f"{caminho}/escolas", filtros),
            "ativo": ativo == ESCOLAS,
            "classe": "",
        },
    ]


def _linhas_por_etapa(items: Sequence[MarketItem]) -> list[dict[str, Any]]:
    """Uma linha por etapa servida por `mart_mercado` (ordem do contrato).

    `n_escolas_ativas`/`n_escolas_privadas` **não** entram aqui: a mart repete o
    total do município em todas as etapas e repeti-lo linha a linha sugere nove
    números diferentes. O total aparece uma única vez no resumo da página
    (`denominadores`), tirado da linha da etapa selecionada.

    `fixa` marca a linha que **não** é uma etapa do mercado: `bas` é o total
    oficial do Censo (a mesma leitura de `routes.py`), então ela não participa
    da ordenação no cliente e fica na posição original. A decisão vem da chave
    da etapa, nunca do rótulo (`t_ee9b1eec`).
    """
    return [
        {
            "etapa": item.etapa,
            "rotulo": rotulo_etapa(item.etapa),
            "fixa": item.etapa == ETAPA_PADRAO_MERCADO,
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
    """Linha da etapa selecionada (cobertura e movimento são de uma etapa)."""
    return next((linha for linha in linhas if linha["etapa"] == etapa), None)


def _item_da_etapa(items: Sequence[MarketItem], etapa: str) -> MarketItem | None:
    """Item de `mart_mercado` da etapa selecionada (fonte dos denominadores)."""
    return next((item for item in items if item.etapa == etapa), None)


def _formatar_largura(valor: float) -> str:
    """Largura do `<rect>`: determinística, sem zeros à direita e sem expoente.

    ``37.5`` → ``37.5``, ``100.0`` → ``100``, ``0.0834`` → ``0.0834``. Quatro
    casas bastam para o share (o menor passo do contrato é 0,0001 p.p.) e
    evitam a notação científica que ``str(float)`` produziria para valores
    ínfimos — o atributo só aceita número decimal.
    """
    return f"{valor:.4f}".rstrip("0").rstrip(".")


def barra_share(pct: float | None) -> Markup | None:
    """Barra decorativa do share em matrícula privada (SVG inline, sem JS).

    Devolve ``None`` quando **não há share** (``None``, ``NaN``, ``inf``): a
    ausência nunca vira zero (AGENTS.md §6) — a célula fica só com o número
    "sem dado". Valor fora de 0..100 é limitado à faixa, porque a barra é uma
    leitura visual e não pode estourar o `viewBox`.

    O SVG é ``aria-hidden``/``focusable="false"``: o número em texto na célula
    continua sendo a leitura acessível, a barra não duplica a informação.
    Nada externo é interpolado além do número já limitado — por isso o
    ``Markup`` pode ser usado sem abrir escape no template. Sem ``xmlns``: o SVG
    é inline no HTML, onde o namespace já é o do documento (e o atributo
    custaria ~38 B em cada linha do ranking).
    """
    if pct is None or not math.isfinite(pct):
        return None
    largura = _formatar_largura(min(max(float(pct), 0.0), 100.0))
    return Markup(
        '<svg class="barra-share" viewBox="0 0 100 8" aria-hidden="true" '
        f'focusable="false"><rect width="{largura}" height="8"/></svg>'
    )


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
            # Barra decorativa ao lado do número (o número não muda): `None`
            # quando o share é nulo, para a célula não ganhar um zero visual.
            "barra_share": barra_share(item.share_privado_pct),
        }
        for indice, item in enumerate(share.data.items)
    ]


def kpis_mercado(
    *, denominadores: dict[str, Any], ano: int | None
) -> list[dict[str, Any]]:
    """Os quatro KPIs do topo do mercado (card V2 `t_cbd54a92`).

    Matrícula privada, escolas privadas ativas, cobertura privada
    (`qt_mat_privada / qt_mat_total`) e a variação anual. A tela cobre **um**
    ano (a composição é por etapa, não por ano), então não há ano anterior no
    próprio recorte para a variação: ela sai como ``sem dado`` com o motivo —
    nunca ``0`` nem um número de outro recorte.
    """
    priv = denominadores.get("qt_mat_privada")
    total = denominadores.get("qt_mat_total")
    cobertura = (priv / total * 100) if priv is not None and total else None
    return [
        {
            "rotulo": f"Matrícula privada {fmt_ano(ano)}",
            "valor": fmt_contagem(priv),
            "classe": "",
            "nota": "soma das escolas privadas ativas do recorte",
        },
        {
            "rotulo": "Escolas privadas ativas",
            "valor": fmt_contagem(denominadores.get("n_escolas_privadas")),
            "classe": "",
            "nota": "no município e no ano",
        },
        {
            "rotulo": "Cobertura privada",
            "valor": (
                f"{fmt_nulo(cobertura)}%" if cobertura is not None else SEM_DADO
            ),
            "classe": "",
            "nota": "matrícula privada sobre a matrícula total do município",
        },
        {
            "rotulo": "Variação anual",
            "valor": SEM_DADO,
            "classe": "",
            "nota": (
                "o recorte desta tela é de um único ano — sem ano anterior "
                "para comparar"
            ),
        },
    ]


def contexto_visao_geral(*, mercado: MarketsResponse, etapa: str) -> dict[str, Any]:
    """Contexto da **Visão geral** — tudo sai de `dados.mercado` (3 consultas).

    `mercado` é consultado **sem** recorte de etapa: a composição por etapa é o
    conteúdo da tela. A etapa selecionada vale para os blocos de cobertura e
    entrada/saída e para os denominadores do resumo; a rota garante que ela
    existe entre as etapas publicadas (etapa sem linha é `404` com seletor).

    Os denominadores vêm da linha da etapa em `mart_mercado` — os mesmos campos
    que o `/v1` usa no share quando a página de share volta vazia. Assim a
    Visão geral não precisa da consulta de share para exibir o tamanho.
    """
    itens = list(mercado.data.items)
    etapas = _linhas_por_etapa(itens)
    item = _item_da_etapa(itens, etapa)

    return {
        "mercado": mercado.data,
        "ano_selecionado": mercado.meta.ano_referencia,
        "etapa_selecionada": etapa,
        "etapa_rotulo": rotulo_etapa(etapa),
        "etapas": etapas,
        # O seletor oferece só as etapas publicadas para este município/ano
        # (linhas de `mart_mercado`), não as 9 do contrato: etapa sem linha
        # seria um 404 anunciado na própria tela.
        "etapas_disponiveis": {linha["etapa"]: linha["rotulo"] for linha in etapas},
        "item_etapa": _linha_da_etapa(etapas, etapa),
        "denominadores": {
            "n_escolas_privadas": item.n_escolas_privadas if item else None,
            "n_escolas_ativas": item.n_escolas_ativas if item else None,
            "qt_mat_privada": item.qt_mat_privada if item else None,
            "qt_mat_total": item.qt_mat_total if item else None,
        },
        "motivo_entrada_saida": MOTIVO_ENTRADA_SAIDA,
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
        "universo_texto": UNIVERSOS.get(mercado.meta.universo),
    }


def contexto_escolas_mercado(
    *,
    share: ShareResponse,
    caminho: str,
    filtros_pagina: dict[str, str],
    montar_paginacao: Any,
    url_lista: Any,
) -> dict[str, Any]:
    """Contexto de **Escolas do mercado** — tudo sai de `dados.share_mercado`.

    `share.data.items` vazio é estado legítimo e tem **dois** significados que a
    tela não pode confundir (card `t_3ea9454f`, achado C2):

    * `offset == 0` → o município não tem escola privada com matrícula nesta
      etapa: "mercado sem escolas privadas com matrícula";
    * `offset > 0` → o `offset` passou do fim da lista (o mercado tem escolas;
      só não nesta página): "não há mais escolas nesta página" + volta à 1ª.

    O contrato não tem `total`, então `items: []` com `offset > 0` **nunca**
    prova ausência de mercado — só prova que a página está além do fim.
    """
    vazia = not share.data.items
    alem_do_fim = vazia and share.page.offset > 0

    return {
        "share": share.data,
        "ano_selecionado": share.meta.ano_referencia,
        "etapa_selecionada": share.data.etapa,
        "etapa_rotulo": rotulo_etapa(share.data.etapa),
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
        "texto_abaixo_porte": TEXTO_ABAIXO_PORTE,
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
        "universo_texto": UNIVERSOS.get(share.meta.universo),
        "paginacao": montar_paginacao(
            share.page, caminho=caminho, filtros=filtros_pagina
        ),
    }


__all__ = [
    "COBERTURA",
    "ESCOLAS",
    "MOVIMENTO",
    "ROTULO_ESCOLAS_MERCADO",
    "VISAO_GERAL",
    "barra_share",
    "contexto_escolas_mercado",
    "contexto_visao_geral",
    "itens_subnav",
    "kpis_mercado",
]
