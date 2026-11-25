#!/usr/bin/env python3
"""Compara os painéis das 3 telas do /app com o cânone V2 (card `t_cbd54a92`).

Busca as telas servidas localmente, extrai os `<h2>` em ordem e compara com
o `ESPERADO` (extraído do protótipo em 2026-11-25); nas telas de `KPI_TELAS`,
exige ainda `div.kpis` com exatamente 4 filhos. Qualquer divergência —
ordem trocada, painel faltando ou painel extra — é falha (saída 1).

Dois modos, ambos sem rede e sem dataset:

* hermético (padrão): sobe o app em memória (`TestClient` + `FakeRepository`
  com fixture própria neste arquivo) — é o modo do gate;
* `--base http://127.0.0.1:8081`: busca as telas de um servidor local já de
  pé (só `urllib` da stdlib, sem dependência nova).

Uso:
    .venv/bin/python scripts/comparar_paineis.py
    .venv/bin/python scripts/comparar_paineis.py --base http://127.0.0.1:8081
"""

from __future__ import annotations

import argparse
import html as html_std
import os
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.request import urlopen

if TYPE_CHECKING:
    from panorama_api.config import Settings
    from tests.unit.conftest import FakeRepository

# O `panorama_api.main` monta o app no import (`app = create_app()`), e
# `APP_ANOS_DISPONIVEIS` é obrigatório por contrato: sem ele, nem a coleta
# dos testes passa (ver `tests/conftest.py`). `setdefault` espelha o conftest —
# um valor já exportado tem precedência.
os.environ.setdefault("APP_ANOS_DISPONIVEIS", "2021,2022,2023,2024,2025")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

ESPERADO = {
    "/app/": ["Filtros de busca", "Resultados"],
    "/app/escolas/31005371": [
        "Série de matrículas",
        "Oferta por etapa",
        "Rendimento",
        "Posição no município",
        "Ranking municipal por matrícula",
    ],
    "/app/mercados/3106200": [
        "Tamanho e composição por etapa",
        "Movimento de escolas",
        "Cobertura e limites",
        "Escolas do mercado por share",
    ],
}
#: Telas que exigem `div.kpis` com 4 filhos.
KPI_TELAS = frozenset({"/app/escolas/31005371", "/app/mercados/3106200"})
FILHOS_KPIS = 4

COTEMIG = "31005371"
MUNICIPIO = "3106200"
ANOS = (2021, 2022, 2023, 2024, 2025)


