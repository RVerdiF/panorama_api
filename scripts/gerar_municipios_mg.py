#!/usr/bin/env python3
"""Gera `src/panorama_api/web/data/municipios_mg.json` a partir do IBGE.

Fonte: API de localidades do IBGE
(``/api/v1/localidades/estados/31/municipios`` — Minas Gerais). O arquivo é
**apoio de tela** da busca por município (card F3): não substitui `dim_geografia`
e não cria endpoint no `/v1`.

Uso::

    .venv/bin/python scripts/gerar_municipios_mg.py
    .venv/bin/python scripts/gerar_municipios_mg.py --url <url> --saida <arquivo>

Falha fechada: se a resposta não vier no formato esperado, se algum código não
casar ``^31\\d{5}$`` ou se o total não for o esperado, o arquivo **não** é
escrito e o script sai com código 1.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from panorama_api.web.municipios import (  # noqa: E402
    ARQUIVO_MUNICIPIOS,
    Municipio,
    normalizar,
    para_json,
)

URL_IBGE = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/31/municipios"
#: MG tem 853 municípios (IBGE). Divergência é mudança na fonte, não no script:
#: falha em vez de publicar uma lista diferente sem revisão.
TOTAL_ESPERADO = 853


def baixar(url: str, *, timeout: float = 30.0) -> object:
    with urllib.request.urlopen(url, timeout=timeout) as resposta:  # noqa: S310
        return json.loads(resposta.read().decode("utf-8"))


def gerar(payload: object, destino: Path) -> tuple[Municipio, ...]:
    municipios = normalizar(payload)
    if len(municipios) != TOTAL_ESPERADO:
        raise ValueError(
            f"esperados {TOTAL_ESPERADO} municípios de MG, recebidos {len(municipios)}"
        )
    destino.parent.mkdir(parents=True, exist_ok=True)
    conteudo = json.dumps(para_json(municipios), ensure_ascii=False, indent=2) + "\n"
    destino.write_text(conteudo, encoding="utf-8")
    return municipios


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Gera a lista versionada de municípios de MG (853, códigos IBGE "
            "^31\\d{5}$) a partir da API de localidades do IBGE."
        )
    )
    parser.add_argument(
        "--url",
        default=URL_IBGE,
        help=f"URL da API de localidades do IBGE (default: {URL_IBGE})",
    )
    parser.add_argument(
        "--saida",
        type=Path,
        default=ARQUIVO_MUNICIPIOS,
        help=f"arquivo de saída (default: {ARQUIVO_MUNICIPIOS})",
    )
    args = parser.parse_args(argv)

    try:
        municipios = gerar(baixar(args.url), args.saida)
    except Exception as exc:  # noqa: BLE001 - falha fechada com mensagem clara
        print(f"erro: {exc}", file=sys.stderr)
        return 1

    print(f"{len(municipios)} municípios de MG escritos em {args.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
