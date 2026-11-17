"""Dependências compartilhadas dos routers da v1."""

from __future__ import annotations

from typing import Callable

from fastapi import Request

from panorama_api.config import Settings
from panorama_api.core.validation import reject_unknown_params
from panorama_api.repositories.serving import ServingRepository
from panorama_api.schemas.common import Problem

#: Respostas de erro documentadas no OpenAPI (corpo RFC 9457).
PROBLEM_CONTENT = {"application/problem+json": {}}
PROBLEM_RESPONSES: dict[int | str, dict] = {
    400: {"model": Problem, "content": PROBLEM_CONTENT, "description": "Requisição inválida"},
    404: {"model": Problem, "content": PROBLEM_CONTENT, "description": "Não encontrado / ano fora do contrato"},
    422: {"model": Problem, "content": PROBLEM_CONTENT, "description": "Parâmetro inválido"},
    503: {"model": Problem, "content": PROBLEM_CONTENT, "description": "Fonte indisponível"},
}


def get_repository(request: Request) -> ServingRepository:
    return request.app.state.repo


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def unknown_params_guard(allowed: frozenset[str]) -> Callable[[Request], None]:
    """Rejeita parâmetro fora da allowlist (`order`, `fields`, SQL...)."""

    def guard(request: Request) -> None:
        reject_unknown_params(dict(request.query_params), allowed)

    return guard
