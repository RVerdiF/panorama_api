#!/usr/bin/env python3
"""Dry-run de todos os templates contra o serving: valida SQL e mede custo.

Custo zero (``dry_run=True`` não fatura). Falha (exit 1) se algum template
estourar ``BQ_MAX_BYTES_BILLED`` — é o mesmo teto aplicado em produção.

Uso::

    GCP_PROJECT=panorama-escola-staging \
    BQ_SERVING_DATASET=panorama_serving \
    BQ_LOCATION=us-central1 \
    .venv/bin/python scripts/dry_run_templates.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from google.cloud import bigquery  # noqa: E402

from panorama_api.repositories.bigquery import (  # noqa: E402
    BigQuerySettings,
    GoogleBigQueryClient,
    PageRequest,
    QueryExecutor,
)
from panorama_api.repositories.bigquery.templates import TEMPLATES  # noqa: E402

#: Filtros representativos por template (mesmos recortes da medição de 2026-11-17).
SAMPLES: dict[str, dict[str, object]] = {
    "schools": {"co_municipio": "3106200"},
    "school": {"co_entidade": "31000000"},
    "school_history": {"co_entidade": "31000000"},
    "school_indicators": {"co_entidade": "31000000"},
    "market": {"co_municipio": "3106200", "nu_ano_censo": 2024},
    "market_share": {"co_municipio": "3106200", "nu_ano_censo": 2024, "etapa": "fund_ai"},
    "market_concentration": {
        "co_municipio": "3106200",
        "nu_ano_censo": 2024,
        "etapa": "fund_ai",
    },
}


class DryRunClient:
    """Executa dry-run e guarda ``total_bytes_processed`` por endpoint."""

    def __init__(self, settings: BigQuerySettings) -> None:
        self._settings = settings
        self._bq = bigquery.Client(project=settings.project, location=settings.location)
        self._configs = GoogleBigQueryClient(settings, client=self._bq)
        self.bytes_processed: dict[str, int] = {}

    def run_query(self, *, sql, endpoint, parameters, timeout_s):  # noqa: ANN001
        config = self._configs.build_job_config(endpoint=endpoint, parameters=parameters)
        config.dry_run = True
        job = self._bq.query(sql, job_config=config)
        self.bytes_processed[endpoint] = int(job.total_bytes_processed or 0)
        return []


def main() -> int:
    env = dict(os.environ)
    settings = BigQuerySettings.from_env(env)
    client = DryRunClient(settings)
    executor = QueryExecutor(settings=settings, client=client)

    print(
        f"projeto={settings.project} dataset={settings.dataset} "
        f"location={settings.location} teto={settings.max_bytes_billed} bytes"
    )
    print(f"{'template':<22}{'bytes':>14}{'MB':>8}  status")

    failures: list[str] = []
    for name in sorted(TEMPLATES):
        try:
            executor.execute(name, SAMPLES[name], PageRequest())
        except Exception as exc:  # noqa: BLE001 - relatório precisa seguir
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"{name:<22}{'-':>14}{'-':>8}  ERRO: {type(exc).__name__}: {exc}")
            continue
        measured = client.bytes_processed.get(name, 0)
        status = "ok" if measured <= settings.max_bytes_billed else "ACIMA DO TETO"
        if status != "ok":
            failures.append(f"{name}: {measured} bytes > teto {settings.max_bytes_billed}")
        print(f"{name:<22}{measured:>14}{measured / 1e6:>8.1f}  {status}")

    if failures:
        print("\nFALHAS:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
