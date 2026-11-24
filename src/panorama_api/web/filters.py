"""Filtros de template — fonte única das regras de exibição (plano §1).

Nenhuma tela formata valor numérico "na mão": toda formatação passa por aqui,
para que `null` nunca vire `0` e a oferta tri-estado nunca seja lida como
booleano simples.
"""

from __future__ import annotations

from typing import Any, Mapping

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


def fmt_contagem(valor: Any, motivo: str | None = None) -> str:
    """Contagem (escolas, matrículas, posições): inteiro nunca sai com ``,0``.

    A mart devolve alguns contadores como `float` (ex.: `n_escolas_entraram`,
    `qt_mat_total`). Um float integral é uma contagem inteira, não uma medida
    fracionária: exibir ``43,0`` sugere precisão que não existe e mistura
    contagem com percentual na mesma tabela. Por isso:

    - `float` integral → mesmo texto de `int` (``43``, ``172.322``);
    - `float` fracionário → mantém a casa decimal (não trunca dado real);
    - `None`/vazio → ``sem dado`` com o motivo, como em `fmt_nulo`;
    - `bool` → ``Sim``/``Não`` (é subclasse de `int`, não é contagem).

    Percentual **não** passa por aqui: continua em `fmt_nulo` com 1 casa.
    """
    if isinstance(valor, bool):
        return fmt_nulo(valor, motivo)
    if isinstance(valor, float) and valor.is_integer():
        return fmt_nulo(int(valor), motivo)
    return fmt_nulo(valor, motivo)


def fmt_celula(celula: Mapping[str, Any]) -> str:
    """Célula de tabela ``{valor, motivo, unidade}`` (as que `web/escola.py` monta).

    A unidade decide a formatação: ``%`` é medida fracionária (1 casa, via
    `fmt_nulo`); qualquer outra (inclusive vazia) é contagem e não mostra
    ``,0`` (via `fmt_contagem`). A unidade só acompanha um valor presente:
    ausência continua ``sem dado (motivo)``, sem sufixo — "sem dado%" não
    existe.
    """
    valor = celula.get("valor")
    motivo = celula.get("motivo")
    unidade = celula.get("unidade") or ""
    if unidade == "%":
        texto = fmt_nulo(valor, motivo)
    else:
        texto = fmt_contagem(valor, motivo)
    if valor is None or not unidade:
        return texto
    return f"{texto}{unidade}"


def fmt_oferta(valor: Any) -> str:
    """Oferta tri-estado: ``True`` → "Sim", ``False`` → "Não", ``None`` → "Desconhecido".

    Regra do plano §1: `null` de oferta é *desconhecido* — nunca "não oferta".
    A flag `is_oferta_desconhecida` explica a origem da ausência, mas o texto
    da célula é sempre um dos três estados para não virar leitura de "sem oferta".
    """
    if valor is None:
        return OFERTA_DESCONHECIDA
    return "Sim" if valor else "Não"


def fmt_ano(valor: Any, motivo: str | None = None) -> str:
    """Ano de referência: `2025`, não `2.025`.

    Ano é identificador, não quantidade — separador de milhar aqui inventaria
    um número que não existe. Ausência continua "sem dado", com o motivo quando
    a base informa a flag.
    """
    if valor is None or valor == "":
        return _sem_dado(motivo)
    if isinstance(valor, bool):  # bool é subclasse de int: não é ano
        return fmt_nulo(valor)
    if isinstance(valor, (int, str)):
        return str(valor).strip() or _sem_dado(motivo)
    return str(valor)


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
    "fmt_celula",
    "fmt_contagem",
    "fmt_gap_lider",
    "fmt_nulo",
    "fmt_oferta",
]
