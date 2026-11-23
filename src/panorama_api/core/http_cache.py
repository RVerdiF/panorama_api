"""Cache HTTP e LRU em memória das respostas `GET` de `/v1/*` e das páginas `/app`.

Decisão do card ``t_817a670c`` (2026-11-17) para o `/v1`:

* ``Cache-Control: public, max-age=86400, stale-while-revalidate=604800``;
* ``ETag`` = hash de ``DATA_VERSION`` + caminho + query canônica — trocar a
  versão dos dados invalida tudo sem precisar varrer o cache;
* LRU em memória com 1000 entradas (sem Redis; cada instância tem a sua);
* erro **nunca** é cacheado nem recebe ``ETag``/``Cache-Control``.

O card ``t_68bd7615`` (F2) reaproveita exatamente a mesma mecânica para as
páginas SSR sob ``/app``, mudando só a política: ``ETag`` inclui também
``APP_BUILD`` (o HTML muda a cada deploy de código) e ``Cache-Control`` é
``private, no-cache`` — o navegador revalida sempre e quem responde é o 304, que
é decidido pelo hash antes do handler, sem tocar no repositório/BigQuery.

O cache guarda o corpo já serializado (JSON ou HTML), então um *hit* não chama o
repositório nem o BigQuery.
"""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Iterable, cast

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

logger = logging.getLogger(__name__)

#: Decisão do card 2d.3: 1 dia de frescor + 7 dias de revalidação em background.
CACHE_CONTROL = "public, max-age=86400, stale-while-revalidate=604800"
#: Páginas `/app` (card F2): o HTML depende do deploy, então o navegador
#: revalida sempre. Quem evita o trabalho é o 304 por `ETag`, decidido antes do
#: handler — `no-cache` não significa "não guardar", significa "revalidar antes
#: de usar". `private` porque a resposta é por usuário/piloto (IAP), não CDN.
CACHE_CONTROL_PAGINA = "private, no-cache"
DEFAULT_MAX_ENTRIES = 1000

_CACHEABLE_METHOD = "GET"
_CACHEABLE_PATH_PREFIX = "/v1/"
_CACHEABLE_STATUS = 200
#: Cabeçalhos que o endpoint pode usar para vetar o cache da própria resposta.
_FORBIDDEN_CACHE_CONTROL = ("no-store", "private")
#: Nas páginas o único veto aceito é `no-store`: `private, no-cache` é a própria
#: política do middleware e não pode ser lida como "não cachear".
_FORBIDDEN_CACHE_CONTROL_PAGINA = ("no-store",)


@dataclass(frozen=True, slots=True)
class CachedResponse:
    """Resposta pronta para ser devolvida sem tocar no repositório."""

    body: bytes
    media_type: str


class LruCache:
    """LRU de tamanho fixo, seguro para uso concorrente.

    A ordenação é a de inserção/uso (`OrderedDict.move_to_end`); ao passar do
    teto, a entrada menos recentemente usada é descartada. A chave já contém a
    `DATA_VERSION`, então a invalidação por versão é automática: as entradas da
    versão antiga deixam de ser consultadas e saem pela própria política LRU.
    """

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        if isinstance(max_entries, bool) or not isinstance(max_entries, int):
            raise TypeError("max_entries deve ser inteiro")
        if max_entries <= 0:
            raise ValueError("max_entries deve ser positivo")
        self._max_entries = max_entries
        self._entries: OrderedDict[str, CachedResponse] = OrderedDict()
        self._lock = Lock()

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def get(self, key: str) -> CachedResponse | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return entry

    def put(self, key: str, entry: CachedResponse) -> None:
        with self._lock:
            self._entries[key] = entry
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self._entries


def canonical_query(query: Iterable[tuple[str, str]]) -> str:
    """Ordena os pares da query string para que a ordem não mude a chave."""
    return "&".join(f"{name}={value}" for name, value in sorted(query))


