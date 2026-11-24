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

from typing import Mapping

from panorama_api.contract import (
    DEFINICAO_RETENCAO,
    UNIVERSO_ESCOLAS_ATIVAS_MG,
    UNIVERSO_ESCOLAS_MG,
    UNIVERSO_PRIVADAS_ATIVAS_MG,
    Etapa,
)
from panorama_api.web.dados import DESCRICAO_COMPETIDORES

#: Rótulo canônico do proxy de retenção (contrato 2b R4). A métrica se chama
#: "proxy de retenção líquida"; o complemento existe para impedir que o número
#: seja lido como taxa de evasão.
ROTULO_RETENCAO = "Proxy de retenção líquida (não é taxa de evasão)"

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

#: Definições publicadas em `meta.definicoes` e reexibidas na metodologia.
DEFINICOES: dict[str, str] = {
    "retencao_liquida_proxy_pct": DEFINICAO_RETENCAO,
    "competidores": DEFINICAO_CONCORRENCIA,
}

#: Tradução dos códigos de `meta.avisos` para texto de tela. O código original
#: sempre fica visível entre parênteses para conferência com o JSON da API.
_AVISOS: dict[str, str] = {
    "IS_ABAIXO_PORTE": (
        "Escola abaixo do porte mínimo de comparabilidade (IS_ABAIXO_PORTE)"
    ),
}
_AVISO_METODOLOGIA = "Etapas com metodologia não comparável em {ano}"
_PREFIXO_METODOLOGIA = "METODOLOGIA_INCOMPARAVEL_"


def rotulo_etapa(etapa: str | None) -> str:
    """Nome de exibição da etapa; `None` = resposta cobre as 9 etapas."""
    if etapa is None:
        return "Todas as etapas"
    return ETAPAS_ROTULOS.get(etapa, etapa)  # type: ignore[arg-type]


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


__all__ = [
    "DEFINICAO_CONCORRENCIA",
    "DEFINICOES",
    "ETAPAS_ROTULOS",
    "ETAPA_PADRAO_MERCADO",
    "MOTIVO_ENTRADA_SAIDA",
    "MOTIVO_ALEM_DO_FIM",
    "MOTIVO_FORA_DO_UNIVERSO_PRIVADO",
    "MOTIVO_SECAO_COMPETIDORES",
    "MOTIVO_SECAO_INDICADORES",
    "MOTIVO_SEM_PRIVADAS",
    "NAO_SE_APLICA",
    "ROTULO_RETENCAO",
    "UNIVERSOS",
    "rotulo_etapa",
    "traduzir_aviso",
    "traduzir_avisos",
]
