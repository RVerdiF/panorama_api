"""Rota `/app/escolas/{co_entidade}/concorrencia` (NAV-2; spec §2.2, §5.1, §5.2).

Indicadores e comparação municipal saíram da abertura da ficha e viraram rota
própria. Este arquivo cobre o que o card exige como verificável — sobre o HTML
renderizado de verdade (``TestClient`` + repositório fake, sem rede/BigQuery):

* **duas** consultas: `get_school_indicators` + `get_school_competidores`, e
  nenhum `get_school_history` (o cabeçalho vem de indicadores);
* a comparação sai da **mesma** resposta de indicadores (`items[-1].competicao`):
  não existe segunda chamada a `concorrentes_escola` nem leitura duplicada da
  mart;
* rótulos do F11 preservados ("crescimento anual" com a direção da posição,
  definição da concorrência, rank municipal/MG);
* `competicao` ausente no ano mais recente → "sem dado" + motivo com o ano;
  nunca `0` no lugar (AGENTS.md §6);
* escola pública/inativa → 200 "não se aplica" + volta para a Visão geral;
* 404 de escola inexistente, 422 em `?ano=`, 503 inteiro com `Retry-After`;
* `aria-current="page"` no item da rota e breadcrumb com a seção atual;
* revalidação com `If-None-Match` → 304 com `calls == []`.

Os testes de indicadores/comparação que viviam em `test_web_escola.py` foram
movidos para cá (não apagados): é a rota que agora os renderiza.
"""

from __future__ import annotations

import re

import pytest

from panorama_api.core.errors import UpstreamUnavailable
from panorama_api.web.filters import fmt_gap_lider
from tests.unit.conftest import competidor_row, history_row, indicator_row, school_row

ESCOLA = "31000001"
VISAO_GERAL_URL = f"/app/escolas/{ESCOLA}"
CONCORRENCIA = f"{VISAO_GERAL_URL}/concorrencia"

#: Chamadas ao repositório esperadas nesta rota (2), na ordem do serviço.
CHAMADAS_ESPERADAS = ["get_school_indicators", "get_school_competidores"]

#: Teto de peso pedido pelo card.
TETO_HTML_BYTES = 25 * 1024

#: Escola real do card F11 (COL COTEMIG BARROCA, BH): `qt_mat_creche = 0` e
#: posição nos rankings de **crescimento** (`rank_crec_municipio = 487`,
#: `rank_crec_mg = 2.134`). É a evidência que separa "creche" de "crescimento".
COTEMIG = "31005371"
COTEMIG_CONCORRENCIA = f"/app/escolas/{COTEMIG}/concorrencia"

#: Rótulos exigidos pelo card: crescimento anual + direção da posição.
POSICAO_MUNICIPIO = (
    "Posição por crescimento anual da matrícula no município "
    "(1.º = maior crescimento ano a ano)"
)
POSICAO_MG = (
    "Posição por crescimento anual da matrícula em Minas Gerais "
    "(1.º = maior crescimento ano a ano)"
)
#: Motivo da ausência de comparação, com o ano dos indicadores.
MOTIVO_SEM_COMPARACAO = "sem linha de comparação municipal para 2025"
#: Motivo quando a escola É privada ativa mas a mart não tem a linha do ano.
MOTIVO_SECAO_INDICADORES = (
    "Os indicadores só existem para escolas privadas ativas com matrícula da "
    "educação básica observada no ano de referência."
)
#: Motivo de quem está **fora** do universo de privadas ativas.
MOTIVO_FORA_UNIVERSO = (
    "Indicadores e comparação municipal existem apenas para escolas privadas "
    "ativas (universo privadas_ativas_mg)."
)


def _html(response, status: int = 200) -> str:
    assert response.status_code == status, response.text[:400]
    assert response.headers["content-type"].startswith("text/html")
    return response.text


