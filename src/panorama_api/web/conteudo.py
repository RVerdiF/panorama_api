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

from panorama_api.contract import DEFINICAO_RETENCAO, Etapa
from panorama_api.services.schools import DESCRICAO_COMPETIDORES

#: Rótulo canônico do proxy de retenção (contrato 2b R4). A métrica se chama
#: "proxy de retenção líquida"; o complemento existe para impedir que o número
#: seja lido como taxa de evasão.
ROTULO_RETENCAO = "Proxy de retenção líquida (não é taxa de evasão)"

#: Definição visível da comparação de concorrência: mesma unidade geográfica
#: (município) e mesmo ano censitário.
DEFINICAO_CONCORRENCIA = DESCRICAO_COMPETIDORES

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
    "ROTULO_RETENCAO",
    "rotulo_etapa",
    "traduzir_aviso",
    "traduzir_avisos",
]
