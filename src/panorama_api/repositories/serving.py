"""Contrato do repositório de serving (implementado pelo BQ; substituído por fake nos testes)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ServingRepository(Protocol):
    """Leituras da v1. Devolve linhas cruas (`dict` coluna→valor, NULL = None)."""

    def search_schools(
        self,
        *,
        q: str | None,
        co_entidade: str | None,
        co_municipio: str | None,
        tp_dependencia: str | None,
        apenas_ativas: bool,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]: ...

    def get_school(self, co_entidade: str) -> dict[str, Any] | None: ...

    def get_school_history(
        self, *, co_entidade: str, ano_inicio: int | None, ano_fim: int | None
    ) -> list[dict[str, Any]]: ...

    def get_school_indicators(
        self, *, co_entidade: str, ano: int | None
    ) -> list[dict[str, Any]]: ...

    def get_school_competidores(self, *, co_entidade: str) -> list[dict[str, Any]]: ...

    def get_municipio(self, co_municipio: str) -> dict[str, Any] | None: ...

    def get_market(
        self, *, co_municipio: str, ano: int, etapa: str | None
    ) -> list[dict[str, Any]]: ...

    def get_concentracao(
        self, *, co_municipio: str, ano: int, etapa: str | None
    ) -> list[dict[str, Any]]: ...

    def get_market_share(
        self,
        *,
        co_municipio: str,
        ano: int,
        etapa: str,
        entidade_tipo: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]: ...

    def get_table_columns(self) -> dict[str, dict[str, str]]:
        """{tabela: {coluna: tipo}} das views do contrato (validação de startup)."""
        ...