class PaineisKpis(HTMLParser):
    """Conta filhos diretos (elementos) de cada `div.kpis`.

    Separado do extrator de `<h2>` para manter cada parser de um passo só e
    legível: este mantém uma pilha de (tag, é_kpis, filhos).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.h2s: list[str] = []
        self.kpis_filhos: list[int] = []
        self._em_h2 = False
        self._texto: list[str] = []
        self._pilha: list[tuple[str, bool, int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        e_kpis = False
        if tag == "div":
            classes = dict(attrs).get("class", "") or ""
            e_kpis = "kpis" in classes.split()
        if tag == "h2":
            self._em_h2 = True
            self._texto = []
        if self._pilha:
            pai_tag, pai_kpis, filhos = self._pilha[-1]
            if pai_kpis:
                self._pilha[-1] = (pai_tag, pai_kpis, filhos + 1)
        self._pilha.append((tag, e_kpis, 0))

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self._em_h2:
            texto = html_std.unescape("".join(self._texto))
            texto = " ".join(texto.split())
            if texto:
                self.h2s.append(texto)
            self._em_h2 = False
            self._texto = []
        if not self._pilha:
            return
        # Desempilha até o par (o HTML do app é bem formado; em geral é o topo).
        for i in range(len(self._pilha) - 1, -1, -1):
            if self._pilha[i][0] == tag:
                _, e_kpis, filhos = self._pilha[i]
                del self._pilha[i:]
                if e_kpis:
                    self.kpis_filhos.append(filhos)
                break

    def handle_data(self, data: str) -> None:
        if self._em_h2:
            self._texto.append(data)


def analisar(html: str) -> tuple[list[str], list[int]]:
    parser = PaineisKpis()
    parser.feed(html)
    parser.close()
    return parser.h2s, parser.kpis_filhos


def _fixture() -> tuple[Settings, FakeRepository]:
    """App hermético: `Settings` explícito + `FakeRepository` com a fixture."""
    from panorama_api.config import Settings
    from panorama_api.main import create_app
    from tests.unit.conftest import (
        FakeRepository,
        competidor_row,
        concentracao_row,
        history_row,
        indicator_row,
        market_row,
        municipio_row,
        school_row,
    )

    settings = Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        max_bytes_billed=256 * 1024 * 1024,
        validate_schema_on_startup=False,
        contract_version="mvp-1",
        app_anos_disponiveis=",".join(str(a) for a in ANOS),
    )
    matriculas = {2021: 420, 2022: 455, 2023: 501, 2024: 540, 2025: 680}
    repository = FakeRepository(
        schools=[
            school_row(co_entidade=COTEMIG, no_entidade="COL COTEMIG BARROCA")
        ],
        history=[
            history_row(
                co_entidade=COTEMIG,
                nu_ano_censo=ano,
                tp_dependencia="4",
                tp_situacao_funcionamento="1",
                qt_mat_bas=matriculas[ano],
                qt_mat_creche=0,
                qt_mat_med=matriculas[ano],
                of_creche=0,
                of_med=1,
            )
            for ano in ANOS
        ],
        indicators=[
            indicator_row(
                co_entidade=COTEMIG,
                qt_mat_bas=680,
                qt_mat_creche=0,
                qt_mat_med=680,
                crescimento_yoy_pct=12.4,
                rank_crec_municipio=487,
                rank_crec_mg=2134,
            )
        ],
        competidores=[competidor_row(co_entidade=COTEMIG)],
        municipios=[municipio_row()],
        markets=[
            market_row(nu_ano_censo=ano, etapa=etapa)
            for ano in ANOS
            for etapa in ("bas", "creche", "med")
        ],
        concentracao=[concentracao_row(nu_ano_censo=2025)],
    )
    return settings, repository


def _buscar_hermetico() -> dict[str, str]:
    from fastapi.testclient import TestClient

    from panorama_api.main import create_app

    settings, repository = _fixture()
    paginas: dict[str, str] = {}
    with TestClient(create_app(settings=settings, repository=repository)) as cliente:
        for caminho in ESPERADO:
            resposta = cliente.get(caminho)
            assert resposta.status_code == 200, f"{caminho}: {resposta.status_code}"
            tipo = resposta.headers.get("content-type", "")
            assert tipo.startswith("text/html"), f"{caminho}: {tipo}"
            paginas[caminho] = resposta.text
    return paginas


def _buscar_base(base: str) -> dict[str, str]:
    paginas: dict[str, str] = {}
    for caminho in ESPERADO:
        url = base.rstrip("/") + caminho
        with urlopen(url, timeout=10) as resposta:  # noqa: S310 (base local)
            corpo = resposta.read().decode("utf-8")
        paginas[caminho] = corpo
    return paginas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default=None,
        help="base de um servidor local (ex.: http://127.0.0.1:8081); "
        "sem ela, sobe o app hermético em memória",
    )
    args = parser.parse_args()
    paginas = _buscar_base(args.base) if args.base else _buscar_hermetico()

    falhas = 0
    for caminho, esperado in ESPERADO.items():
        h2s, kpis = analisar(paginas[caminho])
        if h2s != esperado:
            falhas += 1
            print(f"DIVERGÊNCIA {caminho}")
            print(f"  esperado: {esperado}")
            print(f"  obtido:   {h2s}")
            faltando = [h for h in esperado if h not in h2s]
            extras = [h for h in h2s if h not in esperado]
            if faltando:
                print(f"  faltando: {faltando}")
            if extras:
                print(f"  extras:   {extras}")
        else:
            print(f"OK {caminho} ({len(h2s)} painéis na ordem)")
        if caminho in KPI_TELAS:
            if len(kpis) != 1 or kpis[0] != FILHOS_KPIS:
                falhas += 1
                print(
                    f"DIVERGÊNCIA {caminho}: div.kpis com filhos {kpis}, "
                    f"esperado exatamente [{FILHOS_KPIS}]"
                )
            else:
                print(f"OK {caminho} (div.kpis com {FILHOS_KPIS} filhos)")
    if falhas:
        print(f"\nFALHOU: {falhas} divergência(s)")
        return 1
    print("\nOK: 3 telas conferem com o cânone (h2 em ordem + KPIs).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
