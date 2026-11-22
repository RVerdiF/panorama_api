"""gzip restrito ao front `/app`.

O `/v1` é contrato público: o card proíbe mudar headers das respostas JSON.
Por isso a compressão não é aplicada globalmente — só nos caminhos do front
(HTML/CSS e páginas de erro), onde o gzip é mitigação de egress do plano §3.
"""

from __future__ import annotations

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from panorama_api.web import PREFIXO_WEB


class WebGZipMiddleware(GZipMiddleware):
    """`GZipMiddleware` que só comprime requisições sob o prefixo do front."""

    def __init__(self, app: ASGIApp, *, minimum_size: int = 500) -> None:
        super().__init__(app, minimum_size=minimum_size)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            caminho = scope.get("path", "")
            if caminho != PREFIXO_WEB and not caminho.startswith(PREFIXO_WEB + "/"):
                await self.app(scope, receive, send)
                return
        await super().__call__(scope, receive, send)


__all__ = ["WebGZipMiddleware"]
