"""Validação do schema do serving no startup (falha fechada — B1)."""

from __future__ import annotations

from panorama_api.repositories.expected_schema import EXPECTED_COLUMNS
from panorama_api.repositories.serving import ServingRepository


class SchemaValidationError(RuntimeError):
    """O dataset não corresponde ao contrato mvp-1: a API não deve subir."""


def validate_schema(repository: ServingRepository) -> None:
    """Confere nome + tipo das colunas usadas pela API e levanta se divergir."""
    actual = repository.get_table_columns()
    problems: list[str] = []

    for table, expected in EXPECTED_COLUMNS.items():
        columns = actual.get(table)
        if columns is None:
            problems.append(f"tabela ausente no dataset: {table}")
            continue
        for column, expected_type in expected.items():
            if column not in columns:
                problems.append(f"{table}.{column}: coluna ausente")
            elif columns[column] != expected_type:
                problems.append(
                    f"{table}.{column}: tipo {columns[column]!r} != esperado {expected_type!r}"
                )

    if problems:
        raise SchemaValidationError(
            "schema do serving incompatível com o contrato mvp-1: " + "; ".join(problems)
        )
