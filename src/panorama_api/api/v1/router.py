"""Router da v1 (prefixo `/v1`)."""

from __future__ import annotations

from fastapi import APIRouter

from panorama_api.api.v1 import markets, schools

router = APIRouter()
router.include_router(schools.router)
router.include_router(markets.router)