def _leituras(repository) -> list[str]:
    """Leituras de dado da requisição (o `get_table_columns` é do boot)."""
    return [
        nome
        for nome in repository.methods_called()
        if nome != "get_table_columns"
    ]


def _serie_cotemig() -> list[dict]:
    """Série mínima da 31005371 (privada ativa) — o cabeçalho da rota não a usa."""
    return [
        history_row(
            co_entidade=COTEMIG,
            nu_ano_censo=2025,
            tp_dependencia="4",
            tp_situacao_funcionamento="1",
        )
    ]


def _indicador_cotemig(**overrides) -> dict:
    """Linha de `mart_escola_indicadores` da 31005371 (números do diagnóstico)."""
    valores = {
        "co_entidade": COTEMIG,
        "qt_mat_bas": 680,
        "qt_mat_creche": 0,
        "qt_mat_med": 680,
        "qt_mat_prof": 680,
        "qt_mat_esp": 21,
        "crescimento_yoy_pct": 12.4,
        "rank_crec_municipio": 487,
        "rank_crec_mg": 2134,
    }
    valores.update(overrides)
    return indicator_row(**valores)


def _cotemig(client, repository) -> str:
    """HTML da rota de concorrência da 31005371 (com comparação municipal)."""
    repository.schools = [
        school_row(co_entidade=COTEMIG, no_entidade="COL COTEMIG BARROCA")
    ]
    repository.history = _serie_cotemig()
    repository.indicators = [_indicador_cotemig()]
    repository.competidores = [competidor_row(co_entidade=COTEMIG)]
    return _html(client.get(COTEMIG_CONCORRENCIA))


def _valor_da_definicao(html: str, termo: str) -> str:
    """Texto do `<dd>` imediatamente após o `<dt>` cujo texto é `termo`."""
    achado = re.search(
        rf"<dt>{re.escape(termo)}</dt>\s*<dd>(.*?)</dd>", html, flags=re.S
    )
    assert achado is not None, f"linha ausente na página: {termo!r}"
    return re.sub(r"<[^>]+>", "", achado.group(1)).strip()


def _gap_no_html(html: str) -> str:
    """Conteúdo da célula do saldo para o líder (uma única, sempre renderizada)."""
    achado = re.search(r'<dd class="gap-lider">([^<]*)</dd>', html)
    assert achado is not None, "saldo para o líder ausente na comparação municipal"
    return achado.group(1).strip()


# -- 2 consultas, sem `history` e sem leitura duplicada da mart ---------------


def test_concorrencia_faz_duas_consultas_e_nao_consulta_a_serie(client, repository):
    repository.schools = [school_row()]
    repository.indicators = [indicator_row()]
    repository.competidores = [competidor_row()]

    _html(client.get(CONCORRENCIA))

    chamadas = _leituras(repository)
    assert chamadas == CHAMADAS_ESPERADAS, chamadas
    assert "get_school_history" not in chamadas
    # `concorrentes_escola` (o antigo `/competitors`) também não é chamado: a
    # comparação vem dentro da resposta de indicadores.
    assert "get_school" not in chamadas


def test_html_da_concorrencia_cabe_no_orcamento(client, repository):
    repository.schools = [
        school_row(co_entidade=COTEMIG, no_entidade="COL COTEMIG BARROCA")
    ]
    repository.indicators = [_indicador_cotemig()]
    repository.competidores = [competidor_row(co_entidade=COTEMIG)]

    resposta = client.get(COTEMIG_CONCORRENCIA, headers={"Accept-Encoding": "identity"})
    tamanho = len(resposta.content)
    print(f"Indicadores e concorrência da {COTEMIG}: {tamanho} B")

    assert resposta.status_code == 200
    assert tamanho <= TETO_HTML_BYTES, f"{tamanho} B > {TETO_HTML_BYTES} B"


# -- o que a página mostra: rótulos do F11 preservados ------------------------

