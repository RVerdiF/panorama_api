"""Assets estáticos versionados por hash de conteúdo.

Cada arquivo de `static/` é lido uma vez no boot e publicado como
``/app/static/<hash>-<nome>``. Como a URL muda quando o conteúdo muda, ela pode
ser servida com ``Cache-Control: public, max-age=31536000, immutable`` — o
navegador nunca precisa revalidar e um deploy de código gera URL nova.

O hash também é verificado no handler: uma URL com hash errado dá 404 em vez de
servir bytes que não correspondem ao nome público.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

MEDIA_TYPES: Mapping[str, str] = {
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".js": "text/javascript; charset=utf-8",
}

#: Asset imutável: o nome carrega o hash do conteúdo.
CACHE_CONTROL_ASSET = "public, max-age=31536000, immutable"

_DIGEST_LEN = 12


@dataclass(frozen=True, slots=True)
class Asset:
    """Asset carregado em memória, com o nome público já resolvido."""

    nome: str
    digest: str
    corpo: bytes
    media_type: str

    @property
    def caminho_publico(self) -> str:
        return f"{self.digest}-{self.nome}"


class AssetRegistry:
    """Registro imutável dos assets do front, carregado do diretório `static/`."""

    def __init__(self, diretorio: str | Path, *, prefixo: str) -> None:
        self._prefixo = prefixo.rstrip("/")
        self._por_caminho: dict[str, Asset] = {}
        for arquivo in sorted(Path(diretorio).iterdir()):
            if not arquivo.is_file():
                continue
            corpo = arquivo.read_bytes()
            digest = hashlib.sha256(corpo).hexdigest()[:_DIGEST_LEN]
            asset = Asset(
                nome=arquivo.name,
                digest=digest,
                corpo=corpo,
                media_type=MEDIA_TYPES.get(arquivo.suffix, "application/octet-stream"),
            )
            self._por_caminho[asset.caminho_publico] = asset

    def url(self, nome: str) -> str:
        """URL pública (com hash) de um asset; falha fechada se ele não existe."""
        for asset in self._por_caminho.values():
            if asset.nome == nome:
                return f"{self._prefixo}/static/{asset.caminho_publico}"
        raise KeyError(f"asset desconhecido: {nome!r}")

    def get(self, caminho: str) -> Asset | None:
        return self._por_caminho.get(caminho)

    @property
    def nomes(self) -> tuple[str, ...]:
        return tuple(asset.nome for asset in self._por_caminho.values())


__all__ = ["CACHE_CONTROL_ASSET", "Asset", "AssetRegistry", "MEDIA_TYPES"]
