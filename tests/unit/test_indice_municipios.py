"""Índice de municípios (V4-4b): camada de dado, etapa `bas` fixa, 1 consulta/ano."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request

from panorama_api.core.errors import ErrorCode, ProblemError, UpstreamUnavailable
from panorama_api.repositories import queries
from panorama_api.services import indice as service_indice
from panorama_api.web import dados as web_dados

MUNICIPIOS_JSON = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "panorama_api"
    / "web"
    / "data"
    / "municipios_mg.json"
)


def _fq(table: str) -> str:
    return f"`panorama-escola-staging.panorama_serving.{table}`"


def _codigos_mg() -> list[str]:
    return [
        item["co_municipio"]
        for item in json.loads(MUNICIPIOS_JSON.read_text(encoding="utf-8"))
    ]


def _linha(
    co_municipio: str,
    i: int,
    *,
    qt: float | None = 1000.0,
    anterior: float | None = 900.0,
    escolas: int | None = 10,
    share: float | None = 2.5,
) -> dict[str, Any]:
    qt_val: float | None = 300000.0 - i * 137.5 if qt is not None else None
    anterior_val: float | None = None
    if anterior is not None and qt_val is not None:
        anterior_val = round(qt_val - (i % 5) * 100.0, 2)
    escolas_val: int | None = (i % 200) + 1 if escolas is not None else None
    share_val: float | None = (
        round(1.0 + (i % 90) / 10.0, 2) if share is not None else None
    )
    if qt_val is None or anterior_val is None or anterior_val == 0:
        variacao: float | None = None
    else:
        variacao = (qt_val - anterior_val) / anterior_val * 100
    return {
        "co_municipio": co_municipio,
        "qt_mat_privada": qt_val,
        "qt_mat_privada_anterior": anterior_val,
        "n_escolas_privadas": escolas_val,
        "variacao_pct": variacao,
        "share_lider_pct": share_val,
    }


def _fixture_853(codigos: list[str]) -> list[dict[str, Any]]:
    linhas = []
    for i, co in enumerate(codigos):
        linhas.append(
            _linha(
                co,
                i,
                qt=None if i % 17 == 16 else 1000.0,
                anterior=None if i % 13 == 12 else 900.0,
                escolas=None if i % 11 == 10 else 10,
                share=None if i % 7 == 6 else 2.5,
            )
        )
    # Ordem do SQL: NULLS LAST, qt DESC, co_municipio.
    def _chave(r: dict[str, Any]) -> tuple[bool, float, str]:
        qt = r["qt_mat_privada"]
        assert qt is None or isinstance(qt, (int, float))
        co = r["co_municipio"]
        assert isinstance(co, str)
        return (qt is None, -(qt or 0.0), co)

    return sorted(linhas, key=_chave)


# -- SQL --------------------------------------------------------------------


def test_sql_parametriza_ano_e_fixa_etapa_bas():
    sql, params = queries.indice_municipios(_fq, ano=2025)

    assert params == [("ano", "INT64", 2025)]
    assert "@ano" in sql
    assert "2025" not in sql  # ano nunca interpolado
    assert sql.count("etapa = 'bas'") == 2  # m e c, fixa (sem param de etapa)
    assert "@etapa" not in sql
    assert "COUNT(" not in sql.upper()  # sem COUNT: 853 linhas, sem total


def test_sql_usa_tabelas_via_fq_e_colunas_do_q4b_final():
    sql, _ = queries.indice_municipios(_fq, ano=2025)

    assert f"FROM {_fq('mart_mercado')}" in sql
    assert f"FROM {_fq('mart_concentracao')}" in sql
    assert "nu_ano_censo IN (@ano, @ano - 1)" in sql
    assert "nu_ano_censo = @ano" in sql
    assert "recorte = 'privado'" in sql
    assert "nivel = 'escola'" in sql
    assert "b.qt_mat_privada AS qt_mat_privada_anterior" in sql
    assert "SAFE_DIVIDE(a.qt_mat_privada - b.qt_mat_privada, b.qt_mat_privada) * 100" in sql
    assert (
        "ORDER BY (a.qt_mat_privada IS NULL), a.qt_mat_privada DESC, a.co_municipio"
        in sql
    )


# -- 853 linhas ---------------------------------------------------------------


def test_fixture_gerada_tem_853_linhas(repository, settings):
    codigos = _codigos_mg()

    assert len(codigos) == 853

    repository.indice = _fixture_853(codigos)
    resultado = service_indice.indice_municipios(repository, settings, ano=2025)

    assert resultado.ano == 2025
    assert len(resultado.linhas) == 853
    assert resultado.kpis.n_municipios == 853
    # Ordem do SQL preservada: maior matrícula primeiro, NULLs por último.
    assert resultado.linhas[0].qt_mat_privada == max(
        r["qt_mat_privada"]
        for r in repository.indice
        if r["qt_mat_privada"] is not None
    )
    assert resultado.linhas[-1].qt_mat_privada is None


def test_uma_execucao_por_chamada(repository, settings):
    repository.indice = _fixture_853(_codigos_mg())

    service_indice.indice_municipios(repository, settings, ano=2025)

    assert repository.methods_called() == ["get_indice_municipios"]
    assert repository.calls[0][1] == {"ano": 2025}


# -- NULL ≠ 0 -----------------------------------------------------------------


def test_none_nunca_vira_zero(repository, settings):
    repository.indice = [
        {
            "co_municipio": "3106200",
            "qt_mat_privada": None,
            "qt_mat_privada_anterior": None,
            "n_escolas_privadas": None,
            "variacao_pct": None,
            "share_lider_pct": None,
        }
    ]

    resultado = service_indice.indice_municipios(repository, settings, ano=2025)

    (linha,) = resultado.linhas
    assert linha.qt_mat_privada is None
    assert linha.qt_mat_privada_anterior is None
    assert linha.n_escolas_privadas is None
    assert linha.variacao_pct is None
    assert linha.share_lider_pct is None
    assert resultado.kpis.qt_mat_privada_total is None
    assert resultado.kpis.qt_mat_privada_anterior_total is None
    assert resultado.kpis.n_escolas_privadas_total is None
    assert resultado.kpis.variacao_pct is None


def test_variacao_nula_sem_base(repository, settings):
    repository.indice = [
        {
            "co_municipio": "3106200",
            "qt_mat_privada": 1200.0,
            "qt_mat_privada_anterior": None,
            "n_escolas_privadas": 12,
            "variacao_pct": None,  # sem base o SQL devolve NULL
            "share_lider_pct": 3.1,
        }
    ]

    resultado = service_indice.indice_municipios(repository, settings, ano=2025)

    assert resultado.linhas[0].variacao_pct is None
    # Sem linha com ambos os anos, a variação do recorte também é nula.
    assert resultado.kpis.variacao_pct is None
    # ...mas os totais somam o que existe.
    assert resultado.kpis.qt_mat_privada_total == 1200.0
    assert resultado.kpis.qt_mat_privada_anterior_total is None


def test_kpis_somam_ignorando_none_e_variacao_so_com_ambos(repository, settings):
    repository.indice = [
        {
            "co_municipio": "3106200",
            "qt_mat_privada": 100.0,
            "qt_mat_privada_anterior": 80.0,
            "n_escolas_privadas": 10,
            "variacao_pct": 25.0,
            "share_lider_pct": 2.0,
        },
        {
            "co_municipio": "3170206",
            "qt_mat_privada": None,
            "qt_mat_privada_anterior": 50.0,
            "n_escolas_privadas": None,
            "variacao_pct": None,
            "share_lider_pct": None,
        },
        {
            "co_municipio": "3136702",
            "qt_mat_privada": 30.0,
            "qt_mat_privada_anterior": None,
            "n_escolas_privadas": 5,
            "variacao_pct": None,
            "share_lider_pct": 1.0,
        },
    ]

    resultado = service_indice.indice_municipios(repository, settings, ano=2025)

    assert resultado.kpis.qt_mat_privada_total == pytest.approx(130.0)
    assert resultado.kpis.qt_mat_privada_anterior_total == pytest.approx(130.0)
    assert resultado.kpis.n_escolas_privadas_total == 15
    # Só a 1ª linha tem ambos os anos: (100-80)/80*100. Sobre os totais
    # brutos daria 0 — o recorte exclui as linhas incompletas.
    assert resultado.kpis.variacao_pct == pytest.approx(25.0)


# -- contrato de erro ----------------------------------------------------------


def test_ano_fora_dos_disponiveis_nao_consulta(repository, settings):
    with pytest.raises(ProblemError) as excinfo:
        service_indice.indice_municipios(repository, settings, ano=2020)

    assert excinfo.value.code == ErrorCode.ANO_FORA_DO_CONTRATO
    assert repository.methods_called() == []


def test_upstream_indisponivel_propaga_tipado(repository, settings):
    repository.indice = _fixture_853(_codigos_mg())
    repository.errors["get_indice_municipios"] = UpstreamUnavailable("timeout")

    with pytest.raises(UpstreamUnavailable):
        service_indice.indice_municipios(repository, settings, ano=2025)


# -- seam do front -------------------------------------------------------------


def _request(app: FastAPI) -> Request:
    return Request(
        {
            "type": "http",
            "app": app,
            "method": "GET",
            "scheme": "http",
            "path": "/app/",
            "root_path": "",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )


def test_dados_repasse_fino_ao_servico(client, repository):
    repository.indice = _fixture_853(_codigos_mg())

    resultado = web_dados.indice_municipios(_request(client.app), ano=2025)

    assert resultado.ano == 2025
    assert len(resultado.linhas) == 853
    # `create_app` valida o schema no startup (`get_table_columns`); o repasse
    # em si faz exatamente 1 leitura do índice.
    assert repository.calls[-1] == ("get_indice_municipios", {"ano": 2025})
    assert [n for n, _ in repository.calls if n == "get_indice_municipios"] == [
        "get_indice_municipios"
    ]


def test_dados_ano_obrigatorio(client, repository):
    with pytest.raises(ProblemError) as excinfo:
        web_dados.indice_municipios(_request(client.app), ano=None)  # type: ignore[arg-type]

    assert excinfo.value.code == ErrorCode.PARAMETRO_INVALIDO
    assert "get_indice_municipios" not in repository.methods_called()