def test_concorrencia_mostra_crescimento_definicao_e_rank(client, repository):
    html = _cotemig(client, repository)

    # Crescimento anual explícito, com a direção da posição.
    assert POSICAO_MUNICIPIO in html
    assert POSICAO_MG in html
    assert _valor_da_definicao(html, POSICAO_MUNICIPIO) == "487.º"
    assert _valor_da_definicao(html, POSICAO_MG) == "2.134.º"
    # Definição da comparação (mesma copy do F11) e posição municipal.
    assert "Escolas privadas ativas no mesmo município e ano censitário (MG)" in html
    assert "ESCOLA LIDER" in html


def test_posicao_por_crescimento_nao_e_rotulada_de_creche(client, repository):
    """`rank_crec_*` é posição por crescimento: a 31005371 nem tem creche.

    O bug exibia "Posição por matrícula de creche" (487/2.134) para uma escola
    com `qt_mat_creche = 0`, porque `crec` foi lido como "creche". O teste falha
    se o rótulo voltar (ou se qualquer "posição" voltar a mencionar creche).
    """
    html = _cotemig(client, repository)

    rotulos = re.findall(r"<dt>(.*?)</dt>", html, flags=re.S)
    posicoes = [rotulo for rotulo in rotulos if rotulo.startswith("Posição por")]
    assert posicoes, "nenhuma posição exibida na página"
    assert all("creche" not in rotulo.lower() for rotulo in posicoes), posicoes


def test_posicao_por_crescimento_sem_dado_nao_vira_zero(client, repository):
    """`null` na posição é "sem dado" (AGENTS.md §6) — nunca `0.º`."""
    repository.schools = [school_row(co_entidade=COTEMIG)]
    repository.indicators = [
        _indicador_cotemig(rank_crec_municipio=None, rank_crec_mg=None)
    ]
    repository.competidores = [competidor_row(co_entidade=COTEMIG)]

    html = _html(client.get(COTEMIG_CONCORRENCIA))

    assert _valor_da_definicao(html, POSICAO_MUNICIPIO) == "sem dado"
    assert _valor_da_definicao(html, POSICAO_MG) == "sem dado"
    assert "0.º" not in html


def test_aviso_de_porte_minimo_aparece_na_rota(client, repository):
    repository.schools = [school_row()]
    repository.indicators = [indicator_row(is_abaixo_porte=True)]
    repository.competidores = [competidor_row()]

    html = _html(client.get(CONCORRENCIA))

    assert "abaixo do porte mínimo de comparabilidade" in html
    # O código interno do aviso não vira texto para o leitor (E6).
    assert "IS_ABAIXO_PORTE" not in html


def test_comparacao_municipal_mostra_a_definicao(client, repository):
    repository.indicators = [indicator_row()]
    repository.competidores = [competidor_row()]

    html = _html(client.get(CONCORRENCIA))

    assert "Escolas privadas ativas no mesmo município e ano censitário (MG)" in html
    # A posição no município é exibida junto do líder.
    assert "ESCOLA LIDER" in html
    assert _valor_da_definicao(
        html, "Posição por matrícula da educação básica no município"
    ) == "3.º"


def test_lider_da_comparacao_municipal_continua_texto(client, repository):
    """Sem `co_entidade` do líder no payload, linkar seria adivinhar por nome."""
    repository.indicators = [indicator_row()]
    repository.competidores = [competidor_row()]

    html = _html(client.get(CONCORRENCIA))

    achado = re.search(
        r"<dt>Líder do município[^<]*</dt>\s*<dd>(.*?)</dd>", html, flags=re.S
    )
    assert achado is not None
    assert "ESCOLA LIDER" in achado.group(1)
    assert "href=" not in achado.group(1)


def test_gap_zero_mostra_que_a_escola_lidera(client, repository):
    repository.indicators = [indicator_row()]
    repository.competidores = [
        competidor_row(
            lider_no_entidade="ESCOLA MODELO",
            lider_qt_mat_bas=120,
            gap_mat_bas_para_lider=0,
        )
    ]

    html = _html(client.get(CONCORRENCIA))

    # Gap zero é medição válida: a própria escola é a líder, não ausência.
    assert _gap_no_html(html) == "a escola lidera"


