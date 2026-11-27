"""Landing `/` literal ao protótipo — card `t_e42049c1` (Regra Zero).

O protótipo (`panorama-escola-landing.html`) é a especificação: copy, ordem,
classes, `id`, `aria-*`, `data-reveal`, `data-od-id` — tudo verbatim. Este
arquivo trava o literal sobre o HTML renderizado de verdade (``TestClient``
com repositório fake, nenhuma rede/BigQuery) e que `/` continua sem consultar
o repositório (os números do design são literais do protótipo).

O que saiu com o porte literal (e por quê cada remoção tem substituto aqui):

* painel do recorte derivado (`recorte_*`) — o design mostra os literais do
  protótipo; a asserção equivalente é a copy literal abaixo;
* barra de busca do hero (`form.hero__busca`) — o protótipo tem zero `<form>`
  e zero `<input>`; a asserção equivalente é `test_zero_form_e_input`;
* proibição de números ilustrativos — revogada pela Regra Zero: os literais
  do design entram, e a asserção equivalente é a presença deles.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.main import create_app
from tests.unit.conftest import FakeRepository

ANOS = (2021, 2022, 2023, 2024, 2025)
ANOS_CSV = ",".join(str(ano) for ano in ANOS)
INICIO = "/"

#: Os 8 ganchos de observação do design (`landing.js` usa `data-od-id` só
#: como marcador; o que importa é estarem todos no DOM).
DATA_OD_IDS = (
    "nav-abrir-prototipo",
    "hero-cta",
    "capitulo-busca",
    "capitulo-mercado",
    "capitulo-rede",
    "leitura-ranking",
    "leitura-oferta",
    "fecho-cta",
)


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


def _texto(html: str) -> str:
    """HTML com os espaços normalizados (o template quebra linha no meio das frases)."""
    return re.sub(r"\s+", " ", html)


# -- copy literal do protótipo (critério 1) ----------------------------------


def test_h1_e_a_copy_literal_do_prototipo():
    html, _ = _pagina()

    h1 = re.search(r"<h1\b[^>]*>(.*?)</h1>", html, re.S)
    assert h1 is not None, "h1 ausente em `/`"
    texto_h1 = re.sub(r"<[^>]+>", " ", h1.group(1))
    assert _texto(texto_h1).strip() == (
        "O mercado escolar de Minas, lido por dentro."
    )
    assert "<em>lido por dentro.</em>" in h1.group(1)
    assert html.count("hero__linha") == 3


def test_lead_do_hero_e_literal():
    html, _ = _pagina()

    lead = re.search(r'<p class="hero__lead"[^>]*>(.*?)</p>', html, re.S)
    assert lead is not None, "lead do hero ausente em `/`"
    texto_lead = re.sub(r"<[^>]+>", " ", lead.group(1))
    texto_lead = re.sub(r"\s+([.,;:])", r"\1", texto_lead)
    assert _texto(texto_lead).strip() == (
        "Matrícula, participação e concorrência em 853 municípios. "
        "Cinco anos de Censo Escolar organizados para responder uma pergunta "
        "por vez — com a ressalva de cada número visível ao lado dele."
    )
    assert "<strong>853 municípios</strong>" in lead.group(1)


def test_copy_das_secoes_e_literal():
    plano = _texto(_pagina()[0])

    for frase in (
        "Três entradas, nenhuma ordem obrigatória.",
        "O instrumento foi desenhado para ser percorrido nos dois sentidos: "
        "do município para as escolas, da escola para o mercado em volta. "
        "Cada tela carrega o recorte que a trouxe.",
        "Filtre por nome, município, etapa e situação; ordene a tabela pelo "
        "que importa e abra a ficha sem perder o recorte.",
        "Tamanho, composição por etapa e ranking de participação do privado, "
        "ano a ano, no município escolhido.",
        "Quatro unidades lidas em conjunto: matrícula somada, participação "
        "no município e cobertura de etapas de cada uma.",
        "Cada número carrega a própria ressalva.",
        "Sem dado não é zero.",
        "Não existe um mercado escolar mineiro. Existem 853 mercados "
        "municipais — e cada um tem o seu líder.",
        "O que o Panorama se recusa a fazer.",
        "Quatro decisões de leitura que valem mais do que qualquer gráfico: "
        "elas definem quando um número pode ser dito e quando a resposta "
        "honesta é “sem dado”.",
        "Não estima onde o dado não existe.",
        "Não soma o que não soma.",
        "Não chama retenção de evasão.",
        "Não compara estados.",
        "Comece pelo município. Ou pela escola que você já tem em mente.",
        "Cinco telas navegáveis, sem backend. Leva menos de dois minutos "
        "para chegar ao primeiro número.",
    ):
        assert frase in plano, frase


def test_numeros_e_leituras_do_design_estao_na_pagina():
    html, _ = _pagina()

    for literal in (
        "1.140",
        "+4,9% no ano",
        "Prancha 01 · Belo Horizonte",
        "Colégio Monte Verde",
        "1º de 30",
        "11,0%",
        "8,3%",
        "21,6",
        "Rede Horizonte",
        "Ranking municipal",
        "Oferta por etapa",
        "amostra ilustrativa",
    ):
        assert literal in html, literal
    assert html.count('class="barras__valor"') == 5
    assert html.count('class="matriz__linha"') == 7


# -- estrutura do design (critérios 2, 5, 6, 7, 8) ----------------------------


def test_data_reveal_presente_28_vezes():
    html, _ = _pagina()

    assert html.count("data-reveal") == 28


def test_contadores_e_observadores_do_design():
    html, _ = _pagina()

    assert html.count("data-contar") == 5
    for alvo in ('data-contar="1140"', 'data-contar="853"', 'data-contar="5"',
                 'data-contar="30"', 'data-contar="21.6"'):
        assert alvo in html, alvo
    assert 'data-decimais="1"' in html
    assert html.count("data-observar") == 2


def test_data_od_ids_do_design():
    html, _ = _pagina()

    for gancho in DATA_OD_IDS:
        assert f'data-od-id="{gancho}"' in html, gancho


def test_zero_form_e_input_na_landing():
    """O protótipo não tem `<form>` nem `<input>`: a busca do hero saiu."""
    html, _ = _pagina()

    assert not re.search(r"<form\b", html)
    assert not re.search(r"<input\b", html)


def test_navbar_e_a_lnav_do_design():
    html, _ = _pagina()

    assert 'class="lnav"' in html
    assert '<header class="lnav" id="nav" data-compacto="false">' in html
    assert '<a class="marca" href="/"' in html
    assert '<nav class="lnav__links" aria-label="Seções da página">' in html
    for ancora in ("#instrumento", "#capitulos", "#metodo"):
        assert f'href="{ancora}"' in html
    assert 'class="lnav__cta"' in html
    assert 'id="progresso"' in html
    # A navbar do app não aparece em `/` (fica nas outras telas).
    assert 'class="topo"' not in html
    assert "Navegação principal" not in html


def test_rodape_e_o_rodape_do_design():
    html, _ = _pagina()

    assert 'class="rodape"' in html
    assert 'class="rodape__nota"' in html
    assert 'aria-label="Links do rodapé"' in html
    # O rodapé do app não aparece em `/` (fica nas outras telas).
    assert "rodape-final" not in html
    # Sem a faixa de protótipo (diz "números ilustrativos", falso no app).
    assert "faixa-prototipo" not in html


def test_zero_style_inline_na_landing():
    """Os 40 `style=` do protótipo viraram `:nth-child()` no `landing.css`."""
    html, _ = _pagina()

    assert not re.search(r"\sstyle\s*=", html)


def test_sem_script_do_prototipo_e_com_o_vendorizado():
    html, _ = _pagina()

    assert "assets/js/" not in html
    assert html.count("<script") == 2
    assert re.search(r'<script src="/app/static/[0-9a-f]{12}-landing\.js" defer>', html)


def test_shell_do_design_sem_shell_do_app():
    html, _ = _pagina()

    assert '<body class="land">' in html
    assert '<main class="envoltorio" id="conteudo">' in html
    assert html.count("<h1") == 1
    # Marcas do shell antigo que não existem no protótipo.
    assert "id=\"q\"" not in html
    assert "Recorte dos dados" not in html


def test_hierarquia_de_titulos_nao_pula_nivel():
    html, _ = _pagina()
    niveis = [int(nivel) for nivel in re.findall(r"<h([1-6])[ >]", html)]

    assert niveis.count(1) == 1
    assert niveis[0] == 1
    for anterior, seguinte in zip(niveis, niveis[1:]):
        assert seguinte - anterior <= 1, niveis


# -- links e rotas (só rotas do app, sem origem nova) --------------------------


def test_ctas_do_hero_e_do_fecho_apontam_para_o_app():
    html, _ = _pagina()

    assert 'href="/app/" data-od-id="hero-cta"' in html
    assert 'href="/app/escolas/31005371"' in html
    assert 'href="/app/" data-od-id="fecho-cta"' in html
    assert 'href="/">Ver o sumário das telas</a>' in html


def test_capitulos_apontam_para_as_rotas_do_app():
    html, _ = _pagina()

    assert 'href="/app/" data-od-id="capitulo-busca"' in html
    assert 'href="/app/mercados/3106200" data-od-id="capitulo-mercado"' in html
    # Sem rota de redes no app: o terceiro capítulo cai na metodologia.
    assert 'href="/app/metodologia" data-od-id="capitulo-rede"' in html


def test_rodape_aponta_para_as_rotas_do_app():
    html, _ = _pagina()

    for href in ("/app/", "/app/mercados/", "/app/mercados/3106200",
                 "/app/metodologia", 'href="/">Sumário</a>'):
        assert href in html, href


def test_marquise_duplica_a_sequencia_e_e_decorativa():
    html, _ = _pagina()

    abertura = re.search(r'<div class="marquee[^"]*"[^>]*>', html)
    assert abertura is not None, "marquise ausente em `/`"
    assert 'aria-hidden="true"' in abertura.group(0)
    corpo = html[abertura.end() : html.index("</section>", abertura.end())]
    nomes = re.findall(r"<span>([^<]+)</span>", corpo)
    assert nomes, "marquise sem município"
    assert len(nomes) % 2 == 0
    metade = len(nomes) // 2
    assert nomes[:metade] == nomes[metade:], "marquee do design repete a sequência 2×"
    assert not re.search(r"\d", "".join(nomes)), nomes


def test_links_internos_da_landing_resolvem_no_front():
    from panorama_api.web.municipios import municipios_mg
    from tests.unit.conftest import market_row, municipio_row, share_row

    municipios = {m.co_municipio: m.no_municipio for m in municipios_mg()}
    assert municipios["3106200"] == "Belo Horizonte"

    repo = FakeRepository(
        municipios=[municipio_row()],
        markets=[market_row(nu_ano_censo=ano, etapa="bas") for ano in ANOS],
        share=[share_row(nu_ano_censo=ano) for ano in ANOS],
    )
    app = create_app(settings=_settings(), repository=repo)
    with TestClient(app) as cliente:
        landing = cliente.request(
            "GET", INICIO, headers={"Accept-Encoding": "identity", "Accept": "text/html"}
        )
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


def test_inicio_nao_consulta_o_repositorio():
    """A landing é literal do protótipo: nenhuma consulta ao repositório."""
    _, repo = _pagina()

    assert repo.calls == []
