"""Rate limit em processo: 60 req/min/IP, janela deslizante, por chave."""

from __future__ import annotations

import pytest

from panorama_api.repositories.bigquery import InProcessRateLimiter, RateLimited
from panorama_api.repositories.bigquery.ratelimit import DEFAULT_LIMIT, DEFAULT_WINDOW_S


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_defaults_do_plano_2d() -> None:
    assert DEFAULT_LIMIT == 60
    assert DEFAULT_WINDOW_S == 60.0


def test_permite_60_e_bloqueia_a_61() -> None:
    clock = FakeClock()
    limiter = InProcessRateLimiter(clock=clock)

    for _ in range(60):
        assert limiter.check("203.0.113.7").allowed is True

    decision = limiter.check("203.0.113.7")
    assert decision.allowed is False
    assert decision.remaining == 0
    assert decision.retry_after_s == pytest.approx(60.0)


def test_janela_deslizante_libera_apos_expirar() -> None:
    clock = FakeClock()
    limiter = InProcessRateLimiter(clock=clock)

    for _ in range(60):
        limiter.check("ip")
    assert limiter.check("ip").allowed is False

    clock.advance(60.1)
    assert limiter.check("ip").allowed is True


def test_chaves_diferentes_sao_independentes() -> None:
    clock = FakeClock()
    limiter = InProcessRateLimiter(limit=2, clock=clock)

    assert limiter.check("a").allowed
    assert limiter.check("a").allowed
    assert limiter.check("a").allowed is False
    assert limiter.check("b").allowed is True


def test_remaining_decresce() -> None:
    limiter = InProcessRateLimiter(limit=3, clock=FakeClock())

    assert limiter.check("k").remaining == 2
    assert limiter.check("k").remaining == 1
    assert limiter.check("k").remaining == 0


def test_configuracao_invalida() -> None:
    with pytest.raises(ValueError):
        InProcessRateLimiter(limit=0)
    with pytest.raises(ValueError):
        InProcessRateLimiter(window_s=0)


def test_executor_aplica_rate_limit_antes_do_bigquery() -> None:
    from panorama_api.repositories.bigquery import BigQuerySettings, QueryExecutor

    from conftest import FakeQueryClient

    client = FakeQueryClient()
    executor = QueryExecutor(
        settings=BigQuerySettings(project="p", dataset="d"),
        client=client,
        rate_limiter=InProcessRateLimiter(limit=2, window_s=60, clock=FakeClock()),
    )
    filtros = {"co_municipio": "3106200"}

    executor.execute("schools", filtros, client_ip="198.51.100.1")
    executor.execute("schools", filtros, client_ip="198.51.100.1")

    with pytest.raises(RateLimited) as exc:
        executor.execute("schools", filtros, client_ip="198.51.100.1")

    assert exc.value.http_status == 429
    assert exc.value.retry_after_s == pytest.approx(60.0)
    assert len(client.calls) == 2, "a 3ª requisição não pode chegar ao BigQuery"