def test_gap_positivo_e_exibido_como_numero(client, repository):
    repository.indicators = [indicator_row()]
    repository.competidores = [
        competidor_row(lider_qt_mat_bas=300, gap_mat_bas_para_lider=180)
    ]

    html = _html(client.get(CONCORRENCIA))

    assert _gap_no_html(html) == "180"


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [(0, "a escola lidera"), (180, "180"), (None, "sem dado")],
)
def test_filtro_de_gap_para_lider(valor, esperado):
    assert fmt_gap_lider(valor) == esperado


def test_pagina_nao_chama_taxa_de_evasao(client, repository):
    """O proxy de retenção só pode aparecer na negação exigida pelo rótulo."""
    html = _cotemig(client, repository)

    assert html.count("evasão") == html.count("não é taxa de evasão") > 0


# -- ausência de comparação no ano: "sem dado" + motivo, nunca 0 -------------


def test_sem_competicao_no_ano_mostra_sem_dado_com_motivo(client, repository):
    """Escola privada ativa sem linha em `mart_competidores` no ano."""
    repository.schools = [school_row(co_entidade=COTEMIG)]
    repository.indicators = [_indicador_cotemig()]
    repository.competidores = []

    html = _html(client.get(COTEMIG_CONCORRENCIA))

    assert "sem dado" in html
    assert MOTIVO_SEM_COMPARACAO in html
    # A comparação mudou de ano de propósito: nenhum número é fabricado no lugar.
    assert 'class="gap-lider"' not in html
    assert "<dd>0</dd>" not in html
    assert "0.º" not in html
    # Os indicadores do ano continuam visíveis: só a comparação está ausente.
    assert "Crescimento ano a ano" in html


# -- fora do universo: 200 "não se aplica" com volta --------------------------


def test_escola_publica_vira_nao_se_aplica_com_pagina_200(client, repository):
    """Indicadores vazio + `get_school` com dependência não privada."""
    repository.schools = [
        school_row(co_entidade=ESCOLA, tp_dependencia="3", tp_situacao_funcionamento="1")
    ]
    repository.indicators = []

    html = _html(client.get(CONCORRENCIA), status=200)

    assert "Não se aplica" in html
    assert "Indicadores e concorrência: não se aplica a escola pública." in html
    # A página oferece o caminho de volta em vez de beco sem saída.
    assert f'<a href="{VISAO_GERAL_URL}">Voltar para a Visão geral</a>' in html
    # E não inventa seção de dados.
    assert "Crescimento ano a ano" not in html
    assert "Comparação municipal" not in html


def test_escola_inativa_vira_nao_se_aplica(client, repository):
    repository.schools = [
        school_row(co_entidade=ESCOLA, tp_dependencia="4", tp_situacao_funcionamento="3")
    ]
    repository.indicators = []

    html = _html(client.get(CONCORRENCIA), status=200)

    assert "Indicadores e concorrência: não se aplica a escola inativa." in html
    assert f'<a href="{VISAO_GERAL_URL}">Voltar para a Visão geral</a>' in html


