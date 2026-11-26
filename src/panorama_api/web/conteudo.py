"""Textos e rótulos das telas — fonte única das regras de exibição (plano §1).

Nada aqui fala com o repositório: são apenas decisões de vocabulário. Rótulo de
métrica, tradução de `meta.avisos`, nome de etapa e a definição da comparação
municipal vivem neste módulo para que todas as telas digam a mesma coisa.

Proibições que este módulo materializa:

* `retencao_liquida_proxy_pct` **nunca** é "evasão": o rótulo diz explicitamente
  que não é taxa de evasão (`docs/escopo-adiado-v1.md`);
* a comparação é **municipal** — "raio", "próximos" e "na região" não existem.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from panorama_api.contract import (
    DEFINICAO_RETENCAO,
    UNIVERSO_ESCOLAS_ATIVAS_MG,
    UNIVERSO_ESCOLAS_MG,
    UNIVERSO_PRIVADAS_ATIVAS_MG,
    Etapa,
)
from panorama_api.web.dados import DESCRICAO_COMPETIDORES

#: Rótulos canônicos do proxy de retenção (contrato 2b R4). A métrica se chama
#: "proxy de retenção líquida"; o complemento existe para impedir que o número
#: seja lido como taxa de evasão.
ROTULO_RETENCAO = "Proxy de retenção líquida (não é taxa de evasão)"

#: Posições de **crescimento** da série (`rank_crec_municipio`/`rank_crec_mg`).
#: `crec` é abreviação de *crescimento* (`crescimento_yoy_pct`), não de creche —
#: lida como "creche", a linha exibia posição de creche para escola sem creche
#: nenhuma (escola 31005371, `qt_mat_creche = 0`). O parêntese fixa a direção:
#: 1.º é a escola que **mais cresceu**, não a de maior matrícula.
ROTULO_POSICAO_CRESCIMENTO_MUNICIPIO = (
    "Posição por crescimento anual da matrícula no município "
    "(1.º = maior crescimento ano a ano)"
)
ROTULO_POSICAO_CRESCIMENTO_MG = (
    "Posição por crescimento anual da matrícula em Minas Gerais "
    "(1.º = maior crescimento ano a ano)"
)

#: Definição visível da comparação de concorrência: mesma unidade geográfica
#: (município) e mesmo ano censitário.
DEFINICAO_CONCORRENCIA = DESCRICAO_COMPETIDORES

#: Universo de cada resposta do contrato, traduzido para leitura humana
#: (contrato 2b R1). Compartilhado entre a metodologia e as telas que exibem
#: `meta.universo` — a mesma string, sem duas cópias que possam divergir.
UNIVERSOS: Mapping[str, str] = {
    UNIVERSO_ESCOLAS_MG: "Todas as escolas do recorte (inclui inativas).",
    UNIVERSO_PRIVADAS_ATIVAS_MG: "Escolas privadas ativas no ano de referência.",
    UNIVERSO_ESCOLAS_ATIVAS_MG: "Escolas ativas no ano de referência.",
}

#: Título único da seção que não existe para a escola consultada (página 200).
NAO_SE_APLICA = "Não se aplica"
#: Motivo da seção quando a escola está fora do universo de privadas ativas.
MOTIVO_FORA_DO_UNIVERSO_PRIVADO = (
    "Indicadores e comparação municipal existem apenas para escolas privadas "
    "ativas (universo privadas_ativas_mg)."
)
#: Motivo quando a escola É privada ativa mas a mart não tem a linha do ano
#: (o `/v1` responde 404 nesse caso — ausência de dado, nunca zero).
MOTIVO_SECAO_INDICADORES = (
    "Os indicadores só existem para escolas privadas ativas com matrícula da "
    "educação básica observada no ano de referência."
)
MOTIVO_SECAO_COMPETIDORES = (
    "A comparação municipal só existe para escolas privadas ativas com "
    "matrícula da educação básica observada no município e ano."
)

#: Título da seção que virou rota própria na ficha (spec §2.2). O mesmo texto é o
#: item do subnav e o `<h1>`/trilha da rota `/app/escolas/{id}/concorrencia`.
TITULO_SECAO_CONCORRENCIA = "Indicadores e concorrência"
#: Rótulo do item de volta no subnav de seções.
ROTULO_VISAO_GERAL = "Visão geral"
#: Linha de orientação por âncoras dentro da própria página (sem JS).
TEXTO_NESTA_PAGINA = "Nesta página:"
#: Volta oferecida pela rota de concorrência quando a seção não se aplica.
TEXTO_VOLTAR_VISAO_GERAL = "Voltar para a Visão geral"

#: Nota da Visão geral quando a seção de indicadores não existe para a escola.
#: A decisão é tomada sem consulta, pelo item mais recente da série de `history`.
MOTIVO_SECAO_ESCOLA_PUBLICA = (
    "Indicadores e concorrência: não se aplica a escola pública."
)
MOTIVO_SECAO_ESCOLA_INATIVA = (
    "Indicadores e concorrência: não se aplica a escola inativa."
)

#: Comparação municipal ausente no **ano dos indicadores**: a seção mostra "sem
#: dado" com este motivo, nunca 0 (AGENTS.md §6).
MOTIVO_SEM_COMPARACAO = "sem linha de comparação municipal para {ano}"

#: Título da página de comparação entre duas escolas (card C4) e do link de
#: entrada na ficha. O texto é o mesmo nas duas pontas: o leitor reconhece o
#: destino pelo rótulo.
TITULO_COMPARACAO = "Comparação entre escolas"
ROTULO_COMPARAR_ENTRADA = "Comparar com outra escola"
ROTULO_COMPARAR_COM_ESTA = "Comparar com esta"

#: Escolas de municípios diferentes são permitidas na comparação lado a lado,
#: mas a leitura municipal (participação e posição) não vale para o par.
MOTIVO_MUNICIPIOS_DIFERENTES = (
    "As escolas estão em municípios diferentes: a comparação municipal "
    "(participação no mercado e posição) não se aplica a este par."
)

#: Sem ano censitário em comum, a oferta por etapa não tem ano de referência
#: comum — dizer "não se aplica" é mais honesto que escolher o ano de uma delas.
MOTIVO_SEM_ANO_COMUM = (
    "As duas escolas não têm ano censitário em comum na série: a oferta e a "
    "matrícula por etapa não podem ser comparadas no mesmo ano."
)

#: Estado legítimo da tela de mercado: a mart não tem linha de share para a
#: etapa, ou seja, nenhuma escola privada do recorte tem matrícula observada.
#: **Não** é ausência de mercado nem share de 0% para as escolas ausentes.
MOTIVO_SEM_PRIVADAS = "mercado sem escolas privadas com matrícula"

#: Página da lista de share além do fim (`offset > 0` com `items: []`). O
#: contrato não tem `total`, então página vazia **não** prova ausência de
#: mercado: só prova que não há mais linhas naquele offset. A tela oferece a
#: volta à 1ª página em vez de afirmar que o município não tem escolas privadas
#: (achado C2 do card `t_3ea9454f`).
MOTIVO_ALEM_DO_FIM = "Não há mais escolas nesta página."

#: `n_escolas_entraram`/`n_escolas_ativas_com_baseline`/`n_escolas_sairam` são
#: NULL no primeiro ano da série (não há baseline anterior). Ausência de dado,
#: nunca zero.
MOTIVO_ENTRADA_SAIDA = (
    "No primeiro ano da série não há baseline anterior: entrada, base comparável "
    "e saída de escolas aparecem como sem dado — nunca como zero."
)

#: Motivo da linha de um ano que existe no intervalo da série mas não tem
#: registro na fonte (a mart não traz a linha daquele ano censitário). O ano
#: continua visível para que a lacuna não desapareça da tabela.
MOTIVO_ANO_AUSENTE = "ano ausente na fonte"

#: Texto curto da oferta desconhecida (marcador inline de célula/lista). O
#: nome é o mesmo do estado tri-estado ("Desconhecido"); a flag interna
#: `is_oferta_desconhecida` nunca é exibida.
TEXTO_OFERTA_DESCONHECIDA = "Oferta desconhecida"

#: Explicação completa da oferta desconhecida, usada na ficha e na metodologia.
EXPLICACAO_OFERTA_DESCONHECIDA = (
    "Oferta desconhecida significa que a base não informou a oferta daquela "
    "etapa no ano. Leia essas células como ausência de informação, não como "
    "ausência de oferta."
)

#: Texto curto do porte mínimo de comparabilidade (célula de lista/tabela).
TEXTO_ABAIXO_PORTE = "abaixo do porte mínimo de comparabilidade"

#: Explicação completa do porte mínimo, usada na ficha e na metodologia.
EXPLICACAO_ABAIXO_PORTE = (
    "A escola está abaixo do porte mínimo de comparabilidade: os indicadores "
    "comparativos existem, mas devem ser lidos com cautela."
)

#: Código do aviso de metodologia não comparável — o que aparece hoje nas
#: fichas. É o único código que a metodologia exibe: é por ele que o usuário
#: reconhece, na ficha, o aviso explicado lá.
AVISO_METODOLOGIA_CODIGO = "METODOLOGIA_INCOMPARAVEL_2025"

#: Por que a série de uma etapa deixa de ser comparável. Vem da macro
#: `inep_metodologia_incomparavel` do dbt (educação profissional e EJA a partir
#: de 2025): o aviso existe para que a comparação ano a ano não seja feita às
#: cegas.
EXPLICACAO_METODOLOGIA_INCOMPARAVEL = (
    "Educação profissional e EJA mudaram a metodologia de coleta do Censo "
    "Escolar a partir de 2025 (a matrícula passou a ser subdividida). A série "
    "dessas duas etapas não é diretamente comparável entre 2024 e 2025: "
    "compare 2020–2024 entre si e leia 2025 em diante como um novo patamar. "
    "As demais etapas não são afetadas."
)

#: Nome de exibição da etapa que o seletor mostra quando não foi informada:
#: `bas` é o total oficial do Censo (a leitura municipal padrão), não a soma das
#: subetapas (`docs/api-v1.md`).
ETAPA_PADRAO_MERCADO = "bas"

#: Nome de exibição de cada etapa. `bas` é o total oficial, não a soma das
#: subetapas (`docs/api-v1.md`).
ETAPAS_ROTULOS: dict[Etapa, str] = {
    "bas": "Educação básica (total)",
    "creche": "Creche",
    "pre": "Pré-escola",
    "fund_ai": "Ensino fundamental — anos iniciais",
    "fund_af": "Ensino fundamental — anos finais",
    "med": "Ensino médio",
    "prof": "Educação profissional",
    "eja": "EJA",
    "esp": "Educação especial",
}

#: Grupos semânticos da tabela "Oferta e matrícula por etapa" (card F11). As
#: nove linhas têm naturezas diferentes: listadas como etapas irmãs, somavam
#: 2.061 alunos numa escola de 680 (total oficial 680 + ensino médio 680 +
#: educação profissional 680 + educação especial 21). Cada grupo diz, no
#: próprio título e na nota, se soma ou não ao total.
TITULO_GRUPO_TOTAL = "Total oficial"
NOTA_GRUPO_TOTAL = (
    "Educação básica é o total do Censo; não é a soma das linhas abaixo."
)
TITULO_GRUPO_ETAPAS = "Etapas que somam ao total"
NOTA_GRUPO_ETAPAS = (
    "Somam quando não há lacuna (sem dado); a EJA entra como parcela própria "
    "na contagem do Censo."
)
TITULO_GRUPO_MODALIDADES = "Modalidades e subconjuntos que não somam ao total"
NOTA_GRUPO_MODALIDADES = (
    "A educação profissional acompanha o ensino médio (o técnico integrado é "
    "contado nas duas linhas) e a educação especial é modalidade transversal a "
    "todas as etapas."
)

#: Definições publicadas em `meta.definicoes` e reexibidas na metodologia.
DEFINICOES: dict[str, str] = {
    "retencao_liquida_proxy_pct": DEFINICAO_RETENCAO,
    "competidores": DEFINICAO_CONCORRENCIA,
}

#: Tradução dos códigos de `meta.avisos` para texto de tela, em português.
#: Nenhum código interno do contrato aparece como texto de aviso: o leitor vê a
#: explicação (a conferência com o JSON fica na metodologia).
_AVISOS: dict[str, str] = {
    "IS_ABAIXO_PORTE": "Escola abaixo do porte mínimo de comparabilidade",
}
_AVISO_METODOLOGIA = "Etapas com metodologia não comparável em {ano}"
_PREFIXO_METODOLOGIA = "METODOLOGIA_INCOMPARAVEL_"


def rotulo_etapa(etapa: str | None) -> str:
    """Nome de exibição da etapa; `None` = resposta cobre as 9 etapas."""
    if etapa is None:
        return "Todas as etapas"
    return ETAPAS_ROTULOS.get(etapa, etapa)  # type: ignore[arg-type]


def anos_publicados(anos: Sequence[int]) -> str:
    """Anos do Censo como o painel do recorte os exibe (spec §4).

    Lista contínua vira faixa com meia-risca (``2021–2025``): diz o mesmo que os
    cinco anos e ocupa menos na coluna do painel. Um buraco na lista força os
    anos separados por vírgula — a faixa prometeria um ano não publicado.
    """
    if len(anos) > 1 and all(
        seguinte - atual == 1 for atual, seguinte in zip(anos, anos[1:])
    ):
        return f"{anos[0]}–{anos[-1]}"
    return ", ".join(str(ano) for ano in anos)


def traduzir_aviso(codigo: str) -> str:
    """Traduz um código de `meta.avisos`; código desconhecido é exibido cru."""
    if codigo in _AVISOS:
        return _AVISOS[codigo]
    if codigo.startswith(_PREFIXO_METODOLOGIA):
        ano = codigo[len(_PREFIXO_METODOLOGIA) :]
        if ano.isascii() and ano.isdigit():
            return f"{_AVISO_METODOLOGIA.format(ano=ano)} ({codigo})"
    return codigo


def traduzir_avisos(codigos: list[str] | None) -> list[str]:
    """Traduz a lista de `meta.avisos` preservando a ordem e removendo vazios."""
    return [traduzir_aviso(codigo) for codigo in (codigos or ())]


#: Avisos de `meta.avisos` que a metodologia explica. O rótulo é a leitura
#: humana; o código do contrato aparece só na entrada de metodologia, porque é
#: ele que a ficha exibe hoje (o usuário precisa reconhecê-lo).
AVISOS_METODOLOGIA: tuple[tuple[str, str], ...] = (
    ("Porte mínimo de comparabilidade", EXPLICACAO_ABAIXO_PORTE),
    (
        f"Metodologia não comparável ({AVISO_METODOLOGIA_CODIGO})",
        EXPLICACAO_METODOLOGIA_INCOMPARAVEL,
    ),
)


__all__ = [
    "AVISOS_METODOLOGIA",
    "AVISO_METODOLOGIA_CODIGO",
    "DEFINICAO_CONCORRENCIA",
    "DEFINICOES",
    "ETAPAS_ROTULOS",
    "ETAPA_PADRAO_MERCADO",
    "EXPLICACAO_ABAIXO_PORTE",
    "EXPLICACAO_METODOLOGIA_INCOMPARAVEL",
    "EXPLICACAO_OFERTA_DESCONHECIDA",
    "MOTIVO_ANO_AUSENTE",
    "MOTIVO_ENTRADA_SAIDA",
    "MOTIVO_ALEM_DO_FIM",
    "MOTIVO_FORA_DO_UNIVERSO_PRIVADO",
    "MOTIVO_MUNICIPIOS_DIFERENTES",
    "MOTIVO_SECAO_COMPETIDORES",
    "MOTIVO_SECAO_ESCOLA_INATIVA",
    "MOTIVO_SECAO_ESCOLA_PUBLICA",
    "MOTIVO_SECAO_INDICADORES",
    "MOTIVO_SEM_ANO_COMUM",
    "MOTIVO_SEM_COMPARACAO",
    "MOTIVO_SEM_PRIVADAS",
    "NAO_SE_APLICA",
    "NOTA_GRUPO_ETAPAS",
    "NOTA_GRUPO_MODALIDADES",
    "NOTA_GRUPO_TOTAL",
    "ROTULO_COMPARAR_COM_ESTA",
    "ROTULO_COMPARAR_ENTRADA",
    "ROTULO_POSICAO_CRESCIMENTO_MG",
    "ROTULO_POSICAO_CRESCIMENTO_MUNICIPIO",
    "ROTULO_RETENCAO",
    "ROTULO_VISAO_GERAL",
    "TEXTO_ABAIXO_PORTE",
    "TEXTO_NESTA_PAGINA",
    "TEXTO_OFERTA_DESCONHECIDA",
    "TEXTO_VOLTAR_VISAO_GERAL",
    "TITULO_COMPARACAO",
    "TITULO_GRUPO_ETAPAS",
    "TITULO_GRUPO_MODALIDADES",
    "TITULO_GRUPO_TOTAL",
    "TITULO_SECAO_CONCORRENCIA",
    "UNIVERSOS",
    "anos_publicados",
    "rotulo_etapa",
    "traduzir_aviso",
    "traduzir_avisos",
]
