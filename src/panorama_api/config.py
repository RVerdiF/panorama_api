"""Configuração da API, sempre por variável de ambiente (AGENTS.md §6: sem paths pessoais)."""

from __future__ import annotations

import re
from functools import lru_cache

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from panorama_api.contract import CONTRACT_VERSION_DEFAULT
from panorama_api.core.validation import ANO_MAX, ANO_MIN

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")
#: Vocabulário aceito para as versões que entram em `ETag`/chave de cache.
_VERSAO = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
#: Ano do seletor do front: 4 dígitos ASCII (o `\d` do Python aceita dígitos
#: Unicode, que `int()` recusa e deixariam escapar `ValueError` no boot).
_ANO = re.compile(r"^[0-9]{4}$")

#: Teto canônico por consulta (decisão D2, card `t_63f0a522`): 256 MB, via
#: `API_BQ_MAX_BYTES_BILLED`. 100 MB ficou abaixo do pior caso medido (ver a
#: tabela de custo por consulta em `docs/api-v1.md`). Revisão gatilhada pela
#: clusterização de `t_cfe70dd5`: remedir o pior caso por endpoint e fixar em
#: max(10 MB, menor potência de 2 em MB >= 2x pior caso). Até lá, 256 MB.
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
    #: Versão do código do front (`/app`). Entra no `ETag` das páginas porque o
    #: HTML muda a cada deploy mesmo sem dado novo (plano §5, card F2). Tem o
    #: mesmo vocabulário de `DATA_VERSION` e também falha fechada no boot.
    app_build: str = Field(default="dev", alias="APP_BUILD")
    #: Anos do seletor das telas de mercado (card F5), em CSV — ex.
    #: `2021,2022,2023,2024,2025`. Obrigatório: o front não inventa recorte de
    #: ano, e um deploy sem esta variável falha no boot (mesma política de
    #: `DATA_VERSION`, plano §5). Só anos do contrato (`ANO_MIN..ANO_MAX`), sem
    #: repetição; guardado canonicamente (crescente, sem espaço).
    app_anos_disponiveis: str = Field(alias="APP_ANOS_DISPONIVEIS")

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

    @field_validator("data_version", "app_build")
    @classmethod
    def _version(cls, value: str, info: ValidationInfo) -> str:
        # Entram no ETag: precisam ser estáveis e sem caracteres de controle.
        campo = (info.field_name or "versão").upper()
        value = value.strip()
        if not _VERSAO.match(value):
            raise ValueError(
                f"{campo} inválido: {value!r} (use letras, números, '.', '_' ou '-')"
            )
        return value

    @field_validator("app_anos_disponiveis")
    @classmethod
    def _anos_disponiveis(cls, value: str) -> str:
        """Valida o CSV do seletor de ano e o guarda canonicamente.

        Falha fechada no boot (mesma política de `DATA_VERSION`): vazio, item
        não numérico, ano fora de `ANO_MIN..ANO_MAX` ou repetido levantam. A
        saída é crescente e sem espaço, para que o valor do manifesto seja
        também a forma exibida.
        """
        brutos = [item.strip() for item in value.split(",")]
        if not brutos or any(not item for item in brutos):
            raise ValueError(
                f"APP_ANOS_DISPONIVEIS inválido: {value!r} "
                "(use anos de 4 dígitos separados por vírgula, ex. 2021,2022)"
            )
        anos: list[int] = []
        for item in brutos:
            if not _ANO.match(item):
                raise ValueError(f"APP_ANOS_DISPONIVEIS inválido: {item!r} não é um ano")
            ano = int(item)
            if not ANO_MIN <= ano <= ANO_MAX:
                raise ValueError(
                    f"APP_ANOS_DISPONIVEIS inválido: {ano} fora de {ANO_MIN}..{ANO_MAX}"
                )
            if ano in anos:
                raise ValueError(f"APP_ANOS_DISPONIVEIS inválido: ano repetido {ano}")
            anos.append(ano)
        return ",".join(str(ano) for ano in sorted(anos))

    @property
    def anos_disponiveis(self) -> tuple[int, ...]:
        """Anos do seletor do front, crescentes (validados no boot)."""
        return tuple(int(ano) for ano in self.app_anos_disponiveis.split(","))


@lru_cache
def get_settings() -> Settings:
    return Settings()
