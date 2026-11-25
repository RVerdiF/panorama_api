"""Middlewares do front: gzip e headers de segurança de ``/`` e ``/app``.

O `/v1` é contrato público: o card proíbe mudar headers das respostas JSON. Por
isso nem a compressão nem a CSP são aplicadas globalmente — só nas respostas do
front (HTML, páginas de erro HTML e ``/app/static/*``), onde o gzip é mitigação
de egress do plano §3 e onde o navegador executa o `app.js`. Quem define
"resposta do front" é :func:`panorama_api.web.e_caminho_web`, o mesmo predicado
usado pelo erro HTML, pelo `page_view` e pelo cache de página.

O header de CSP é **constante**: sem nonce e sem hash inline. Um nonce mudaria o
corpo a cada requisição e quebraria o `ETag`/LRU das páginas; constante, ele
convive com *hit*, *miss* e 304. Por isso o middleware fica **por fora** do
`HttpCacheMiddleware` de páginas.
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from panorama_api.web import e_caminho_web


class WebGZipMiddleware(GZipMiddleware):
    """`GZipMiddleware` que só comprime requisições das páginas do front."""

    def __init__(self, app: ASGIApp, *, minimum_size: int = 500) -> None:
        super().__init__(app, minimum_size=minimum_size)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            caminho = scope.get("path", "")
            if not e_caminho_web(caminho):
                await self.app(scope, receive, send)
                return
        await super().__call__(scope, receive, send)

#: Política do front (spec `interatividade.md` §6): nada implícito, script,
#: estilo, imagem, fonte, `fetch` e formulário só da própria origem.
#:
#: `font-src 'self'` entrou no card V1 (`t_423aa547`) junto com as fontes
#: self-hosted: com `default-src 'none'` e sem essa diretiva o navegador
#: bloquearia cada `.woff2` servido por `/app/static/…` e o `@font-face` cairia
#: na fonte de fallback. Continua fechado — só a própria origem, nada de CDN.
CSP_WEB = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self'; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "object-src 'none'"
)

#: Passamos a servir JavaScript: sem `nosniff` o navegador pode reinterpretar
#: o tipo do asset.
NOSNIFF_WEB = "nosniff"

_CABECALHOS_WEB = (
    ("content-security-policy", CSP_WEB),
    ("x-content-type-options", NOSNIFF_WEB),
)


class WebSecurityHeadersMiddleware:
    """CSP + `nosniff` nas respostas do front; nada fora de ``/`` e ``/app``."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not e_caminho_web(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        async def send_com_cabecalhos(message: Message) -> None:
            if message["type"] == "http.response.start":
                cabecalhos = MutableHeaders(scope=message)
                for nome, valor in _CABECALHOS_WEB:
                    if nome not in cabecalhos:
                        cabecalhos.append(nome, valor)
            await send(message)

        await self.app(scope, receive, send_com_cabecalhos)


__all__ = ["CSP_WEB", "NOSNIFF_WEB", "WebSecurityHeadersMiddleware"]
