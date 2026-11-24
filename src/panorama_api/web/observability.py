"""Linha de log `page_view` por requisição de página sob `/app` (plano §7, card F6).

O plano pede o **mínimo** de observabilidade do front, reusando a infra de log
que já existe (`core/logging_config.py` emite uma linha JSON por registro no
stdout, e é isso que o Cloud Logging lê como `jsonPayload`). Nada aqui é RUM,
telemetria de JavaScript nem uptime check — os três estão fora do MVP.

Responsabilidades separadas:

* quem sabe se a resposta veio do LRU, do handler ou de um 304 é o
  `HttpCacheMiddleware` de páginas. Ele já decide isso; aqui só lemos a decisão
  publicada em `request.scope` (`CACHE_SCOPE_KEY`);
* este middleware acrescenta o que é de analytics: `route` (template da rota,
  não o caminho concreto), `ms`, `data_version`, `app_build` e `user_hash`.

`user_hash` é ``sha256(salt + email)[:16]`` do e-mail que o IAP injeta em
``X-Goog-Authenticated-User-Email`` (formato ``<emissor>:<email>``). O e-mail
**nunca** vai para o log: os dados são públicos, mas a identidade do piloto não.
Sem `API_OBS_USER_HASH_SALT` configurado o hash seria reversível por dicionário
(e-mails corporativos são poucos e previsíveis), então o valor degrada para
``anon`` em vez de hashear sem salt.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match
from starlette.types import ASGIApp

from panorama_api.core.http_cache import CACHE_SCOPE_KEY
from panorama_api.web import PREFIXO_WEB, e_caminho_web

logger = logging.getLogger(__name__)

#: Valor de `user_hash` quando não há identidade (sem header) ou salt ausente.
USER_HASH_ANON = "anon"

#: Cabeçalho do IAP. O valor vem como ``accounts.google.com:<email>``.
EMAIL_HEADER = "x-goog-authenticated-user-email"

#: Assets do front são conteúdo estático versionado por hash, não páginas: não
#: entram no `page_view` (mesma exclusão que o cache de páginas faz).
ASSET_PREFIX = f"{PREFIXO_WEB}/static/"

#: `cache` do plano §7: hit | miss | 304.
CACHE_HIT = "hit"
CACHE_MISS = "miss"
CACHE_NOT_MODIFIED = "304"

_ALREADY_WARNED_ATTR = "_panorama_api_salt_warned"
_salt_warned = False


def email_do_header(valor: str | None) -> str | None:
    """Extrai o e-mail de ``<emissor>:<email>``; devolve ``None`` sem header."""
    if not valor:
        return None
    _, separador, email = valor.rpartition(":")
    email = (email if separador else valor).strip()
    return email or None


def user_hash(email: str | None, salt: str) -> str:
    """``sha256(salt + email)[:16]``; ``anon`` sem e-mail **ou** sem salt."""
    if not email or not salt:
        return USER_HASH_ANON
    digest = hashlib.sha256((salt + email).encode("utf-8")).hexdigest()
    return digest[:16]


def route_template(request: Request) -> str:
    """Template da rota (ex. ``/app/escolas/{co_entidade}``).

    O router do Starlette escreve ``scope["route"]`` depois que o handler entra,
    então um *hit* do LRU ou um 304 de revalidação — que não executam o handler —
    não têm essa chave. Nesses casos casamos o caminho contra as rotas
    registradas: o template não depende de o handler ter rodado.

    Caminho que não casa rota nenhuma (404 de `/app/inexistente`) cai no próprio
    caminho, para que a linha continue rastreável.
    """
    route = request.scope.get("route")
    if route is not None:
        template = getattr(route, "path_format", None) or getattr(route, "path", None)
        if template:
            return str(template)

    caminho = request.url.path
    for candidata in request.app.router.routes:
        match, _ = candidata.matches(request.scope)
        if match is not Match.NONE:
            template = getattr(candidata, "path_format", None) or getattr(
                candidata, "path", None
            )
            if template:
                return str(template)
    return caminho


def _pertence(caminho: str, prefixo: str) -> bool:
    raiz = prefixo.rstrip("/")
    return caminho == raiz or caminho.startswith(raiz + "/")


class PageViewMiddleware(BaseHTTPMiddleware):
    """Emite uma linha `page_view` por requisição de página do front."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        caminho = request.url.path
        # `/app/static/*` são assets imutáveis, não páginas; `/v1` e `/health`
        # têm a própria linha (`http_cache`/`bq_query`) e não são front.
        if not e_caminho_web(caminho) or _pertence(caminho, ASSET_PREFIX):
            return await call_next(request)

        inicio = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            # Erro que escapou dos handlers: o status que o cliente vê é 500.
            _log_page_view(request, status=500, inicio=inicio)
            raise
        _log_page_view(request, status=response.status_code, inicio=inicio)
        return response


def _log_page_view(request: Request, *, status: int, inicio: float) -> None:
    settings = getattr(request.app.state, "settings", None)
    salt = getattr(settings, "obs_user_hash_salt", "") or ""
    if not salt:
        _warn_salt_ausente()

    email = email_do_header(request.headers.get(EMAIL_HEADER))
    extra: dict[str, Any] = {
        "route": route_template(request),
        "status": status,
        "cache": _cache_status(request.scope.get(CACHE_SCOPE_KEY), status),
        "ms": round((time.monotonic() - inicio) * 1000.0, 1),
        "data_version": getattr(settings, "data_version", "dev"),
        "app_build": getattr(settings, "app_build", "dev"),
        "user_hash": user_hash(email, salt),
    }
    logger.info("page_view", extra=extra)


def _cache_status(outcome: object, status: int) -> str:
    """Normaliza a decisão do cache para o vocabulário do plano: hit|miss|304."""
    if status == 304:
        return CACHE_NOT_MODIFIED
    if outcome in (CACHE_HIT, CACHE_MISS):
        return str(outcome)
    # Requisição que o cache de páginas não tratou (método diferente de GET, por
    # exemplo) executou o handler: do ponto de vista do `page_view`, é `miss`.
    return CACHE_MISS


def _warn_salt_ausente() -> None:
    """Avisa uma vez por processo que `user_hash` está degradado para `anon`."""
    global _salt_warned
    if _salt_warned:
        return
    _salt_warned = True
    logger.warning(
        "page_view_user_hash_sem_salt",
        extra={"env": "API_OBS_USER_HASH_SALT"},
    )


def reset_warning() -> None:
    """Volta o aviso de salt ausente ao estado inicial (uso em teste)."""
    global _salt_warned
    _salt_warned = False


__all__ = [
    "ASSET_PREFIX",
    "CACHE_HIT",
    "CACHE_MISS",
    "CACHE_NOT_MODIFIED",
    "CACHE_SCOPE_KEY",
    "EMAIL_HEADER",
    "PageViewMiddleware",
    "USER_HASH_ANON",
    "email_do_header",
    "reset_warning",
    "route_template",
    "user_hash",
]