def cache_key(
    data_version: str,
    path: str,
    query: Iterable[tuple[str, str]],
    *,
    app_build: str | None = None,
) -> str:
    """Chave canônica: ``DATA_VERSION`` (+ ``APP_BUILD``) + caminho + query.

    ``app_build=None`` reproduz exatamente a chave do `/v1` (contrato público
    preservado byte a byte); as páginas `/app` passam o build do código porque o
    HTML muda a cada deploy mesmo sem dado novo.
    """
    versao = data_version if app_build is None else f"{data_version}\x00{app_build}"
    return f"{versao}\x00{path}\x00{canonical_query(query)}"


def etag_for(key: str) -> str:
    """``ETag`` forte e determinístico entre instâncias/processos."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    return f'"{digest}"'


def etag_matches(header: str | None, etag: str, *, allow_star: bool = True) -> bool:
    """Compara ``If-None-Match`` (lista, tags fracas ``W/`` e ``*``).

    ``allow_star=False`` trata ``*`` como não-casado: pela RFC 9110 o ``*`` só
    casa quando existe representação atual, e o *short-circuit* do middleware
    não sabe se o recurso existe (quem sabe é o handler).
    """
    if not header:
        return False
    wanted = _opaque(etag)
    for candidate in header.split(","):
        item = candidate.strip()
        if item == "*":
            return allow_star
        if _opaque(item) == wanted:
            return True
    return False


def _opaque(tag: str) -> str:
    return tag[2:] if tag.startswith("W/") else tag


class HttpCacheMiddleware(BaseHTTPMiddleware):
    """Aplica cache HTTP às respostas ``GET`` bem-sucedidas de um prefixo.

    Uma instância por superfície, cada uma com a sua política:

    * ``prefix="/v1/"`` (default, ``app_build=False``): o contrato público, com
      ``ETag`` de ``DATA_VERSION`` + caminho + query e ``Cache-Control`` de 1 dia;
    * ``prefix="/app"``, ``app_build=True``, ``exclude_prefix="/app/static/"``:
      as páginas SSR, com ``APP_BUILD`` no ``ETag`` e
      ``Cache-Control: private, no-cache`` (revalidação sempre, respondida por
      304 sem executar o handler). Os assets ficam de fora porque já são
      imutáveis pelo nome com hash e trazem o próprio ``Cache-Control``.
    """

    def __init__(
        self,
        app,  # type: ignore[no-untyped-def]
        *,
        cache: LruCache | None = None,
        cache_control: str = CACHE_CONTROL,
        prefix: str = _CACHEABLE_PATH_PREFIX,
        app_build: bool = False,
        exclude_prefix: str | None = None,
    ) -> None:
        super().__init__(app)
        self.cache = cache if cache is not None else LruCache()
        self.cache_control = cache_control
        self.prefix = prefix
        self.app_build = app_build
        self.exclude_prefix = exclude_prefix

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not self._cacheable(request):
            return await call_next(request)

        settings = getattr(request.app.state, "settings", None)
        data_version = getattr(settings, "data_version", "dev")
        build = getattr(settings, "app_build", "dev") if self.app_build else None
        key = cache_key(
            data_version,
            request.url.path,
            request.query_params.multi_items(),
            app_build=build,
        )
        etag = etag_for(key)

        if etag_matches(
            request.headers.get("if-none-match"), etag, allow_star=False
        ):
            _log_access(
                request, cache="hit", status=304, data_version=data_version, build=build
            )
            return _not_modified(self._headers(etag))

        cached = self.cache.get(key)
        if cached is not None:
            # `If-None-Match: *` casa aqui porque o recurso já está cacheado
            # (logo, existe) — RFC 9110.
            if etag_matches(request.headers.get("if-none-match"), etag):
                _log_access(
                    request,
                    cache="hit",
                    status=304,
                    data_version=data_version,
                    build=build,
                )
                return _not_modified(self._headers(etag))
            _log_access(
                request, cache="hit", status=200, data_version=data_version, build=build
            )
            return Response(
                content=cached.body,
                status_code=200,
                media_type=cached.media_type,
                headers=self._headers(etag),
            )

        response = await call_next(request)
        if response.status_code != _CACHEABLE_STATUS or _vetoed(response, self._vetos):
            # Erro (ou resposta que o endpoint marcou como não cacheável):
            # fica sem ETag/Cache-Control e nunca entra no LRU.
            _log_access(
                request,
                cache="miss",
                status=response.status_code,
                data_version=data_version,
                build=build,
            )
            return response

        body = await _collect_body(cast(StreamingResponse, response))
        media_type = response.media_type or "application/json"
        headers = dict(response.headers)
        headers.pop("content-length", None)

        self.cache.put(key, CachedResponse(body=body, media_type=media_type))
        # `If-None-Match: *` só casa quando existe representação atual
        # (RFC 9110). Aqui o handler respondeu 200, então 304 é o correto —
        # ao contrário do short-circuit acima, que não sabe se o recurso existe.
        if etag_matches(request.headers.get("if-none-match"), etag):
            _log_access(
                request, cache="hit", status=304, data_version=data_version, build=build
            )
            return _not_modified(self._headers(etag))
        _log_access(
            request, cache="miss", status=200, data_version=data_version, build=build
        )
        headers.update(self._headers(etag))
        return Response(
            content=body, status_code=200, media_type=media_type, headers=headers
        )

    def _cacheable(self, request: Request) -> bool:
        if request.method != _CACHEABLE_METHOD:
            return False
        caminho = request.url.path
        if self.exclude_prefix is not None and _pertence(caminho, self.exclude_prefix):
            return False
        return _pertence(caminho, self.prefix)

    @property
    def _vetos(self) -> tuple[str, ...]:
        # Nas páginas, `private` é a política do próprio middleware — só
        # `no-store` veta a resposta.
        if self.app_build:
            return _FORBIDDEN_CACHE_CONTROL_PAGINA
        return _FORBIDDEN_CACHE_CONTROL

    def _headers(self, etag: str) -> dict[str, str]:
        return {"ETag": etag, "Cache-Control": self.cache_control}


async def _collect_body(response: StreamingResponse) -> bytes:
    """Materializa o corpo da resposta para guardar no LRU."""
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunks.append(chunk)
        elif isinstance(chunk, str):
            chunks.append(chunk.encode("utf-8"))
        else:
            chunks.append(bytes(chunk))
    return b"".join(chunks)


def _not_modified(headers: dict[str, str]) -> Response:
    response = Response(status_code=304, headers=headers)
    # 304 não tem corpo; ``Content-Length: 0`` não descreve a representação.
    if "content-length" in response.headers:
        del response.headers["content-length"]
    return response


def _pertence(caminho: str, prefixo: str) -> bool:
    """Um caminho está sob o prefixo (o próprio prefixo ou algo abaixo dele)."""
    raiz = prefixo.rstrip("/")
    return caminho == raiz or caminho.startswith(raiz + "/")


def _vetoed(
    response: Response, vetoes: tuple[str, ...] = _FORBIDDEN_CACHE_CONTROL
) -> bool:
    cache_control = response.headers.get("cache-control", "").lower()
    return any(token in cache_control for token in vetoes)


def _log_access(
    request: Request,
    *,
    cache: str,
    status: int,
    data_version: str,
    build: str | None = None,
) -> None:
    """Linha `http_cache` (JSON no stdout) consumida pelos alertas de custo.

    As páginas `/app` acrescentam `app_build`; a linha do `/v1` continua com
    exatamente os mesmos campos de antes (contrato de log preservado).
    """
    extra: dict[str, object] = {
        "cache": cache,
        "status": status,
        "path": request.url.path,
        "data_version": data_version,
    }
    if build is not None:
        extra["app_build"] = build
    logger.info("http_cache", extra=extra)


__all__ = [
    "CACHE_CONTROL",
    "CACHE_CONTROL_PAGINA",
    "DEFAULT_MAX_ENTRIES",
    "CachedResponse",
    "HttpCacheMiddleware",
    "LruCache",
    "cache_key",
    "canonical_query",
    "etag_for",
    "etag_matches",
]
