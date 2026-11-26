"""Regras da tela de mercado: Visão geral + Escolas do mercado (card D1-E3).

Tudo aqui é **puro**: recebe as respostas do contrato (as mesmas do `/v1`) e
devolve o contexto do template. Nenhum acesso a dado — quem consulta é
`web/dados.py`, chamado pela rota em `web/routes.py`.

Uma rota, duas consultas (decisão D4 do plano):

* `/app/mercados/{co_municipio}` — **tamanho, composição**, cobertura,
  entrada/saída e o ranking de share **paginado na própria página**
  (`section#escolas`, 10 linhas por página). Consulta `dados.mercado` mais
  `dados.share_mercado` (`limit=10`, na etapa do recorte, deslocado por
  `offset`); `offset` fora de `0..1000` continua `422`.
* `/app/mercados/{co_municipio}/escolas` não existe mais: virou **301** para
  `/app/mercados/{co}?ano&etapa&offset#escolas` (o handler mora em
  `web/routes.py`, sem contexto nem template).

Decisões que moram neste módulo:

1. **Sem concentração (HHI/C4) na tela.** Decisão D4 do plano: fora do MVP. Os
   campos `concentracao` do contrato são consultados pelo `/v1` e não exibidos.
2. **Concorrência é municipal.** A contagem vem de `n_escolas_privadas`/
   `n_escolas_ativas` do mesmo município e ano — vocabulário de raio/proximidade
   não existe aqui (`docs/escopo-adiado-v1`). Essas duas contagens **não**
   variam por etapa na mart e aparecem uma única vez, nos KPIs.
3. **Ausência nunca vira zero.** `share_privado_pct` nulo e os campos de
   entrada/saída do primeiro ano da série saem como "sem dado" com o motivo;
   escola ausente do share **não é** 0%.
4. **Composição são 5 etapas que somam** (decisão D9): Creche, Pré-escola,
   anos iniciais e finais do fundamental e Ensino médio. EJA, especial,
   profissional e o total `bas` ficam fora do gráfico (não somam).
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

#: Rótulo do item do subnav que leva ao ranking (spec §1).
ROTULO_ESCOLAS_MERCADO = "Escolas do mercado"

#: Etapas que somam no gráfico de composição, nesta ordem (decisão D9).
COMPOSICAO_ETAPAS: tuple[str, ...] = ("creche", "pre", "fund_ai", "fund_af", "med")


def itens_subnav(*, prefixo: str) -> list[dict[str, Any]]:
    """Itens do subnav do mercado — literais do protótipo, sem JS.

    As duas primeiras são âncoras da própria página (`#composicao` leva
    `aria-current="page"`, como no protótipo); as duas últimas saem da tela
    (índice de municípios e busca). Sem `offset`, sem params mortos e sem
    classe: o protótipo não tem classe nesses links (macro
    `partials/subnav.html`).
    """
    return [
        {
            "rotulo": ROTULO_VISAO_GERAL,
            "href": "#composicao",
            "ativo": True,
            "classe": "",
        },
        {
            "rotulo": ROTULO_ESCOLAS_MERCADO,
            "href": "#escolas",
            "ativo": False,
            "classe": "",
        },
        {
            "rotulo": "← Índice de municípios",
            "href": f"{prefixo}/mercados/",
            "ativo": False,
            "classe": "",
        },
        {
            "rotulo": "Buscar escolas",
            "href": f"{prefixo}/",
            "ativo": False,
            "classe": "",
        },
    ]


def _linhas_por_etapa(items: Sequence[MarketItem]) -> list[dict[str, Any]]:
    """Uma linha por etapa servida por `mart_mercado` (ordem do contrato).

    `n_escolas_ativas`/`n_escolas_privadas` **não** entram aqui: a mart repete o
    total do município em todas as etapas e repeti-lo linha a linha sugere nove
    números diferentes. O total aparece uma única vez nos KPIs da página
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
            "qt_mat_total": item.qt_mat_total,
            "qt_mat_publica": item.qt_mat_publica,
            "qt_mat_privada": item.qt_mat_privada,
            "pct_privada_no_total_pct": item.pct_privada_no_total_pct,
        }
        for item in items
    ]


