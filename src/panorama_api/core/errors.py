"""Erros da API no formato RFC 9457 (`application/problem+json`).

Regra do contrato: erro nunca vira `200` com lista vazia nem com zeros.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Iterable, Mapping

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

PROBLEM_MEDIA_TYPE = "application/problem+json"
PROBLEM_TYPE_BASE = "https://api.panorama/erros/"


class ErrorCode(str, Enum):
    """Códigos de erro expostos no campo `code` do problem+json."""

    PARAMETRO_INVALIDO = "PARAMETRO_INVALIDO"
    NAO_ENCONTRADO = "NAO_ENCONTRADO"
    ANO_FORA_DO_CONTRATO = "ANO_FORA_DO_CONTRATO"
    FONTE_INDISPONIVEL = "FONTE_INDISPONIVEL"
    ERRO_INTERNO = "ERRO_INTERNO"


#: code -> (status HTTP, title, slug do `type`)
_CODE_META: Mapping[ErrorCode, tuple[int, str, str]] = {
    ErrorCode.PARAMETRO_INVALIDO: (422, "Parâmetro inválido", "parametro-invalido"),
    ErrorCode.NAO_ENCONTRADO: (404, "Não encontrado", "nao-encontrado"),
    ErrorCode.ANO_FORA_DO_CONTRATO: (
        404,
        "Ano fora do contrato",
        "ano-fora-do-contrato",
    ),
    ErrorCode.FONTE_INDISPONIVEL: (
        503,
        "Fonte indisponível",
        "fonte-indisponivel",
    ),
    ErrorCode.ERRO_INTERNO: (500, "Erro interno", "erro-interno"),
}


def problem_type(code: ErrorCode) -> str:
    return PROBLEM_TYPE_BASE + _CODE_META[code][2]


class ProblemError(Exception):
    """Erro de domínio que vira uma resposta RFC 9457."""

    def __init__(
        self,
        code: ErrorCode,
        detail: str,
        *,
        status: int | None = None,
        title: str | None = None,
        errors: Iterable[Mapping[str, Any]] | None = None,
    ) -> None:
        default_status, default_title, _ = _CODE_META[code]
        self.code = code
        self.status = status or default_status
        self.title = title or default_title
        self.detail = detail
        self.errors = [dict(item) for item in (errors or ())]
        super().__init__(detail)


class UpstreamUnavailable(Exception):
    """Falha/timeout/teto de bytes do BigQuery (vira 503 `FONTE_INDISPONIVEL`)."""


def invalid(detail: str, *, loc: tuple[str, ...] | None = None) -> ProblemError:
    errors = [{"loc": list(loc), "msg": detail}] if loc else []
    return ProblemError(ErrorCode.PARAMETRO_INVALIDO, detail, errors=errors)


def not_found(detail: str) -> ProblemError:
    return ProblemError(ErrorCode.NAO_ENCONTRADO, detail)


def bad_request(detail: str, *, loc: tuple[str, ...] | None = None) -> ProblemError:
    """400 `PARAMETRO_INVALIDO`: combinação inválida ou parâmetro desconhecido."""
    errors = [{"loc": list(loc), "msg": detail}] if loc else []
    return ProblemError(
        ErrorCode.PARAMETRO_INVALIDO, detail, status=400, errors=errors
    )


def ano_fora_do_contrato(detail: str) -> ProblemError:
    return ProblemError(ErrorCode.ANO_FORA_DO_CONTRATO, detail)


def problem_body(
    request: Request,
    *,
    code: ErrorCode,
    status: int,
    title: str,
    detail: str,
    errors: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "type": problem_type(code),
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "code": code.value,
        "errors": [dict(item) for item in (errors or ())],
    }


def problem_response(request: Request, exc: ProblemError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        media_type=PROBLEM_MEDIA_TYPE,
        content=problem_body(
            request,
            code=exc.code,
            status=exc.status,
            title=exc.title,
            detail=exc.detail,
            errors=exc.errors,
        ),
    )


def _validation_loc(loc: Iterable[Any]) -> list[str]:
    parts = [str(part) for part in loc]
    # FastAPI prefixa a origem ("query"/"path"/"body"); mantém como está.
    return parts or ["request"]


def validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    return [
        {"loc": _validation_loc(err.get("loc", ())), "msg": err.get("msg", "valor inválido")}
        for err in exc.errors()
    ]
