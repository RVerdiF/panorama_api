"""Evidência manual dos critérios de aceite do card t_ae1f7c43.

Renderiza as telas com o TestClient + FakeRepository (sem rede/BigQuery) usando
dados no formato exato do contrato, e imprime o que o HTML final contém. Não é
teste: é a coleta de evidência para o card.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_ANOS_DISPONIVEIS", "2021,2022,2023,2024,2025")

from fastapi.testclient import TestClient  # noqa: E402

from panorama_api.config import Settings  # noqa: E402
from panorama_api.main import create_app  # noqa: E402
from tests.unit.conftest import (  # noqa: E402
    FakeRepository,
    competidor_row,
    history_row,
    indicator_row,
    market_row,
    municipio_row,
    school_row,
    share_row,
)

ANOS = (2021, 2022, 2023, 2024, 2025)


def settings() -> Settings:
    return Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        max_bytes_billed=256 * 1024 * 1024,
        validate_schema_on_startup=False,
        contract_version="mvp-1",
        app_anos_disponiveis=",".join(str(a) for a in ANOS),
    )


def client(repo: FakeRepository) -> TestClient:
    return TestClient(create_app(settings=settings(), repository=repo))


def tabela(html: str, prefixo: str) -> str:
    for t in re.findall(r"<table[^>]*>.*?</table>", html, flags=re.S):
        if prefixo in t:
            return t
    raise AssertionError(f"tabela ausente: {prefixo}")


def linhas(tab: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", tr)).strip()
        for tr in re.findall(r"<tr>(.*?)</tr>", tab, flags=re.S)
    ]


OK = "[OK]  "
FAIL = "[FALHA] "
falhas = 0


def check(cond: bool, rotulo: str, detalhe: str = "") -> None:
    global falhas
    if cond:
        print(f"{OK}{rotulo}")
    else:
        falhas += 1
        print(f"{FAIL}{rotulo} :: {detalhe}")


print("=" * 78)
print("E2 — contagem sem ',0' em /app/mercados/3106200")
print("=" * 78)
repo = FakeRepository(
    municipios=[municipio_row()],
    markets=[
        market_row(
            nu_ano_censo=ano,
            etapa=etapa,
            n_escolas_entraram=43.0,
            n_escolas_ativas_com_baseline=172322.0,
            n_escolas_sairam=7.0,
            qt_mat_total=172322.0,
            qt_mat_privada=15000.0,
        )
        for ano in ANOS
        for etapa in ("bas", "creche", "pre", "fund_ai", "fund_af", "med", "prof", "eja", "esp")
    ],
    share=[
        share_row(nu_ano_censo=2025, etapa="bas", mat_entidade=172322.0, share_privado_pct=8.7)
    ],
)
html = client(repo).get("/app/mercados/3106200").text
hit = re.search(r"\d,0\b(?!%)", html)
check(hit is None, "regex \\d,0\\b ausente (exceto %)", str(hit))
for trecho in ("Escolas que entraram", "Escolas comparáveis", "Escolas que saíram"):
    for linha in linhas(html):
        if trecho in linha:
            print(f"        {linha}")
check(">172.322<" in html, "matrícula total como inteiro (172.322)")
check(">43<" in html, "escolas que entraram como inteiro (43)")
check("8,7%" in html, "percentual mantém 1 casa (8,7%)")

print()
print("=" * 78)
print("E3 — ano ausente na série (/app/escolas/31364835: 2020, 2022, 2023)")
print("=" * 78)
repo = FakeRepository(
    history=[
        history_row(co_entidade="31364835", nu_ano_censo=2020, tp_dependencia="4", qt_mat_bas=100),
        history_row(co_entidade="31364835", nu_ano_censo=2022, tp_dependencia="4", qt_mat_bas=120),
        history_row(co_entidade="31364835", nu_ano_censo=2023, tp_dependencia="4", qt_mat_bas=130),
    ],
)
html = client(repo).get("/app/escolas/31364835").text
tab = tabela(html, "Série de matrículas por ano")
for linha in linhas(tab):
    print(f"        {linha}")
check("2021" in tab and "sem dado (ano ausente na fonte)" in tab, "linha 2021 com 'sem dado'")
check(">0<" not in tab, "nenhum zero inventado na série")

print()
print("=" * 78)
print("E4 — composição por etapa sem repetir total municipal")
print("=" * 78)
repo = FakeRepository(
    municipios=[municipio_row()],
    markets=[
        market_row(nu_ano_censo=2025, etapa=etapa, n_escolas_ativas=100,
                   n_escolas_privadas=30)
        for etapa in ("bas", "creche", "pre", "fund_ai", "fund_af", "med", "prof", "eja", "esp")
    ],
    share=[share_row(nu_ano_censo=2025, etapa="bas")],
)
html_mercado = client(repo).get("/app/mercados/3106200").text
tab = tabela(html_mercado, "Tamanho do mercado por etapa")
for linha in linhas(tab)[:4]:
    print(f"        {linha}")
check("Escolas ativas" not in tab and "Privadas ativas" not in tab,
      "colunas repetidas fora da tabela por etapa")
check(html_mercado.count("Escolas privadas ativas no município e ano") == 1,
      "total do município aparece 1x")

print()
print("=" * 78)
print("E5 — rótulos INEP (/app/escolas/31334243: dependência 2)")
print("=" * 78)
repo = FakeRepository(
    history=[history_row(co_entidade="31334243", nu_ano_censo=2025, tp_dependencia="2",
                         tp_situacao_funcionamento="3")],
)
html = client(repo).get("/app/escolas/31334243").text
for m in re.findall(r"<dt>[^<]*(?:Dependência|Situação)[^<]*</dt>\s*<dd>(.*?)</dd>", html, flags=re.S):
    texto = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m)).strip()
    print(f"        {texto}")
check("Estadual" in html, "contém 'Estadual'")
check("não privada" not in html, "não contém 'não privada'")
check("Extinta" in html and "não ativa" not in html, "situação 3 = 'Extinta'")

print()
print("=" * 78)
print("E6 — jargão interno fora das telas")
print("=" * 78)
repo = FakeRepository(
    municipios=[municipio_row()],
    schools=[school_row(of_bas=None, is_oferta_desconhecida=True)],
    history=[history_row(co_entidade="31334243", nu_ano_censo=2025, is_oferta_desconhecida=True)],
    indicators=[indicator_row(is_abaixo_porte=True)],
    competidores=[competidor_row()],
    markets=[market_row(nu_ano_censo=2025, etapa="bas")],
    share=[share_row(nu_ano_censo=2025, etapa="bas", is_abaixo_porte=True)],
)
c = client(repo)
telas = {
    "busca": c.get("/app/", params={"co_municipio": "3106200"}).text,
    "escola": c.get("/app/escolas/31334243").text,
    "mercado": c.get("/app/mercados/3106200").text,
    "metodologia": c.get("/app/metodologia").text,
}
for nome, html in telas.items():
    for jargao in ("is_oferta_desconhecida", "IS_ABAIXO_PORTE"):
        check(jargao not in html, f"{nome}: sem '{jargao}' visível")

print()
print("=" * 78)
print("E7 — metodologia explica METODOLOGIA_INCOMPARAVEL_2025")
print("=" * 78)
html = telas["metodologia"]
check("METODOLOGIA_INCOMPARAVEL_2025" in html, "código presente")
check("não é diretamente comparável" in html, "explicação presente")
check("Educação profissional e EJA" in html, "escopo do aviso explicado")
m = re.search(r"<dt>Metodologia não comparável[^<]*</dt>\s*<dd>(.*?)</dd>", html, flags=re.S)
if m:
    print("        " + re.sub(r"\s+", " ", m.group(1)).strip()[:300])

print()
print("=" * 78)
print("E8 — /app/escolas/31246018?ano=2020 -> 422")
print("=" * 78)
repo = FakeRepository(history=[history_row(nu_ano_censo=2025)])
resp = client(repo).get("/app/escolas/31246018?ano=2020")
check(resp.status_code == 422, f"status {resp.status_code} (esperado 422)")
check(not [n for n, _ in repo.calls if n == "get_school_history"], "repositório não consultado")
m = re.search(r'<p class="detalhe">(.*?)</p>', resp.text, flags=re.S)
print("        detalhe:", re.sub(r"\s+", " ", m.group(1)).strip() if m else "(n/d)")

print()
print("=" * 78)
print("Transversal — nenhum None/nan nas telas")
print("=" * 78)
vaaz = re.compile(r"\bNone\b|\bnan\b")
for nome, html in telas.items():
    check(not vaaz.search(html), f"{nome}: sem None/nan")

print()
print("=" * 78)
print(f"RESULTADO: {falhas} falha(s)")
print("=" * 78)
raise SystemExit(1 if falhas else 0)