def test_privada_ativa_sem_linha_na_mart_explica_a_ausencia_da_secao(
    client, repository
):
    """Privada ativa sem linha em `mart_escola_indicadores`: 404 do `/v1` é estado da seção.

    O universo está certo — `get_school` respondeu `tp_dependencia=4` e
    `tp_situacao_funcionamento=1` — e o que falta é a linha da mart. Dizer
    "fora do universo de privadas ativas" contradiria a própria consulta de
    identidade, então o motivo é o da seção (teste herdado do F11, que travava
    exatamente essa frase).
    """
    repository.schools = [
        school_row(
            co_entidade=ESCOLA, tp_dependencia="4", tp_situacao_funcionamento="1"
        )
    ]
    repository.indicators = []

    html = _html(client.get(CONCORRENCIA), status=200)

    assert "Não se aplica" in html
    # O motivo é a copy da tela, nunca o detail de diagnóstico da API.
    assert MOTIVO_SECAO_INDICADORES in html
    assert "não pertence ao universo de indicadores" not in html
    # A escola É privada ativa: o texto não pode afirmar o contrário.
    assert MOTIVO_FORA_UNIVERSO not in html
    # A página oferece o caminho de volta e não inventa seção de dados.
    assert f'<a href="{VISAO_GERAL_URL}">Voltar para a Visão geral</a>' in html
    assert "Crescimento ano a ano" not in html
    assert "Comparação municipal" not in html


# -- erros: 404, 422 e 503 ----------------------------------------------------


def test_escola_inexistente_vira_404_html(client, repository):
    repository.schools = []
    repository.indicators = []

    resposta = client.get(CONCORRENCIA)

    assert resposta.status_code == 404
    assert resposta.headers["cache-control"] == "no-store"
    assert "não encontrado" in _html(resposta, status=404).lower()


@pytest.mark.parametrize("ano", ["2023", "2025"])
def test_ano_na_rota_responde_422_sem_consultar_repositorio(ano, client, repository):
    repository.errors["get_school_indicators"] = AssertionError("não deveria consultar")

    resposta = client.get(CONCORRENCIA, params={"ano": ano})

    assert resposta.status_code == 422
    html = _html(resposta, status=422)
    assert "Parâmetro inválido" in html
    assert "ano" in html
    assert _leituras(repository) == []


def test_503_nos_indicadores_derruba_a_pagina_inteira(client, repository):
    repository.indicators = [indicator_row()]
    repository.competidores = [competidor_row()]
    repository.errors["get_school_indicators"] = UpstreamUnavailable()

    resposta = client.get(CONCORRENCIA)

    assert resposta.status_code == 503
    assert resposta.headers["cache-control"] == "no-store"
    assert resposta.headers["retry-after"] == "300"
    html = _html(resposta, status=503)
    assert "não se aplica" not in html.lower()
    assert "Crescimento ano a ano" not in html


def test_503_nos_competidores_derruba_a_pagina_inteira(client, repository):
    repository.indicators = [indicator_row()]
    repository.competidores = [competidor_row()]
    repository.errors["get_school_competidores"] = UpstreamUnavailable()

    resposta = client.get(CONCORRENCIA)

    assert resposta.status_code == 503
    assert resposta.headers["retry-after"] == "300"
    assert "Crescimento ano a ano" not in _html(resposta, status=503)


# -- subnav, breadcrumb e revalidação ----------------------------------------


def test_subnav_marca_a_concorrencia_como_pagina_atual(client, repository):
    repository.indicators = [indicator_row()]
    repository.competidores = [competidor_row()]

    html = _html(client.get(CONCORRENCIA))

    assert (
        f'<a href="{CONCORRENCIA}" aria-current="page">Indicadores e concorrência</a>'
        in html
    )
    # O item da Visão geral continua navegável (é a seção anterior).
    assert f'<a href="{VISAO_GERAL_URL}">Visão geral</a>' in html
    assert 'role="tablist"' not in html
    # Breadcrumb termina na seção atual, em texto.
    assert (
        '<li><span aria-current="page">Indicadores e concorrência</span></li>' in html
    )


def test_revalidacao_com_if_none_match_nao_consulta(client, repository):
    repository.indicators = [indicator_row()]
    repository.competidores = [competidor_row()]
    primeira = client.get(CONCORRENCIA)
    assert primeira.status_code == 200
    etag = primeira.headers["etag"]

    repository.calls.clear()
    segunda = client.get(CONCORRENCIA, headers={"If-None-Match": etag})

    assert segunda.status_code == 304
    assert repository.calls == []
