"""Cliente BigQuery: única fronteira que fala com o SDK do Google.

O resto da camada trabalha com ``QueryClient`` (protocolo) e com parâmetros
``(nome, tipo, valor)``. Aqui ficam: criação preguiçosa do client com
``location`` explícito, montagem do ``QueryJobConfig`` (teto de bytes, labels e
timeout) e tradução de falhas do SDK em erros de domínio.
"""

from __future__ import annotations

import re
import threading
from typing import TYPE_CHECKING, Any, Mapping, Protocol, Sequence

from .config import BigQuerySettings
from .errors import BytesBudgetExceeded, QueryExecutionError, QueryTimeout
from .parameters import ParamType

if TYPE_CHECKING:  # pragma: no cover - apenas tipagem
    from google.cloud import bigquery

_LABEL_INVALID_RE = re.compile(r"[^a-z0-9_-]")
LABEL_MAX_LEN = 63


class QueryClient(Protocol):
    """Contrato mínimo consumido pelo executor (facilita teste hermético)."""

    def run_query(
        self,
        *,
        sql: str,
        endpoint: str,
        parameters: Sequence[tuple[str, ParamType, Any]],
        timeout_s: float,
    ) -> list[Mapping[str, Any]]:
        ...


def sanitize_label(value: str, *, fallback: str = "unknown") -> str:
    """Normaliza um valor de label do BigQuery (``[a-z0-9_-]``, até 63)."""
    text = _LABEL_INVALID_RE.sub("_", (value or "").strip().lower())
    text = text.strip("_-")[:LABEL_MAX_LEN]
    if not text:
        text = fallback
    if not text[0].isalpha():
        text = f"v_{text}"[:LABEL_MAX_LEN]
    return text


class GoogleBigQueryClient:
    """Implementação real; o client é criado no primeiro uso (ADC, sem chave)."""

    def __init__(self, settings: BigQuerySettings, *, client: "bigquery.Client | None" = None) -> None:
        self._settings = settings
        self._client = client
        self._lock = threading.Lock()

    @property
    def settings(self) -> BigQuerySettings:
        return self._settings

    def _get_client(self) -> "bigquery.Client":
        with self._lock:
            if self._client is None:
                from google.cloud import bigquery

                # Sem project explícito em produção? Usa o do ambiente/ADC.
                self._client = bigquery.Client(
                    project=self._settings.project,
                    location=self._settings.location,
                )
            return self._client

    def build_job_config(
        self,
        *,
        endpoint: str,
        parameters: Sequence[tuple[str, ParamType, Any]],
    ) -> "bigquery.QueryJobConfig":
        """Config de todo job: parâmetros tipados, teto de bytes, labels, timeout."""
        from google.cloud import bigquery

        query_parameters = [
            bigquery.ScalarQueryParameter(name, param_type.value, value)
            for name, param_type, value in parameters
        ]
        job_config = bigquery.QueryJobConfig(query_parameters=query_parameters)
        job_config.maximum_bytes_billed = self._settings.max_bytes_billed
        job_config.use_query_cache = True
        job_config.job_timeout_ms = int(self._settings.timeout_s * 1000)
        job_config.labels = {
            "service": sanitize_label(self._settings.service_name),
            "endpoint": sanitize_label(endpoint),
            "data_version": sanitize_label(self._settings.data_version),
        }
        return job_config

    def run_query(
        self,
        *,
        sql: str,
        endpoint: str,
        parameters: Sequence[tuple[str, ParamType, Any]],
        timeout_s: float,
    ) -> list[Mapping[str, Any]]:
        from google.api_core.exceptions import BadRequest, GoogleAPIError

        job_config = self.build_job_config(endpoint=endpoint, parameters=parameters)
        try:
            job = self._get_client().query(sql, job_config=job_config, timeout=timeout_s)
            rows = job.result(timeout=timeout_s)
        except TimeoutError as exc:
            raise QueryTimeout("consulta excedeu o tempo limite no BigQuery") from exc
        except BadRequest as exc:
            message = str(exc)
            if "bytesBilledLimitExceeded" in message or "bytes billed" in message.lower():
                raise BytesBudgetExceeded(
                    "consulta excedeu o teto de bytes faturados configurado"
                ) from exc
            raise QueryExecutionError("BigQuery rejeitou a consulta") from exc
        except GoogleAPIError as exc:
            raise QueryExecutionError("BigQuery indisponível no momento") from exc

        return [_row_to_mapping(row) for row in rows]


def _row_to_mapping(row: Any) -> Mapping[str, Any]:
    """Converte ``Row`` (ou mapping de teste) em dict, preservando ``None``."""
    items = getattr(row, "items", None)
    if callable(items):
        return dict(items())
    return dict(row)  # ``Row`` expõe ``keys()``/``__getitem__``