def _item_da_etapa(items: Sequence[MarketItem], etapa: str) -> MarketItem | None:
    """Item de `mart_mercado` da etapa selecionada (fonte dos denominadores)."""
    return next((item for item in items if item.etapa == etapa), None)


def composicao_do_mercado(
    linhas: Sequence[dict[str, Any]], *, total_privado_bas: float | None
) -> tuple[list[dict[str, Any]], float | None]:
    """As 5 etapas que somam, com % do total privado e largura da barra.

    `pct` é a fração do total privado do ano (`qt_mat_privada` da linha `bas`,
    1 casa); `largura` é a fração do maior valor entre as 5 (1 casa, para
    `data-largura` + `aplicarBarras`). Etapa sem valor sai com `None` nos três
    campos: o template mostra `sem dado` e não desenha barra. A soma cobre só
    as etapas presentes (`None` quando nenhuma tem valor — nunca `0`).
    """
    por_etapa = {linha["etapa"]: linha["qt_mat_privada"] for linha in linhas}
    valores = [por_etapa.get(etapa) for etapa in COMPOSICAO_ETAPAS]
    presentes = [v for v in valores if v is not None]
    maximo = max(presentes) if presentes else None
    itens = []
    for etapa, valor in zip(COMPOSICAO_ETAPAS, valores):
        if valor is None:
            itens.append(
                {
                    "etapa": etapa,
                    "rotulo": rotulo_etapa(etapa),
                    "qt_mat_privada": None,
                    "pct": None,
                    "largura": None,
                }
            )
            continue
        itens.append(
            {
                "etapa": etapa,
                "rotulo": rotulo_etapa(etapa),
                "qt_mat_privada": valor,
                "pct": (
                    valor / total_privado_bas * 100 if total_privado_bas else None
                ),
                "largura": f"{valor / maximo * 100:.1f}" if maximo else None,
            }
        )
    soma = sum(presentes) if presentes else None
    return itens, soma


def movimento_para_ranking(
    *,
    item: MarketItem | None,
    privadas_ativas: int | float | None,
    ano_ref: int,
) -> dict[str, Any] | None:
    """O cartão único do `ul.ranking` do movimento — ou `None` no 1º ano.

    Entrada e saída comparam dois anos: quando os três campos são nulos (sem
    baseline, o 1º ano da série), o bloco vira o `estado-vazio` do protótipo
    em vez de mostrar zero. Fora isso, o cartão mostra as privadas ativas com
    `entraram`/`saíram` da etapa selecionada.
    """
    if item is None or (
        item.n_escolas_entraram is None
        and item.n_escolas_ativas_com_baseline is None
        and item.n_escolas_sairam is None
    ):
        return None
    return {
        "ativas": privadas_ativas,
        "entraram": item.n_escolas_entraram,
        "sairam": item.n_escolas_sairam,
        "ano": ano_ref,
        "ano_anterior": ano_ref - 1,
    }


def barra_share(pct: float | None) -> Markup | None:
    """Barra decorativa do share em matrícula privada (CSS do protótipo).

    Devolve o trilho com o preenchimento em ``data-largura="X%"`` — o
    percentual real, saturado em 0..100 com uma casa (par do protótipo) — ou
    ``None`` quando **não há share** (``None``, ``NaN``, ``inf``): a ausência
    nunca vira zero (AGENTS.md §6) — a célula fica só com o número
    "sem dado".

    Sem ``style=`` de propósito: a CSP é `style-src 'self'` (sem
    `'unsafe-inline'`) e o navegador descarta o atributo — a barra nunca
    ganhava largura em produção (rodada 1 da revisão, item 1). A largura é
    aplicada pelo `app.js` (`data-largura` → CSSOM, que a CSP permite); sem
    JS, o número ao lado continua legível e a barra fica vazia — nunca
    errada.

    O trilho não carrega texto: a leitura acessível é o número ao lado
    (`.barra-share__valor` no ranking, o `<td>` na tabela do mercado).
    Nada externo é interpolado além do número já limitado — por isso o
    ``Markup`` pode ser usado sem abrir escape no template.
    """
    if pct is None or not math.isfinite(pct):
        return None
    largura = f"{min(max(float(pct), 0.0), 100.0):.1f}"
    return Markup(
        '<span class="barra-share__trilho">'
        f'<span class="barra-share__preenche" data-largura="{largura}%"></span>'
        "</span>"
    )


