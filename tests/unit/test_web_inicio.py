"""Landing `/` — estrutura literal do protótipo, valores do repositório.

O protótipo (`panorama-escola-landing.html`) continua sendo a especificação
de estrutura e copy (card `t_e42049c1`): classes, `id`, `aria-*`,
`data-reveal`, `data-od-id` — tudo verbatim. Os valores que eram mock do
protótipo agora vêm do repositório (card `t_e06e1ad5`), no recorte fixo da
landing (Belo Horizonte, maior ano de `APP_ANOS_DISPONIVEIS`, etapa padrão):

* a escola em destaque e as 5 barras saem de um `get_market_share`;
* a posição ("1º de N") e o KPI de escolas saem de um `get_market`;
* o KPI "4 maiores" sai do `c4_pct` de um `get_concentracao`;
* o nome do município vem de `municipios_mg()` (lista versionada, sem custo);
* série histórica e variação anual estão fora do orçamento de consultas —
  saem como "sem dado" explícito, nunca recomputadas, nunca `0`.

Regras que este arquivo trava sobre o HTML renderizado de verdade
(``TestClient`` com repositório fake, nenhuma rede/BigQuery):

* no máximo 3 consultas ao repositório por render, com cache em processo
  por `DATA_VERSION`;
* falha do repositório mantém `/` em `200`, com "sem dado" nos blocos;
* repositório vazio mostra "sem dado" — nunca `0`, nunca nome/valor mock.

O que saiu com a troca dos mocks por dado real (e por que cada remoção tem
substituto aqui):

* painel do recorte derivado (`recorte_*`) — o design mostra os literais do
  protótipo; a asserção equivalente é a copy literal abaixo;
* barra de busca do hero (`form.hero__busca`) — o protótipo tem zero `<form>`
  e zero `<input>`; a asserção equivalente é `test_zero_form_e_input`;
* os 8 literais do protótipo (`Monte Verde`, `1.140`, `+4,9%`, a série do
  `<desc>`, `1º de 30`, `11,0%`, `amostra ilustrativa`, `21,6%`, `Rede
  Horizonte`) — viraram dado real ou "sem dado"; a asserção equivalente é
  `test_repo_vazio_nao_traz_mock` + `test_valores_vem_do_repositorio`.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from panorama_api.config import Settings
from panorama_api.main import create_app
from tests.unit.conftest import (
    FakeRepository,
    concentracao_row,
    market_row,
    municipio_row,
    share_row,
)

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


def _pagina(
    *, anos: str = ANOS_CSV, repo: FakeRepository | None = None
) -> tuple[str, FakeRepository]:
    """HTML de `/` e o repositório fake que a página recebeu (para contar chamadas)."""
    repositorio = repo if repo is not None else FakeRepository()
    app = create_app(settings=_settings(anos=anos), repository=repositorio)
    with TestClient(app) as cliente:
        resposta = cliente.request(
            "GET", INICIO, headers={"Accept": "text/html", "Accept-Encoding": "identity"}
        )

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/html")
    return resposta.text, repositorio


def _repo_cheio() -> FakeRepository:
    """Fake com o recorte da landing: top-5 de BH/2025, mercado e C4 reais."""
    return FakeRepository(
        municipios=[municipio_row()],
        markets=[market_row(nu_ano_censo=2025, etapa="bas")],
        concentracao=[concentracao_row(nu_ano_censo=2025, etapa="bas")],
        share=[
            share_row(
                id_entidade=f"3100000{i}",
                no_entidade=nome,
                mat_entidade=matricula,
                share_privado_pct=share,
                nu_ano_censo=2025,
            )
            for i, (nome, matricula, share) in enumerate(
                (
                    ("Escola Alfa", 1140.0, 11.0),
                    ("Escola Beta", 830.0, 8.3),
                    ("Escola Gama", 690.0, 6.9),
                    ("Escola Delta", 630.0, 6.3),
                    ("Escola Epsilon", 530.0, 5.3),
                ),
                start=1,
            )
        ],
    )


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


def test_valores_vem_do_repositorio():
    """Prancha, barras e KPIs mostram o recorte real (BH/2025/etapa padrão)."""
    html, _ = _pagina(repo=_repo_cheio())
    plano = _texto(html)

    # Prancha: destaque é a 1ª do share; posição usa o total de privadas.
    assert "Prancha 01 · Belo Horizonte" in plano
    assert "Escola Alfa — matrícula total" in plano
    assert "1.140" in html
    assert "1º de 30" in plano
    assert "11,0%" in html
    assert "Fonte: Censo Escolar (INEP) · 2025" in html
    # Barras: o top-5 real, na ordem do share.
    for nome, share in (
        ("Escola Alfa", "11,0%"),
        ("Escola Beta", "8,3%"),
        ("Escola Gama", "6,9%"),
        ("Escola Delta", "6,3%"),
        ("Escola Epsilon", "5,3%"),
    ):
        assert nome in html, nome
        assert share in html, share
    assert html.count('class="barras__valor"') == 5
    # KPIs: total de privadas do `get_market`, C4 do `get_concentracao`.
    assert "escolas privadas no mercado de Belo Horizonte" in plano
    assert "participação somada das 4 maiores escolas" in plano
    assert "60,0" in html
    # Leituras do design continuam no lugar, com os nomes reais.
    assert "Ranking municipal" in html
    assert "Oferta por etapa" in html
    assert html.count('class="matriz__linha"') == 7


def test_repo_vazio_nao_traz_mock():
    """Sem dado no repositório: 'sem dado' explícito — nunca `0`, nunca mock."""
    html, _ = _pagina()
    plano = _texto(html)

    assert "sem dado" in plano
    for mock in (
        "Monte Verde",
        "Rede Horizonte",
        "amostra",
        "ilustrativ",
        "1.140",
        "+4,9%",
        "1º de 30",
        "11,0%",
        "8,3%",
        "21,6",
    ):
        assert mock not in html, mock
    # "sem dado" não vaza como zero em nenhum contador do design.
    assert ">0<" not in html
    # A estrutura das leituras continua — só os valores caem para "sem dado".
    assert html.count('class="barras__valor"') == 5
    assert html.count('class="matriz__linha"') == 7


# -- estrutura do design (critérios 2, 5, 6, 7, 8) ----------------------------


def test_data_reveal_presente_28_vezes():
    html, _ = _pagina()

    assert html.count("data-reveal") == 28


def test_contadores_e_observadores_do_design():
    """Os 5 `data-contar` do design, com o número real (vazio = sem dado)."""
    html, _ = _pagina(repo=_repo_cheio())

    assert html.count("data-contar") == 5
    for alvo in ('data-contar="1140"', 'data-contar="853"', 'data-contar="5"',
                 'data-contar="30"', 'data-contar="60"'):
        assert alvo in html, alvo
    assert 'data-decimais="1"' in html
    assert html.count("data-observar") == 2


def test_contadores_vazios_nao_animam_nem_zeram():
    """Sem dado: `data-contar` vazio (o `landing.js` ignora NaN)."""
    html, _ = _pagina()

    assert html.count("data-contar") == 5
    assert html.count('data-contar=""') == 3
    assert "sem dado" in html


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
        metodologia = cliente.request(
            "GET", "/app/metodologia", headers={"Accept-Encoding": "identity"}
        )
        mercado = cliente.request(
            "GET", "/app/mercados/3106200", headers={"Accept-Encoding": "identity"}
        )

    assert landing.status_code == 200
    assert metodologia.status_code == 200
    assert mercado.status_code == 200


# -- contrato de consultas da landing (card `t_e06e1ad5`) ---------------------

METODOS_LANDING = frozenset({"get_market_share", "get_market", "get_concentracao"})


def test_inicio_consulta_no_maximo_3_vezes_por_render():
    """A landing consulta o repositório — no máximo 3 vezes, só o recorte fixo."""
    _, repo = _pagina(repo=_repo_cheio())

    assert 1 <= len(repo.calls) <= 3, repo.calls
    assert {nome for nome, _ in repo.calls} <= METODOS_LANDING, repo.calls
    for _, kwargs in repo.calls:
        assert kwargs["co_municipio"] == "3106200", kwargs
        assert kwargs["ano"] == ANOS[-1], kwargs
        assert kwargs["etapa"] == "bas", kwargs


def test_segundo_render_reaproveita_o_cache_por_data_version():
    """O cache em processo zera o custo do render seguinte (mesma versão)."""
    repo = _repo_cheio()
    app = create_app(settings=_settings(), repository=repo)
    with TestClient(app) as cliente:
        for _ in range(2):
            resposta = cliente.request(
                "GET",
                INICIO,
                headers={"Accept": "text/html", "Accept-Encoding": "identity"},
            )
            assert resposta.status_code == 200

    assert 1 <= len(repo.calls) <= 3, repo.calls


def test_falha_do_repositorio_mantem_200_com_sem_dado():
    """BigQuery fora: `/` continua 200 e cada bloco cai para 'sem dado'."""
    repo = _repo_cheio()
    repo.errors = {
        "get_market_share": RuntimeError("bigquery fora"),
        "get_market": RuntimeError("bigquery fora"),
        "get_concentracao": RuntimeError("bigquery fora"),
    }
    with TestClient(create_app(settings=_settings(), repository=repo)) as cliente:
        resposta = cliente.request(
            "GET", INICIO, headers={"Accept": "text/html", "Accept-Encoding": "identity"}
        )

    assert resposta.status_code == 200
    assert "sem dado" in resposta.text
    for mock in ("Monte Verde", "Rede Horizonte", "amostra", "ilustrativ"):
        assert mock not in resposta.text, mock
