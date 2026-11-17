"""Parâmetros de consulta: tipos, normalização e validação de domínio.

Regra dura do card ``t_ea2c4d84``: nenhum valor de usuário entra no texto do
SQL. Todo valor vira ``ScalarQueryParameter`` tipado (STRING/INT64/BOOL) e o
SQL referencia apenas ``@nome``. Este módulo concentra o contrato de tipo e as
validações de formato, para que a montagem do SQL nunca precise confiar no
chamador.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from .errors import InvalidQueryRequest

#: Domínio fechado de etapas do censo (9 etapas servidas pelos marts).
ETAPAS: frozenset[str] = frozenset(
    {"bas", "creche", "pre", "fund_ai", "fund_af", "med", "prof", "eja", "esp"}
)
ENTIDADE_TIPOS: frozenset[str] = frozenset({"escola", "mantenedora"})

ANO_MIN, ANO_MAX = 2000, 2100

PARAM_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_CO_ENTIDADE_RE = re.compile(r"^\d{8}$")
_CO_MUNICIPIO_RE = re.compile(r"^31\d{5}$")
_INT_RE = re.compile(r"^-?\d{1,9}$")


class ParamType(str, Enum):
    """Tipos escalares aceitos; espelham os tipos verificados no serving."""

    STRING = "STRING"
    INT64 = "INT64"
    BOOL = "BOOL"


@dataclass(frozen=True, slots=True)
class ParamSpec:
    """Especificação de um parâmetro: tipo no BigQuery + validação de domínio."""

    name: str
    type: ParamType
    check: Callable[[Any], Any] | None = None

    def __post_init__(self) -> None:
        if not PARAM_NAME_RE.match(self.name):
            raise ValueError(f"nome de parâmetro inválido: {self.name!r}")

    def normalize(self, value: Any) -> Any:
        """Converte e valida um valor vindo da borda; nunca retorna lixo."""
        coerced = _coerce(self.name, self.type, value)
        if self.check is None:
            return coerced
        try:
            return self.check(coerced)
        except ValueError as exc:
            raise InvalidQueryRequest(str(exc), field=self.name) from exc


def _coerce(name: str, param_type: ParamType, value: Any) -> Any:
    if value is None:
        raise InvalidQueryRequest(f"parâmetro '{name}' não pode ser nulo", field=name)
    if param_type is ParamType.INT64:
        if isinstance(value, bool):
            raise InvalidQueryRequest(f"parâmetro '{name}' deve ser inteiro", field=name)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and _INT_RE.match(value.strip()):
            return int(value.strip())
        raise InvalidQueryRequest(f"parâmetro '{name}' deve ser inteiro", field=name)
    if param_type is ParamType.BOOL:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            return value.strip().lower() == "true"
        raise InvalidQueryRequest(f"parâmetro '{name}' deve ser booleano", field=name)
    # STRING
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise InvalidQueryRequest(f"parâmetro '{name}' deve ser texto", field=name)
    return str(value).strip()


def check_co_entidade(value: str) -> str:
    if not _CO_ENTIDADE_RE.match(value):
        raise ValueError("co_entidade deve ter exatamente 8 dígitos numéricos")
    return value


def check_co_municipio(value: str) -> str:
    if not _CO_MUNICIPIO_RE.match(value):
        raise ValueError("co_municipio deve ter 7 dígitos e começar com 31 (MG)")
    return value


def check_ano(value: int) -> int:
    if not ANO_MIN <= value <= ANO_MAX:
        raise ValueError(f"ano deve estar entre {ANO_MIN} e {ANO_MAX}")
    return value


def check_etapa(value: str) -> str:
    if value not in ETAPAS:
        raise ValueError(f"etapa deve ser uma de {sorted(ETAPAS)}")
    return value


def check_entidade_tipo(value: str) -> str:
    if value not in ENTIDADE_TIPOS:
        raise ValueError(f"entidade_tipo deve ser uma de {sorted(ENTIDADE_TIPOS)}")
    return value


def check_prefixo_busca(value: str) -> str:
    if not 3 <= len(value) <= 100:
        raise ValueError("q deve ter entre 3 e 100 caracteres")
    return value.upper()


# --- specs reutilizados pelos templates -------------------------------------

CO_ENTIDADE = ParamSpec("co_entidade", ParamType.STRING, check_co_entidade)
CO_MUNICIPIO = ParamSpec("co_municipio", ParamType.STRING, check_co_municipio)
ANO_CENSO = ParamSpec("nu_ano_censo", ParamType.INT64, check_ano)
ETAPA = ParamSpec("etapa", ParamType.STRING, check_etapa)
ENTIDADE_TIPO = ParamSpec("entidade_tipo", ParamType.STRING, check_entidade_tipo)
PREFIXO_BUSCA = ParamSpec("no_entidade_prefix", ParamType.STRING, check_prefixo_busca)
ANO_INICIO = ParamSpec("ano_inicio", ParamType.INT64, check_ano)
ANO_FIM = ParamSpec("ano_fim", ParamType.INT64, check_ano)
