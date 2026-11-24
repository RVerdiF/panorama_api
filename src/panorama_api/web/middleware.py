"""gzip restrito às páginas do front (``/`` e ``/app``).

O `/v1` é contrato público: o card proíbe mudar headers das respostas JSON.
Por isso a compressão não é aplicada globalmente — só nos caminhos do front
(HTML/CSS e páginas de erro), onde o gzip é mitigação de egress do plano §3.
Quem define "página do front" é :func:`panorama_api.web.e_caminho_web`, o mesmo
predicado usado pelo erro HTML, pelo `page_view` e pelo cache de página.
"""

from __future__ import annotations

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

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


__all__ = ["WebGZipMiddleware"]