def _linhas_share(share: ShareResponse) -> list[dict[str, Any]]:
    """Ranking do share na página, com a posição explícita (o contrato não tem `total`).

    `share_privado_fmt` é o número com 2 casas no formato BR (`37,50`) para a
    célula `td.num.metrica`; `None` vira `sem dado` no template, nunca `0%`.
    """
    offset = share.page.offset
    return [
        {
            "posicao": offset + indice + 1,
            "id_entidade": item.id_entidade,
            "no_entidade": item.no_entidade,
            "mat_entidade": item.mat_entidade,
            "share_privado_pct": item.share_privado_pct,
            "share_privado_fmt": (
                f"{item.share_privado_pct:.2f}".replace(".", ",")
                if item.share_privado_pct is not None
                else None
            ),
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


def contexto_visao_geral(
    *, mercado: MarketsResponse, etapa: str, anos: Sequence[int]
) -> dict[str, Any]:
    """Contexto da tela — tudo sai de `dados.mercado` (3 consultas).

    `mercado` é consultado **sem** recorte de etapa: a composição por etapa é o
    conteúdo da tela. A etapa selecionada vale para o movimento e para os
    denominadores dos KPIs; a rota garante que ela existe entre as etapas
    publicadas (etapa sem linha é `404` com seletor).

    Os denominadores vêm da linha da etapa em `mart_mercado` — os mesmos campos
    que o `/v1` usa no share quando a página de share volta vazia. Assim a
    tela não precisa da consulta de share para exibir o tamanho.
    """
    itens = list(mercado.data.items)
    etapas = _linhas_por_etapa(itens)
    item = _item_da_etapa(itens, etapa)
    # A rota só chama este contexto depois de resolver e validar o ano, então
    # a meta sempre traz o ano de referência; o `max(anos)` é o mesmo padrão
    # do seletor, para o tipo continuar `int` no `ano - 1` do movimento.
    ano_ref = (
        mercado.meta.ano_referencia
        if mercado.meta.ano_referencia is not None
        else max(anos)
    )
    denominadores = {
        "n_escolas_privadas": item.n_escolas_privadas if item else None,
        "n_escolas_ativas": item.n_escolas_ativas if item else None,
        "qt_mat_privada": item.qt_mat_privada if item else None,
        "qt_mat_total": item.qt_mat_total if item else None,
    }
    bas = _item_da_etapa(itens, ETAPA_PADRAO_MERCADO)
    composicao, soma_etapas = composicao_do_mercado(
        etapas,
        total_privado_bas=bas.qt_mat_privada if bas else None,
    )

    return {
        "mercado": mercado.data,
        "ano_selecionado": ano_ref,
        "etapa_selecionada": etapa,
        "etapa_rotulo": rotulo_etapa(etapa),
        "menor_ano": min(anos),
        "composicao": composicao,
        "soma_etapas": soma_etapas,
        "total_privado_bas": bas.qt_mat_privada if bas else None,
        "movimento": movimento_para_ranking(
            item=item,
            privadas_ativas=denominadores["n_escolas_privadas"],
            ano_ref=ano_ref,
        ),
        "denominadores": denominadores,
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
    "COMPOSICAO_ETAPAS",
    "ROTULO_ESCOLAS_MERCADO",
    "barra_share",
    "composicao_do_mercado",
    "contexto_escolas_mercado",
    "contexto_visao_geral",
    "itens_subnav",
    "kpis_mercado",
    "movimento_para_ranking",
]
