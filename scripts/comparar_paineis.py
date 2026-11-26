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
from typing import TYPE_CHECKING, Sequence
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

#: Esqueleto do DOM da busca (card V3 `t_9f384f60`, critério 1): filhos de
#: `main`, de cada `section.painel` e do `form#form-busca`, exatamente como
#: no esqueleto-alvo do spec. Ordem trocada, elemento faltando ou extra =
#: falha. A chave usa `q=colegio` para que a página venha com linhas (sem
#: critério não há consulta e a seção de resultados muda de forma).
ESQUELETO = {
    "/app/?q=colegio": {
        "main": [
            "div.tela-topo",
            "section.painel.painel--inicial",
            "section.painel",
            "footer.rodape-final",
        ],
        "filtros": [
            "div.painel__cabecalho",
            "form#form-busca",
        ],
        "form-busca": [
            "div.filtros",
            "div.filtros.filtros--3",
            "div.acoes-filtro",
            "p.retorno#retorno",
            "div.chips#chips",
        ],
        "resultados": [
            "div.painel__cabecalho",
            "div.tabela-rolagem",
            "nav.paginacao",
            "dl.rodape-meta",
        ],
    }
}

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


class Esqueleto(HTMLParser):
    """Árvore mínima (tag + atributos + filhos) para assinar filhos diretos.

    Só elementos viram nó; texto é ignorado, porque o esqueleto compara
    estrutura (tag, classes em ordem, `id`), nunca copy.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.raiz: dict = {"tag": "raiz", "attrs": {}, "filhos": []}
        self._pilha: list[dict] = [self.raiz]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        no: dict = {"tag": tag, "attrs": dict(attrs), "filhos": []}
        self._pilha[-1]["filhos"].append(no)
        self._pilha.append(no)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        no: dict = {"tag": tag, "attrs": dict(attrs), "filhos": []}
        self._pilha[-1]["filhos"].append(no)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._pilha) - 1, 0, -1):
            if self._pilha[i]["tag"] == tag:
                del self._pilha[i:]
                break


def _assinatura(no: dict) -> str:
    """`tag.classes#id` (classes na ordem do HTML, `id` só quando há)."""
    pedacos = [no["tag"]]
    for classe in (no["attrs"].get("class") or "").split():
        pedacos.append(f".{classe}")
    identidade = no["attrs"].get("id")
    if identidade:
        pedacos.append(f"#{identidade}")
    return "".join(pedacos)


def _casa(no: dict, *, tag: str, classe: str | None = None) -> bool:
    if no["tag"] != tag:
        return False
    return classe is None or classe in (no["attrs"].get("class") or "").split()


def _secoes_do_main(raiz: dict) -> tuple[dict | None, list[dict]]:
    principal = None
    pilha = [raiz]
    while pilha:
        no = pilha.pop()
        if _casa(no, tag="main"):
            principal = no
            break
        pilha.extend(no["filhos"])
    secoes = (
        [f for f in principal["filhos"] if _casa(f, tag="section", classe="painel")]
        if principal is not None
        else []
    )
    return principal, secoes


def conferir_esqueleto(caminho: str, html: str) -> list[str]:
    """Filhos de `main`, de cada `section.painel` e do `form#form-busca`.

    Devolve a lista de divergências (vazia = confere com o ESQUELETO).
    """
    esperado = ESQUELETO[caminho]
    parser = Esqueleto()
    parser.feed(html)
    parser.close()
    principal, secoes = _secoes_do_main(parser.raiz)
    reais = {"main": [], "filtros": [], "form-busca": [], "resultados": []}
    if principal is not None:
        reais["main"] = [_assinatura(f) for f in principal["filhos"]]
    formulario = None
    if len(secoes) == 2:
        reais["filtros"] = [_assinatura(f) for f in secoes[0]["filhos"]]
        reais["resultados"] = [_assinatura(f) for f in secoes[1]["filhos"]]
        for filho in secoes[0]["filhos"]:
            if filho["tag"] == "form" and filho["attrs"].get("id") == "form-busca":
                formulario = filho
    if formulario is not None:
        reais["form-busca"] = [_assinatura(f) for f in formulario["filhos"]]
    divergencias = []
    for chave, lista_esperada in esperado.items():
        if reais[chave] != lista_esperada:
            divergencias.append(
                f"{caminho} [{chave}]\n"
                f"  esperado: {lista_esperada}\n"
                f"  obtido:   {reais[chave]}"
            )
    return divergencias


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
            school_row(co_entidade=COTEMIG, no_entidade="COL COTEMIG BARROCA"),
            # Casa `q=colegio` do ESQUELETO (critério 1 do card da busca).
            school_row(co_entidade="31009999", no_entidade="COLEGIO EXEMPLO"),
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
        for caminho in list(ESPERADO) + list(ESQUELETO):
            resposta = cliente.get(caminho)
            assert resposta.status_code == 200, f"{caminho}: {resposta.status_code}"
            tipo = resposta.headers.get("content-type", "")
            assert tipo.startswith("text/html"), f"{caminho}: {tipo}"
            paginas[caminho] = resposta.text
    return paginas


def _buscar_base(base: str) -> dict[str, str]:
    paginas: dict[str, str] = {}
    for caminho in list(ESPERADO) + list(ESQUELETO):
        url = base.rstrip("/") + caminho
        with urlopen(url, timeout=10) as resposta:  # noqa: S310 (base local)
            corpo = resposta.read().decode("utf-8")
        paginas[caminho] = corpo
    return paginas


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default=None,
        help="base de um servidor local (ex.: http://127.0.0.1:8081); "
        "sem ela, sobe o app hermético em memória",
    )
    # `argv=None` lê `sys.argv` (uso como script); o gate hermético chama
    # `main([])` — sem isso, os argumentos do pytest vazariam para cá.
    args = parser.parse_args(argv)
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
    for esqueleto_caminho in ESQUELETO:
        divergencias = conferir_esqueleto(esqueleto_caminho, paginas[esqueleto_caminho])
        for divergencia in divergencias:
            falhas += 1
            print(f"DIVERGÊNCIA {divergencia}")
        if not divergencias:
            print(f"OK {esqueleto_caminho} (esqueleto confere)")
    if falhas:
        print(f"\nFALHOU: {falhas} divergência(s)")
        return 1
    print("\nOK: 3 telas conferem com o cânone (h2 em ordem + KPIs).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
