"""Lista versionada dos municípios de Minas Gerais — apoio de tela, sem BigQuery.

A busca por município precisa de um `select` com os 853 códigos IBGE de MG. Não
existe endpoint de localidades no contrato `serving-marts`; o arquivo
``data/municipios_mg.json`` (versionado, gerado da API de localidades do IBGE por
``scripts/gerar_municipios_mg.py``) cobre essa lacuna sem criar rota nova.

Regras:

* o código usado é o `co_municipio` de 7 dígitos do IBGE (prefixo `31`), o mesmo
  campo de `dim_geografia`/`/v1/schools`;
* a lista é **apoio de tela**: um município sem linha na `dim_geografia` cai no
  tratamento de busca sem resultado, nunca vira erro de carregamento;
* falha fechada: arquivo ausente, código fora de `^31\\d{5}$`, nome vazio ou
  código repetido interrompem a página com erro claro em vez de exibir uma
  lista silenciosamente errada.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from panorama_api.core.validation import CO_MUNICIPIO_RE

DATA_DIR = Path(__file__).resolve().parent / "data"
ARQUIVO_MUNICIPIOS = DATA_DIR / "municipios_mg.json"


def chave_ordenacao(nome: str) -> tuple[str, str]:
    """Chave de ordenação alfabética em português (ignora acento e caixa).

    Sem isso, nomes começados por vogal acentuada (``Águas Vermelhas``) iriam
    para o fim da lista de 853 municípios, depois de ``Z``.
    """
    sem_acento = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", nome)
        if not unicodedata.combining(caractere)
    )
    return (sem_acento.casefold(), nome)


@dataclass(frozen=True, slots=True)
class Municipio:
    """Município de MG como a tela precisa: código IBGE + nome de exibição."""

    co_municipio: str
    no_municipio: str


def _validar(codigo: str, nome: str) -> Municipio:
    if not CO_MUNICIPIO_RE.match(codigo):
        raise ValueError(
            f"co_municipio fora do padrão ^31\\d{{5}}$: {codigo!r} ({nome!r})"
        )
    if not nome:
        raise ValueError(f"município {codigo!r} sem nome de exibição")
    return Municipio(co_municipio=codigo, no_municipio=nome)


def normalizar(payload: object) -> tuple[Municipio, ...]:
    """Valida a resposta da API do IBGE (`id` + `nome`) e ordena por nome.

    Função pura, sem rede: é o que o script de geração usa antes de escrever o
    arquivo e o que os testes exercitam com uma carga sintética.
    """
    if not isinstance(payload, list) or not payload:
        raise ValueError("lista de municípios vazia ou com tipo inesperado")

    municipios: dict[str, Municipio] = {}
    for item in payload:
        if not isinstance(item, Mapping):
            raise ValueError(f"município com tipo inesperado: {type(item).__name__}")
        codigo = str(item.get("id", "")).strip()
        nome = str(item.get("nome", "")).strip()
        municipio = _validar(codigo, nome)
        if codigo in municipios:
            raise ValueError(f"co_municipio repetido: {codigo!r}")
        municipios[codigo] = municipio

    return tuple(sorted(municipios.values(), key=lambda m: chave_ordenacao(m.no_municipio)))


def _do_arquivo(bruto: object) -> tuple[Municipio, ...]:
    """Valida o JSON versionado (lista de `co_municipio` + `no_municipio`)."""
    if not isinstance(bruto, list) or not bruto:
        raise ValueError("arquivo de municípios vazio ou com tipo inesperado")

    municipios: dict[str, Municipio] = {}
    for item in bruto:
        if not isinstance(item, Mapping):
            raise ValueError(f"município com tipo inesperado: {type(item).__name__}")
        codigo = str(item.get("co_municipio", "")).strip()
        nome = str(item.get("no_municipio", "")).strip()
        municipio = _validar(codigo, nome)
        if codigo in municipios:
            raise ValueError(f"co_municipio repetido: {codigo!r}")
        municipios[codigo] = municipio

    return tuple(sorted(municipios.values(), key=lambda m: chave_ordenacao(m.no_municipio)))


@lru_cache
def municipios_mg() -> tuple[Municipio, ...]:
    """Municípios de MG do arquivo versionado (carregado uma vez por processo)."""
    try:
        bruto: Any = json.loads(ARQUIVO_MUNICIPIOS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # pragma: no cover - depende do arquivo
        raise RuntimeError(
            f"não foi possível ler {ARQUIVO_MUNICIPIOS}: {exc}"
        ) from exc
    try:
        return _do_arquivo(bruto)
    except ValueError as exc:  # pragma: no cover - depende do arquivo
        raise RuntimeError(f"lista de municípios inválida em {ARQUIVO_MUNICIPIOS}: {exc}") from exc


def para_json(municipios: Sequence[Municipio]) -> list[dict[str, str]]:
    """Serialização estável usada pelo script de geração."""
    return [
        {"co_municipio": municipio.co_municipio, "no_municipio": municipio.no_municipio}
        for municipio in municipios
    ]


__all__ = [
    "ARQUIVO_MUNICIPIOS",
    "DATA_DIR",
    "Municipio",
    "chave_ordenacao",
    "municipios_mg",
    "normalizar",
    "para_json",
]
