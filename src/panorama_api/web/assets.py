"""Assets estáticos versionados por hash de conteúdo.

Cada arquivo de `static/` é lido uma vez no boot e publicado como
``/app/static/<hash>-<nome>``. Como a URL muda quando o conteúdo muda, ela pode
ser servida com ``Cache-Control: public, max-age=31536000, immutable`` — o
navegador nunca precisa revalidar e um deploy de código gera URL nova.

O hash também é verificado no handler: uma URL com hash errado dá 404 em vez de
servir bytes que não correspondem ao nome público.

Referência entre assets (`{{asset:<nome>}}` e `../fonts/<nome>`)
-------------------------------------------------------------
O `@font-face` do `app.css` precisa apontar para a URL **com hash** da fonte, e
essa URL só existe depois que o conteúdo da fonte é lido. Em vez de duplicar a
lógica de hash no CSS, o CSS declara a referência lógica::

    src: url("{{asset:inter-400.woff2}}") format("woff2");

O CSS vendorizado do protótipo (`static/prototipo/`) NÃO pode ser editado
(contrato byte a byte, D1-a): as referências relativas que ele já declara::

    src: url("../fonts/inter-400.woff2") format("woff2");

são resolvidas pelo registro da mesma forma, virando a URL pública com hash
da fonte. O arquivo no disco segue intacto (`cmp` limpo); só os bytes
servidos carregam a URL final — o mesmo padrão do `{{asset:}}`.

O registro varre `static/` (inclusive subdiretórios, como `static/fonts/`),
publica tudo num espaço de nomes plano — o nome público é o nome do arquivo — e
substitui cada referência pela URL final. O digest do CSS é calculado **depois**
da substituição, então a URL do CSS corresponde aos bytes servidos e o ciclo
`css → fonte` continua imutável e auditável. Referência para asset inexistente
falha no boot (`KeyError`), nunca no navegador: nada de `url()` quebrada em
produção.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

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

#: Tipos em que a referência `{{asset:...}}` é resolvida (texto, não binário).
_TEXTUAL_SUFFIXES = frozenset({".css", ".js", ".svg"})

#: `{{asset:<nome>}}` — nome publicado, nunca caminho no disco.
_REFERENCIA = re.compile(r"\{\{asset:([A-Za-z0-9._-]+)\}\}")

#: `../fonts/<nome>` — referência relativa do CSS vendorizado do protótipo
#: (`static/prototipo/`), que NÃO pode ser editado (D1-a). Resolve para a
#: mesma URL pública com hash; o arquivo no disco segue intacto.
_REFERENCIA_RELATIVA_FONTE = re.compile(r"\.\./fonts/([A-Za-z0-9._-]+)")


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


def _arquivos(diretorio: Path) -> Iterable[Path]:
    """Todo arquivo de `static/`, em ordem estável e recursiva."""
    return sorted(caminho for caminho in diretorio.rglob("*") if caminho.is_file())


def _digest(corpo: bytes) -> str:
    return hashlib.sha256(corpo).hexdigest()[:_DIGEST_LEN]


class AssetRegistry:
    """Registro imutável dos assets do front, carregado do diretório `static/`."""

    def __init__(self, diretorio: str | Path, *, prefixo: str) -> None:
        self._prefixo = prefixo.rstrip("/")
        brutos: dict[str, tuple[bytes, str]] = {}
        for arquivo in _arquivos(Path(diretorio)):
            if arquivo.name in brutos:
                # O espaço público é plano (`/static/<hash>-<nome>`): dois
                # arquivos com o mesmo nome em subdiretórios diferentes
                # colidiriam na URL. Falha no boot, não na navegação.
                raise ValueError(f"asset com nome duplicado em static/: {arquivo.name!r}")
            brutos[arquivo.name] = (
                arquivo.read_bytes(),
                MEDIA_TYPES.get(arquivo.suffix, "application/octet-stream"),
            )

        self._por_caminho: dict[str, Asset] = {}
        for nome, (corpo, media_type) in brutos.items():
            self._por_caminho[f"{_digest(corpo)}-{nome}"] = Asset(
                nome=nome, digest=_digest(corpo), corpo=corpo, media_type=media_type
            )

        # Segunda passada: resolve `{{asset:...}}` nos assets textuais. Os
        # binários já estão finais, então o mapa de nomes está completo.
        for nome, (corpo, media_type) in brutos.items():
            if Path(nome).suffix not in _TEXTUAL_SUFFIXES:
                continue
            resolvido = self._resolver_referencias(corpo, nome)
            if resolvido == corpo:
                continue
            self._por_caminho.pop(f"{_digest(corpo)}-{nome}", None)
            self._por_caminho[f"{_digest(resolvido)}-{nome}"] = Asset(
                nome=nome, digest=_digest(resolvido), corpo=resolvido, media_type=media_type
            )

    def _resolver_referencias(self, corpo: bytes, dono: str) -> bytes:
        texto = corpo.decode("utf-8")
        faltando: list[str] = []

        def troca(achado: re.Match[str]) -> str:
            nome = achado.group(1)
            try:
                return self.url(nome)
            except KeyError:
                faltando.append(nome)
                return achado.group(0)

        resolvido = _REFERENCIA.sub(troca, texto)
        # O CSS vendorizado declara `../fonts/<nome>` (relativo à posição do
        # stylesheet no disco); servido sob `/app/static/`, esse relativo
        # quebraria — resolve para a URL com hash, sem tocar no arquivo.
        resolvido = _REFERENCIA_RELATIVA_FONTE.sub(troca, resolvido)
        if faltando:
            raise KeyError(f"{dono} referencia asset inexistente: {sorted(set(faltando))!r}")
        return resolvido.encode("utf-8")

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
