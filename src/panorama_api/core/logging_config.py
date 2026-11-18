"""Logging estruturado (JSON por linha no stdout) da API.

Motivação (card ``t_817a670c``, revisão 2): os alertas de custo consomem
``bq_ms`` e ``cache`` como **campos** de log. O formatter padrão do Python
descarta ``extra`` e o logger ``panorama_api`` herdava o nível ``WARNING``, de
modo que na execução real nada era emitido. Aqui:

* o logger ``panorama_api`` (e seus filhos) fica em ``INFO``;
* cada registro vira **uma linha JSON** em `stdout`, que o Cloud Logging lê
  como `jsonPayload` (campos consultáveis, ex. `bq_ms`, `cache`);
* ``propagate=True`` e nenhum handler no root: em produção não há duplicação,
  e o ``caplog`` do pytest continua vendo os registros.

Não mexe no root nem nos loggers ``uvicorn.*``: o `--log-config` do uvicorn
segue mandando na parte HTTP e o app só cuida dos próprios registros.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

APP_LOGGER = "panorama_api"

#: Atributos que todo `LogRecord` já tem; o resto veio de `extra=` e vira campo
#: do JSON. Inclui nomes adicionados por versões novas do Python (`taskName`).
_RESERVED_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

_HANDLER_FLAG = "_panorama_api_structured"
_configured = False


class JsonFormatter(logging.Formatter):
    """Serializa o registro (mensagem + ``extra``) como um objeto JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "timestamp": _timestamp(record.created),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_ATTRS or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # `default=str`: um campo `extra` não serializável não derruba o log.
        return json.dumps(payload, ensure_ascii=False, default=str)


def _timestamp(created: float) -> str:
    return (
        datetime.fromtimestamp(created, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class _StdoutHandler(logging.StreamHandler):
    """Escreve sempre no ``sys.stdout`` **corrente**.

    O `StreamHandler` padrão guarda o stream no construtor; aqui o stream é
    resolvido a cada emissão, então redirecionamentos (Cloud Run, `capsys`) são
    respeitados mesmo que o logging tenha sido configurado antes.
    """

    def __init__(self) -> None:
        super().__init__(sys.stdout)

    @property
    def stream(self):  # type: ignore[override]
        return sys.stdout

    @stream.setter
    def stream(self, _value: object) -> None:  # o construtor tenta atribuir
        pass


def configure_logging(level: int = logging.INFO, *, force: bool = False) -> logging.Logger:
    """Liga o log estruturado do app. Idempotente; ``force`` recria o handler."""
    global _configured
    logger = logging.getLogger(APP_LOGGER)
    if _configured and not force:
        return logger

    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_FLAG, False):
            logger.removeHandler(handler)
            handler.close()

    handler = _StdoutHandler()
    handler.setFormatter(JsonFormatter())
    setattr(handler, _HANDLER_FLAG, True)
    logger.addHandler(handler)
    logger.setLevel(level)
    # Os registros seguem para o root (caplog em teste); em produção o root não
    # tem handler, então não há linha duplicada.
    logger.propagate = True
    _configured = True
    return logger


__all__ = ["APP_LOGGER", "JsonFormatter", "configure_logging"]
