"""Filtros de template — fonte única das regras de exibição (plano §1).

Nenhuma tela formata valor numérico "na mão": toda formatação passa por aqui,
para que `null` nunca vire `0` e a oferta tri-estado nunca seja lida como
booleano simples.
"""

from __future__ import annotations

from typing import Any

#: Texto único para ausência de dado. A palavra é a mesma em todas as telas.
SEM_DADO = "sem dado"
#: Oferta `null` = desconhecido (`is_oferta_desconhecida` ≠ "não oferta").
OFERTA_DESCONHECIDA = "Desconhecido"


def fmt_nulo(valor: Any, motivo: str | None = None) -> str:
    """Formata um valor, preservando ausência como ausência.

    - `None` (e string vazia) → ``"sem dado"``; com ``motivo`` → ``"sem dado (motivo)"``.
      **Nunca** ``0`` e nunca célula vazia ambígua.
    - `bool` → ``"Sim"``/``"Não"`` (dado binário; oferta tem filtro próprio).
    - `int`/`float` → separador de milhar ``.`` e decimal ``,``.
    """
    if valor is None:
        return _sem_dado(motivo)
    if isinstance(valor, str):
        texto = valor.strip()
        return texto if texto else _sem_dado(motivo)
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    if isinstance(valor, int):
        return f"{valor:,}".replace(",", ".")
    if isinstance(valor, float):
        inteiro, _, decimal = f"{valor:,.1f}".partition(".")
        return f"{inteiro.replace(',', '.')},{decimal}"
    return str(valor)


def fmt_oferta(valor: Any) -> str:
    """Oferta tri-estado: ``True`` → "Sim", ``False`` → "Não", ``None`` → "Desconhecido".

    Regra do plano §1: `null` de oferta é *desconhecido* — nunca "não oferta".
    A flag `is_oferta_desconhecida` explica a origem da ausência, mas o texto
    da célula é sempre um dos três estados para não virar leitura de "sem oferta".
    """
    if valor is None:
        return OFERTA_DESCONHECIDA
    return "Sim" if valor else "Não"


def fmt_ano(valor: Any) -> str:
    """Ano censitário: sem separador de milhar e sem `0` para ausência.

    `fmt_nulo` formata números com milhar (``2.025``), o que está errado para
    ano. Aqui o ano sai como ``2025`` e a ausência continua ``sem dado``.
    """
    if valor is None:
        return SEM_DADO
    if isinstance(valor, bool):  # bool é subclasse de int: não é ano
        return fmt_nulo(valor)
    if isinstance(valor, int):
        return str(valor)
    texto = str(valor).strip()
    return texto or SEM_DADO


def fmt_gap_lider(valor: Any) -> str:
    """Saldo de matrícula para o líder do município (plano §1).

    ``gap_mat_bas_para_lider = 0`` é **medição válida**: a própria escola é a
    líder, não ausência de dado. Por isso o texto é "a escola lidera" em vez de
    "0" — que na tabela seria lido como "sem matrícula".
    """
    if valor is None:
        return SEM_DADO
    if valor == 0:
        return "a escola lidera"
    return fmt_nulo(valor)


def _sem_dado(motivo: str | None) -> str:
    return f"{SEM_DADO} ({motivo})" if motivo else SEM_DADO


__all__ = [
    "OFERTA_DESCONHECIDA",
    "SEM_DADO",
    "fmt_ano",
    "fmt_gap_lider",
    "fmt_nulo",
    "fmt_oferta",
]
