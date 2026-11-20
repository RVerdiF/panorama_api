"""Configuração da camada de consulta ao BigQuery (12-factor).

Projeto, dataset, região, teto de bytes e limites de paginação vêm todos de
ambiente. Os defaults refletem a decisão D2 (card ``t_63f0a522``): teto
**canônico** de 256 MB por consulta e dataset em ``us-central1``. A revisão é
gatilhada pela clusterização de ``t_cfe70dd5``: remedir o pior caso por
endpoint e fixar em max(10 MB, menor potência de 2 em MB >= 2x pior caso).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Mapping

from .errors import ConfigurationError

DEFAULT_LOCATION = "us-central1"
#: 256 MB (teto canônico da decisão D2). O pior caso medido por endpoint está
#: acima de 100 MB, então 100 MB não serve de teto; 10 MB é o mínimo faturado
#: por tabela, não um teto.
DEFAULT_MAX_BYTES_BILLED = 268_435_456
DEFAULT_TIMEOUT_S = 10.0
DEFAULT_PAGE_SIZE = 50
DEFAULT_PAGE_MAX = 500
DEFAULT_OFFSET_MAX = 1_000
DEFAULT_ROW_CAP = 1_000
DEFAULT_RATE_LIMIT = 60
DEFAULT_RATE_WINDOW_S = 60.0
DEFAULT_SERVICE_NAME = "panorama-api"
DEFAULT_DATA_VERSION = "dev"

_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DATASET_RE = re.compile(r"^[A-Za-z0-9_]{1,1024}$")
_LOCATION_RE = re.compile(r"^[a-z0-9-]{2,64}$")
_RELATION_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class BigQuerySettings:
    """Parâmetros de execução da camada, imutáveis após o startup."""

    project: str
    dataset: str
    location: str = DEFAULT_LOCATION
    max_bytes_billed: int = DEFAULT_MAX_BYTES_BILLED
    timeout_s: float = DEFAULT_TIMEOUT_S
    page_size_default: int = DEFAULT_PAGE_SIZE
    page_size_max: int = DEFAULT_PAGE_MAX
    offset_max: int = DEFAULT_OFFSET_MAX
    row_cap: int = DEFAULT_ROW_CAP
    service_name: str = DEFAULT_SERVICE_NAME
    data_version: str = DEFAULT_DATA_VERSION

    def __post_init__(self) -> None:
        if not _PROJECT_RE.match(self.project or ""):
            raise ConfigurationError("GCP_PROJECT ausente ou inválido")
        if not _DATASET_RE.match(self.dataset or ""):
            raise ConfigurationError(
                "BQ_SERVING_DATASET ausente ou inválido (use apenas letras, números e _)"
            )
        if not _LOCATION_RE.match(self.location or ""):
            raise ConfigurationError("BQ_LOCATION ausente ou inválido")
        if isinstance(self.max_bytes_billed, bool) or self.max_bytes_billed <= 0:
            raise ConfigurationError("BQ_MAX_BYTES_BILLED deve ser inteiro positivo")
        if not 0 < self.timeout_s <= 300:
            raise ConfigurationError("BQ_TIMEOUT_S deve estar entre 0 e 300 segundos")
        if self.page_size_default <= 0:
            raise ConfigurationError("API_PAGE_DEFAULT deve ser positivo")
        if self.page_size_max < self.page_size_default:
            raise ConfigurationError("API_PAGE_MAX não pode ser menor que API_PAGE_DEFAULT")
        if self.offset_max < 0:
            raise ConfigurationError("API_OFFSET_MAX não pode ser negativo")
        if self.row_cap <= 0:
            raise ConfigurationError("API_ROW_CAP deve ser positivo")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "BigQuerySettings":
        """Monta a configuração a partir do ambiente, falhando fechado."""
        source = os.environ if env is None else env
        project = _first(source, "GCP_PROJECT", "GOOGLE_CLOUD_PROJECT")
        dataset = _first(source, "BQ_SERVING_DATASET", "BQ_DATASET")
        return cls(
            project=project,
            dataset=dataset,
            location=_first(source, "BQ_LOCATION") or DEFAULT_LOCATION,
            max_bytes_billed=_int_env(source, "BQ_MAX_BYTES_BILLED", DEFAULT_MAX_BYTES_BILLED),
            timeout_s=_float_env(source, "BQ_TIMEOUT_S", DEFAULT_TIMEOUT_S),
            page_size_default=_int_env(source, "API_PAGE_DEFAULT", DEFAULT_PAGE_SIZE),
            page_size_max=_int_env(source, "API_PAGE_MAX", DEFAULT_PAGE_MAX),
            offset_max=_int_env(source, "API_OFFSET_MAX", DEFAULT_OFFSET_MAX),
            row_cap=_int_env(source, "API_ROW_CAP", DEFAULT_ROW_CAP),
            service_name=_first(source, "SERVICE_NAME") or DEFAULT_SERVICE_NAME,
            data_version=_first(source, "DATA_VERSION") or DEFAULT_DATA_VERSION,
        )

    def render_relation(self, relation: str) -> str:
        """Expande ``{dataset}`` numa relação fixa do template.

        Só o nome do dataset (validado) é interpolado; o restante da relação é
        constante de código.
        """
        if "{" not in relation:
            return relation
        if relation.count("{dataset}") != relation.count("{"):
            raise ConfigurationError(f"relação com placeholder desconhecido: {relation!r}")
        rendered = relation.format(dataset=self.dataset)
        if "{" in rendered or "}" in rendered:
            raise ConfigurationError(f"relação malformada: {relation!r}")
        return rendered

    def render_table(self, table: str) -> str:
        """Qualifica uma tabela simples do allowlist."""
        if not _RELATION_RE.match(table or ""):
            raise ConfigurationError(f"nome de tabela inválido: {table!r}")
        return f"{self.dataset}.{table}"


def _first(env: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = env.get(name)
        if value is not None and value.strip():
            return value.strip()
    return ""


def _int_env(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ConfigurationError(f"{name} deve ser inteiro, recebido {raw!r}") from exc


def _float_env(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise ConfigurationError(f"{name} deve ser numérico, recebido {raw!r}") from exc
