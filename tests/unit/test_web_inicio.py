"""Hero da landing `/` e painel do recorte — card `t_437796c3` (spec §4, §5, §8).

O painel da coluna direita substitui a foto da referência visual por três
números que saem do **código e da config**, nunca de literal no template:

* municípios de MG — `len(municipios_mg())`, a lista IBGE versionada;
* anos publicados — `settings.anos_disponiveis` (`APP_ANOS_DISPONIVEIS`), em
  faixa quando a lista é contínua e separados por vírgula quando tem buraco;
* etapas e modalidades — chaves de `ETAPAS_ROTULOS` **sem** `"bas"`, que é o
  total oficial do Censo e não uma etapa do mercado.

Nada aqui toca rede ou BigQuery: o HTML vem do `TestClient` com repositório fake
vazio e os testes conferem que `GET /` continua com **0** chamadas ao
repositório. Não existe contagem de escolas porque `COUNT(*)` é proibido
(`repositories/bigquery/pagination.py:1-5`), e por isso não há o que consultar.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.main import create_app
from panorama_api.web import routes as web_routes
from panorama_api.web.municipios import Municipio, municipios_mg
from tests.unit.conftest import (
    FakeRepository,
    market_row,
    municipio_row,
    share_row,
)

ANOS = (2021, 2022, 2023, 2024, 2025)
ANOS_CSV = ",".join(str(ano) for ano in ANOS)
INICIO = "/"

VALOR = re.compile(r"<dd>([^<]*)</dd>")


def _settings(*, anos: str = ANOS_CSV) -> Settings:
    return Settings(
        bq_project="panorama-escola-staging",
        bq_dataset="panorama_serving",
        bq_location="us-central1",
        max_bytes_billed=256 * 1024 * 1024,
        validate_schema_on_startup=False,
        contract_version="mvp-1",
        data_version="dev",
        app_anos_disponiveis=anos,
    )


def _pagina(*, anos: str = ANOS_CSV) -> tuple[str, FakeRepository]:
    """HTML de `/` e o repositório fake que a página recebeu (para contar chamadas)."""
    repo = FakeRepository()
    app = create_app(settings=_settings(anos=anos), repository=repo)
    with TestClient(app) as cliente:
        resposta = cliente.request(
            "GET", INICIO, headers={"Accept": "text/html", "Accept-Encoding": "identity"}
        )

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/html")
    return resposta.text, repo


def _valores(html: str) -> list[str]:
    """Os três números do painel, na ordem em que a página os apresenta."""
    return VALOR.findall(html)


def test_painel_do_recorte_mostra_os_numeros_reais_do_produto():
    html, _ = _pagina()

    # 853 vem da lista versionada, não de um literal no template.
    assert len(municipios_mg()) == 853
    assert _valores(html) == ["853", "2021–2025", "8"]
    for rotulo in (
        "municípios de Minas Gerais",
        "anos do Censo Escolar publicados",
        "etapas e modalidades no mercado",
    ):
        assert rotulo in html
    assert "Fonte: Censo Escolar da Educação Básica (INEP)." in html


def test_painel_e_a_prancha_com_h2_e_lista_de_definicoes():
    """A prancha do design é a seção do recorte: `h2` na fita e `dl` no corpo."""
    html, _ = _pagina()

    assert re.search(r'<figure class="prancha" aria-labelledby="recorte-titulo">', html)
    assert '<h2 id="recorte-titulo">Recorte dos dados</h2>' in html
    assert re.search(r'<dl class="prancha__base">', html)
    # Um `dt` por número, na ordem em que o `dl` os apresenta.
    assert html.count("<dt>") == 3
    assert html.count("<dd>") == 3


def test_anos_continuos_viram_faixa_e_anos_com_buraco_viram_lista():
    continuos, _ = _pagina(anos="2021,2022,2023,2024,2025")
    assert _valores(continuos)[1] == "2021–2025"

    com_buraco, _ = _pagina(anos="2021,2023")
    assert _valores(com_buraco)[1] == "2021, 2023"
    # A faixa prometeria um ano não publicado: nada de "2021–2023".
    assert "2021–2023" not in com_buraco


def test_painel_muda_quando_a_fonte_muda(monkeypatch: pytest.MonkeyPatch):
    """O painel é derivado, não decorado: trocar a fonte muda a página."""
    monkeypatch.setattr(
        web_routes,
        "municipios_mg",
        lambda: (
            Municipio(co_municipio="3106200", no_municipio="Belo Horizonte"),
            Municipio(co_municipio="3100104", no_municipio="Abadia dos Dourados"),
        ),
    )
    monkeypatch.setattr(
        web_routes,
        "ETAPAS_ROTULOS",
        {"bas": "Educação básica (total)", "med": "Ensino médio"},
    )

    html, _ = _pagina()

    assert _valores(html) == ["2", "2021–2025", "1"]


def test_inicio_nao_consulta_o_repositorio():
    """Contar escolas exigiria `COUNT(*)`; o painel não faz nenhuma consulta."""
    _, repo = _pagina()

    assert repo.calls == []


def test_template_nao_carrega_numero_literal_do_painel():
    """Os números saem do código e da config — o template só tem a marcação."""
    fonte = (web_routes.TEMPLATES_DIR / "inicio.html").read_text(encoding="utf-8")

    assert "853" not in fonte
    assert "2021" not in fonte
    for variavel in ("recorte_municipios", "recorte_anos", "recorte_etapas"):
        assert "{{ " + variavel + " }}" in fonte


def _hero(html: str) -> str:
    """Marcação da hero: a `<section class="hero">` com a prancha aninhada dentro."""
    inicio = html.index('<section class="hero"')
    fim_da_prancha = html.index("</figure>", inicio) + len("</figure>")
    fim = html.index("</section>", fim_da_prancha) + len("</section>")
    return html[inicio:fim]


def test_hierarquia_de_titulos_do_hero():
    """Um `<h1>`; a prancha abre nível com `<h2>`, sem pular nível na hero."""
    html, _ = _pagina()
    hero = _hero(html)

    assert hero.count("<h1") == 1
    assert hero.index("<h1") < hero.index("<h2")
    assert hero.count("<h2") == 1
    # Nada de `<h3>` na hero: os capítulos abaixo dela é que abrem nível.
    assert "<h3" not in hero
    assert html.count("<h1") == 1


def test_hero_mostra_a_copy_do_h1_e_do_subtitulo():
    """A copy é a mesma; o `h1` agora tem três `span.hero__linha` (máscara)."""
    html, _ = _pagina()

    h1 = re.search(r"<h1\b[^>]*>(.*?)</h1>", html, re.S)
    assert h1 is not None, "h1 ausente em `/`"
    texto_h1 = re.sub(r"<[^>]+>", " ", h1.group(1))
    assert _texto(texto_h1).strip() == (
        "Escolas e mercados da educação básica em Minas Gerais"
    )
    assert html.count("hero__linha") == 3
    assert (
        "Matrículas, oferta por etapa, rendimento e participação de mercado das "
        "escolas" in html
    )
    assert "a partir do Censo Escolar da Educação Básica (INEP)." in html


# -- busca no hero (card `t_e075a6f6`, spec §6) ------------------------------

FORMULARIO = re.compile(r'<form class="hero__busca"[^>]*>.*?</form>', re.S)


def _formulario(html: str) -> str:
    """Marcação do `<form>` da barra de busca do hero."""
    achado = FORMULARIO.search(html)
    assert achado is not None, "barra de busca do hero ausente em `/`"
    return achado.group(0)


def test_hero_tem_form_get_para_a_busca_com_os_parametros_de_app():
    """O hero não inventa rota: envia o mesmo GET de `/app/` (`q`, município)."""
    html, repo = _pagina()
    form = _formulario(html)

    assert 'method="get"' in form
    assert 'action="/app/"' in form
    assert 'role="search"' in form
    assert 'aria-label="Buscar escolas ou mercado municipal"' in form
    # Nome da escola: rótulo visível, limite do contrato e dica associada.
    assert '<label for="q">Nome da escola</label>' in form
    assert re.search(
        r'<input\s+type="search"\s+id="q"\s+name="q"\s+minlength="3"\s+maxlength="100"',
        form,
    )
    assert 'aria-describedby="q-dica"' in form
    assert 'id="q-dica">Trecho do nome, de 3 a 100 caracteres.</p>' in form
    # Município: a mesma lista versionada da busca, com a opção "todos".
    assert '<label for="co_municipio">Município</label>' in form
    assert '<select id="co_municipio" name="co_municipio">' in form
    assert '<option value="">Todos os municípios de MG</option>' in form
    assert form.count('<option value="31') == len(municipios_mg()) == 853
    # Sem campo de ano (o ano não filtra a busca) e sem `apenas_ativas`.
    assert 'name="ano"' not in form
    assert "apenas_ativas" not in form
    # O select do hero é markup de apoio de tela: nenhuma consulta ao repositório.
    assert repo.calls == []


def test_hero_tem_os_dois_botoes_e_o_segundo_vai_ao_mercado():
    html, _ = _pagina()
    form = _formulario(html)

    assert ">Buscar escolas</button>" in form
    assert ">Ver mercado do município</button>" in form
    # O atalho do mercado é um `<button formaction>` com `formnovalidate`: o
    # `minlength` do nome não pode barrar a ida ao mercado.
    assert 'formaction="/app/mercados"' in form
    assert "formnovalidate" in form
    # Os dois são submit; só o de mercado declara `formaction`/`formnovalidate`.
    assert form.count('type="submit"') == 2
    secundario = form[form.index("botao--secundario") : form.index("formnovalidate")]
    assert 'formaction="/app/mercados"' in secundario
    primario = form[form.index("botao--primario") : form.index("botao--secundario")]
    assert "formaction" not in primario
    assert "formnovalidate" not in primario


def test_hero_mantem_um_unico_h1_e_o_alvo_do_ancora_do_campo_de_nome():
    """O `#q` do campo é o alvo dos links "buscar uma escola" (L4)."""
    html, _ = _pagina()

    assert html.count("<h1") == 1
    assert 'id="q"' in _formulario(html)


# -- conteúdo da landing (card `t_2c2e564b`, spec §5) ------------------------


def _texto(html: str) -> str:
    """HTML com os espaços normalizados.

    O template quebra linha no meio das frases: o que importa é a frase, não o
    ``\\n`` do HTML.
    """
    return re.sub(r"\s+", " ", html)


def test_landing_tem_as_tres_secoes_de_conteudo():
    html, _ = _pagina()

    assert '<h2 id="encontra-titulo">O que você encontra</h2>' in html
    assert '<h2 id="fonte-titulo">De onde vêm os dados</h2>' in html
    assert '<h2 id="publico-titulo">Para quem é</h2>' in html
    # Os três itens da primeira seção abrem nível com `<h3>`.
    for item in ("Ficha da escola", "Mercado municipal", "Metodologia"):
        assert f"<h3>{item}</h3>" in html


def test_copy_dos_itens_e_das_secoes_e_a_do_5():
    plano = _texto(_pagina()[0])

    for frase in (
        "Série de matrículas, oferta por etapa e rendimento. Nas escolas "
        "privadas ativas, também a posição da escola no município.",
        "Tamanho do mercado, composição por etapa e participação das escolas "
        "privadas, ano a ano.",
        "De onde vem cada número, o que cada indicador mede e quais são os "
        "limites de leitura.",
        "Os números vêm do Censo Escolar da Educação Básica, levantamento "
        "anual do INEP que cobre todas as escolas do país. O Panorama Escola "
        "recorta Minas Gerais e publica os anos 2021–2025. Quando um dado não "
        "existe na base, a tela mostra “sem dado”, e nunca zero.",
        "Para quem acompanha a educação básica privada em Minas Gerais: gestão "
        "e expansão de redes, direção de escolas e análise de mercado. O "
        "Panorama não exibe dado individual de aluno.",
    ):
        assert frase in plano, frase


def test_hierarquia_de_titulos_da_landing_nao_pula_nivel():
    html, _ = _pagina()
    niveis = [int(nivel) for nivel in re.findall(r"<h([1-6])[ >]", html)]

    assert niveis.count(1) == 1
    assert niveis[0] == 1
    # Descer de h3 para h2 é legítimo (nova seção); subir de h1 para h3 não é.
    for anterior, seguinte in zip(niveis, niveis[1:]):
        assert seguinte - anterior <= 1, niveis


def test_secao_de_fonte_usa_os_anos_da_config_nao_um_literal():
    plano = _texto(_pagina(anos="2024,2025")[0])

    assert "publica os anos 2024–2025." in plano
    assert "2021" not in plano


def test_links_da_landing_resolvem_no_front():
    """`#q` aponta para um alvo real e as duas rotas de apoio respondem 200."""
    html, _ = _pagina()

    # Os capítulos do design: o link carrega classe, então o alvo é o `href` e o
    # texto, não a tag inteira.
    for href, texto in (
        ("#q", "Buscar uma escola"),
        ("/app/metodologia", "Ler a metodologia"),
        ("/app/mercados/3106200", "Ver o mercado de Belo Horizonte"),
    ):
        assert re.search(
            rf'<a\b[^>]*href="{re.escape(href)}"[^>]*>\s*{re.escape(texto)}', html
        ), (href, texto)
    assert 'id="q"' in html
    assert '<a href="/app/metodologia">Como os números são calculados</a>' in html

    # O exemplo de mercado é um código que existe na lista versionada — a
    # landing não pode apontar para um município inventado.
    municipios = {m.co_municipio: m.no_municipio for m in municipios_mg()}
    assert municipios["3106200"] == "Belo Horizonte"

    repo = FakeRepository(
        municipios=[municipio_row()],
        markets=[
            market_row(nu_ano_censo=ano, etapa="bas") for ano in ANOS
        ],
        share=[share_row(nu_ano_censo=ano) for ano in ANOS],
    )
    app = create_app(settings=_settings(), repository=repo)
    with TestClient(app) as cliente:
        landing = cliente.request(
            "GET", INICIO, headers={"Accept-Encoding": "identity", "Accept": "text/html"}
        )
        # A landing continua sem consultar o repositório (spec §7).
        assert repo.calls == []
        metodologia = cliente.request(
            "GET", "/app/metodologia", headers={"Accept-Encoding": "identity"}
        )
        mercado = cliente.request(
            "GET", "/app/mercados/3106200", headers={"Accept-Encoding": "identity"}
        )

    assert landing.status_code == 200
    assert metodologia.status_code == 200
    assert mercado.status_code == 200
