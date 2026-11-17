"""Configuração da API, sempre por variável de ambiente (AGENTS.md §6: sem paths pessoais)."""

from __future__ import annotations

import re
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from panorama_api.contract import CONTRACT_VERSION_DEFAULT

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")
_DATA_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

#: Teto provisório por consulta (decisão do gateway 2026-11-17: medição real de
#: até 86 MB; volta a 100 MB quando a clusterização entrar).
DEFAULT_MAX_BYTES_BILLED = 256 * 1024 * 1024


class Settings(BaseSettings):
    """Configuração lida do ambiente (`BQ_*`, `API_*`)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    bq_project: str = Field(default="panorama-escola-staging", alias="BQ_PROJECT")
    bq_dataset: str = Field(default="panorama_serving", alias="BQ_DATASET")
    #: BigQuery não consulta entre localizações; o dataset está em `us-central1`.
    bq_location: str = Field(default="us-central1", alias="BQ_LOCATION")
    max_bytes_billed: int = Field(
        default=DEFAULT_MAX_BYTES_BILLED, alias="API_BQ_MAX_BYTES_BILLED"
    )
    validate_schema_on_startup: bool = Field(
        default=True, alias="API_VALIDATE_SCHEMA_ON_STARTUP"
    )
    contract_version: str = Field(
        default=CONTRACT_VERSION_DEFAULT, alias="API_CONTRACT_VERSION"
    )
    #: Versão dos dados publicados (run de publicação). Entra no ETag e na chave
    #: do LRU: trocar o valor no deploy invalida o cache HTTP sem varrer nada.
    data_version: str = Field(default="dev", alias="DATA_VERSION")

    @field_validator("bq_project", "bq_dataset")
    @classmethod
    def _identifier(cls, value: str) -> str:
        # O dataset entra no texto da consulta (só nomes de tabela são permitidos);
        # valor vindo do ambiente é validado para não abrir superfície de injeção.
        if not _IDENTIFIER.match(value):
            raise ValueError(f"identificador BigQuery inválido: {value!r}")
        return value

    @field_validator("max_bytes_billed")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("API_BQ_MAX_BYTES_BILLED deve ser positivo")
        return value

    @field_validator("data_version")
    @classmethod
    def _version(cls, value: str) -> str:
        # Entra no ETag: precisa ser estável e sem caracteres de controle.
        value = value.strip()
        if not _DATA_VERSION.match(value):
            raise ValueError(
                f"DATA_VERSION inválido: {value!r} (use letras, números, '.', '_' ou '-')"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
