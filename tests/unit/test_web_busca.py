"""Tela de busca `/app/` (cards `t_f28d76a9` e V6-P4 `t_6a9f6b6f`).

Cobre os critérios de aceite sobre o HTML renderizado de verdade
(``TestClient`` + repositório fake, nenhuma rede):

* copy literal do protótipo (`panorama-escola-busca.html:40-164`): `h1`, sub,
  caption, nota de ordenação, placeholders, estado vazio e os ids do design;
* os 3 selects do protótipo (etapa, ano, situação) com os options literais, e
  `etapa`/`ano`/`situacao`/`ordem`/`direcao` chegando à consulta;
* 7 `th.ordenavel[data-campo] > button` e `aria-sort` na coluna ordenada;
* a abertura lista o recorte com **uma** consulta (`buscar_escolas_recorte`),
  sem o estado pré-busca inventado e sem o `div.aviso` do teto;
* métrica ausente é `sem dado`, nunca `0`; ordenação `NULLS LAST` no SQL;
* "Próxima" só com `page.has_more`; nunca "de N resultados"; no teto o
  `paginacao__estado` traz o texto do protótipo;
* parâmetro inválido → erro **sem** consultar o repositório;
* `GET /v1/schools` sem critério continua ``400`` (decisão c do V6-P4).
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

import pytest

from panorama_api.core.http_cache import HttpCacheMiddleware
from panorama_api.repositories import queries
from panorama_api.web import PREFIXO_WEB, dados
from panorama_api.web import municipios as modulo_municipios
from panorama_api.web.conteudo import OPCOES_ETAPA_BUSCA, OPCOES_SITUACAO_BUSCA
from tests.unit.conftest import recorte_row

BUSCA = "/app/"
REPO_ROOT = Path(__file__).resolve().parents[2]
APP_JS = REPO_ROOT / "src" / "panorama_api" / "web" / "static" / "app.js"
#: Nenhuma forma de total no HTML ("de 1.025 resultados", "de 20 resultados").
TEXTO_DE_TOTAL = re.compile(r"\bde\s+[\d.]+\s+resultados?\b", re.IGNORECASE)
#: Termos geográficos proibidos no vocabulário de comparação.
TERMOS_PROIBIDOS = ("raio", "próximos", "proximos", "na região", "na regiao")
#: Texto do teto no `paginacao__estado` (protótipo `app.js:533-537`).
TEXTO_TETO = "Teto de 1.000 registros alcançado — refine a busca."


def _consultas_de_escola(repository) -> list[tuple[str, dict]]:
    """Chamadas de listagem/busca de escola (o boot registra `get_table_columns`)."""
    return [
        chamada
        for chamada in repository.calls
        if chamada[0] in ("list_escolas_recorte", "search_schools")
    ]


def _escolas(total: int, *, nome: str = "ESCOLA MODELO") -> list[dict]:
    """`total` linhas do recorte distinguíveis, matrícula decrescente."""
    return [
        recorte_row(
            co_entidade=f"31{i:06d}",
            no_entidade=f"{nome} {i:03d}",
            qt_mat_bas=10_000 - i,
        )
        for i in range(1, total + 1)
    ]


def _payload_ibge(total: int) -> list[dict]:
    """Carga sintética no formato da API de localidades do IBGE."""
    return [
        {"id": 3100000 + i, "nome": f"Município Teste {i:03d}"} for i in range(total)
    ]


def _limpar_caches(client) -> None:
    """Esvazia o LRU das páginas `/app` **e** o LRU do recorte da busca.

    A chave dos dois é ``DATA_VERSION`` + recorte — contrato dos cards do cache
    de páginas (`t_68bd7615`) e do V6-P4 —, que **não** inclui a fonte de
    dados. Cada caso aqui troca o repositório fake: sem limpar, a página do
    caso anterior seria servida como *hit* e a asserção falharia por dado
    obsoleto. O `/app` real é cacheado por desenho; o isolamento é do teste.
    """
    recorte = getattr(client.app.state, "cache_recorte", None)
    if recorte is not None:
        recorte.clear()
    pilha = client.app.middleware_stack
    while pilha is not None:
        if (
            isinstance(pilha, HttpCacheMiddleware)
            and pilha.prefix == PREFIXO_WEB
            and pilha.pagina
        ):
            pilha.cache.clear()
            return
        pilha = getattr(pilha, "app", None)
    raise AssertionError("cache de páginas /app não encontrado no stack")


def _get(client, path: str = BUSCA, **kwargs):
    """``GET /app/`` com os caches limpos antes da requisição."""
    _limpar_caches(client)
    return client.request("GET", path, **kwargs)


def _tem_link(html: str, rel: str) -> bool:
    """Link de paginação ativo (`<a rel="…">`); o lado indisponível é `span`
    com `aria-disabled`, sem `href` (D5)."""
    return re.search(rf'<a[^>]*rel="{rel}"', html) is not None


def _bloco(html: str, inicio: str, fim: str) -> str:
    comeco = html.index(inicio)
    return html[comeco : html.index(fim, comeco) + len(fim)]


def _options(html: str, select_id: str) -> list[str]:
    bloco = _bloco(html, f'<select id="{select_id}"', "</select>")
    return [texto.strip() for texto in re.findall(r"<option[^>]*>(.*?)</option>", bloco)]


def _estado_paginacao(html: str) -> str:
    achado = re.search(r'<p class="paginacao__estado">(.*?)</p>', html, re.S)
    assert achado, "paginacao__estado ausente"
    return achado.group(1).strip()


def _carregar_script_gerador() -> ModuleType:
    caminho = REPO_ROOT / "scripts" / "gerar_municipios_mg.py"
    spec = importlib.util.spec_from_file_location("gerar_municipios_mg", caminho)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# -- lista versionada de municípios ------------------------------------------


@pytest.mark.parametrize(("valor", "esperado"), [(2025, "2025"), (None, "sem dado")])
def test_filtro_de_ano_nao_usa_separador_de_milhar(valor, esperado):
    from panorama_api.web.filters import fmt_ano

    assert fmt_ano(valor) == esperado


def test_json_de_municipios_tem_853_entradas_com_codigo_ibge_de_mg():
    bruto = json.loads(
        modulo_municipios.ARQUIVO_MUNICIPIOS.read_text(encoding="utf-8")
    )

    assert len(bruto) == 853
    codigos = [item["co_municipio"] for item in bruto]
    assert len(set(codigos)) == 853
    assert all(re.fullmatch(r"^31\d{5}$", codigo) for codigo in codigos)
    assert all(item["no_municipio"].strip() for item in bruto)
    assert all(set(item) == {"co_municipio", "no_municipio"} for item in bruto)


def test_carregador_do_front_entrega_os_mesmos_853_municipios():
    municipios = modulo_municipios.municipios_mg()

    assert len(municipios) == 853
    chaves = [modulo_municipios.chave_ordenacao(m.no_municipio) for m in municipios]
    assert chaves == sorted(chaves)
    assert municipios[0].co_municipio.startswith("31")


def test_gerador_recusa_carga_fora_de_mg_sem_nome_ou_duplicada():
    script = _carregar_script_gerador()

    with pytest.raises(ValueError):
        script.normalizar([{"id": 3500000, "nome": "Fora de MG"}])
    with pytest.raises(ValueError):
        script.normalizar([{"id": 3100001, "nome": "   "}])
    with pytest.raises(ValueError):
        script.normalizar(
            [{"id": 3100001, "nome": "A"}, {"id": 3100001, "nome": "B"}]
        )


def test_gerador_escreve_853_entradas_e_nao_escreve_com_total_errado(tmp_path):
    script = _carregar_script_gerador()
    destino = tmp_path / "municipios_mg.json"

    with pytest.raises(ValueError):
        script.gerar(_payload_ibge(852), destino)
    assert not destino.exists()

    municipios = script.gerar(_payload_ibge(853), destino)
    assert len(municipios) == 853
    bruto = json.loads(destino.read_text(encoding="utf-8"))
    assert len(bruto) == 853
    assert all(re.fullmatch(r"^31\d{5}$", item["co_municipio"]) for item in bruto)


def test_package_data_inclui_o_json_de_municipios():
    """Sem esta linha o arquivo não entraria na imagem (`pip install .`)."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "web/data/*.json" in pyproject


# -- abertura: o recorte é listado (B16) --------------------------------------


def test_abertura_lista_o_recorte_com_uma_consulta_nos_padroes_do_design(
    client, repository
):
    """Sem critério a tela lista o recorte: 1 consulta, matrícula desc, ano máximo."""
    repository.recorte = _escolas(3)

    resposta = _get(client)

    assert resposta.status_code == 200
    ((nome, kwargs),) = _consultas_de_escola(repository)
    assert nome == "list_escolas_recorte"
    assert kwargs == {
        "ano": 2025,
        "q": None,
        "co_municipio": None,
        "etapa": None,
        "situacao": None,
        "ordem": "matricula",
        "direcao": "desc",
        "limit": 20,
        "offset": 0,
    }
    assert "ESCOLA MODELO 001" in resposta.text


def test_abertura_nao_tem_estado_pre_busca_nem_aviso_de_teto(client, repository):
    repository.recorte = _escolas(1025)

    for params in ({}, {"offset": 1000}):
        html = _get(client, params=params).text
        assert "Nenhuma escola listada ainda" not in html
        assert 'div class="aviso"' not in html
        assert '<div class="aviso">' not in html
        assert "Limite de paginação atingido" not in html


def test_busca_usa_a_funcao_do_recorte_e_nao_o_espelho_do_v1(client, repository):
    """`buscar_escolas` (= `/v1/schools`) não é chamada pela tela."""
    repository.recorte = _escolas(2)

    _get(client, params={"q": "modelo", "co_municipio": "3106200"})

    assert [nome for nome, _ in _consultas_de_escola(repository)] == [
        "list_escolas_recorte"
    ]


def test_v1_schools_sem_criterio_continua_400(client, repository):
    """Decisão c do V6-P4: o contrato público não se abre pela tela."""
    resposta = client.get("/v1/schools")

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "PARAMETRO_INVALIDO"
    assert _consultas_de_escola(repository) == []


# -- copy e ids literais (B1–B5, B7, B13, B15, B20) ---------------------------


def test_copy_literal_do_prototipo(client, repository):
    repository.recorte = _escolas(1)

    html = _get(client).text

    assert "<h1>Busca de escolas na rede privada</h1>" in html
    assert (
        '<p class="tela-sub">Cruze nome, município, etapa e situação de '
        "funcionamento. Matrícula, participação municipal e variação anual "
        "aparecem na mesma linha.</p>"
    ) in html
    assert (
        '<p class="painel__nota">Ordenável por qualquer coluna. Nenhum total é '
        "exibido: a paginação usa apenas “tem mais”.</p>"
    ) in html
    assert 'placeholder="Ex.: Colégio Horizonte"' in _bloco(html, '<input type="search" id="q"', ">")
    assert 'placeholder="Todos os municípios"' in _bloco(html, '<input type="text" id="co_municipio"', ">")
    assert "Todos os municípios de MG" not in html


def test_caption_segue_o_formato_do_prototipo_com_o_ano_real(client, repository):
    """`caption` do design (`app.js:529`): posição + ano. "de demonstração" sai
    porque o dado é real (adaptação registrada no card)."""
    repository.recorte = _escolas(25)

    html = _get(client).text

    assert (
        '<caption id="caption-resultados">Mostrando 1–20 do recorte · '
        "matrícula em 2025</caption>"
    ) in html
    assert "de demonstração" not in html


@pytest.mark.parametrize(
    "elemento",
    [
        '<input type="text" id="co_municipio"',
        '<button type="button" class="combo__seta" id="botao-municipio"',
        '<ul class="combo__lista" id="lista-municipios"',
        '<tbody id="corpo-resultados">',
        '<nav class="paginacao" id="paginacao"',
        '<dl class="rodape-meta" id="meta-busca">',
    ],
)
def test_render_tem_os_6_ids_do_prototipo(client, repository, elemento):
    repository.recorte = _escolas(1)

    assert elemento in _get(client).text


def test_combobox_do_ssr_segue_o_dom_do_prototipo(client, repository):
    html = _get(client).text
    campo = _bloco(html, '<input type="text" id="co_municipio"', ">")

    for atributo in (
        'role="combobox"',
        'aria-expanded="false"',
        'aria-controls="lista-municipios"',
        'aria-autocomplete="list"',
        'autocomplete="off"',
    ):
        assert atributo in campo
    # O texto visível não é enviado: quem leva o código é o `hidden`.
    assert "name=" not in campo
    assert '<label for="co_municipio">Município</label>' in html
    assert 'role="listbox"' in _bloco(html, '<ul class="combo__lista"', ">")
    assert 'data-aberta="false"' in _bloco(html, '<ul class="combo__lista"', ">")


def test_codigo_do_municipio_vai_no_hidden_desabilitado_ate_o_js(client, repository):
    html = _get(client, params={"co_municipio": "3106200"}).text

    assert (
        '<input type="hidden" name="co_municipio" value="3106200" disabled data-combo-codigo>'
    ) in html
    # A combobox reabre com o nome visível do município escolhido.
    assert 'value="Belo Horizonte"' in _bloco(html, '<input type="text" id="co_municipio"', ">")


def test_sem_js_o_select_do_noscript_envia_o_codigo(client, repository):
    html = _get(client, params={"co_municipio": "3106200"}).text
    bloco = _bloco(html, "<noscript>", "</noscript>")

    assert '<select name="co_municipio" aria-label="Município">' in bloco
    assert bloco.count('<option value="31') == 853
    assert bloco.count(" selected>") == 1
    assert '<option value="3106200" selected>Belo Horizonte</option>' in bloco
    assert '<option value="">Todos os municípios</option>' in bloco


def test_ilha_de_municipios_tem_853_pares_nome_codigo(client):
    """A ilha `dados-municipios` alimenta a combobox (D7)."""
    html = _get(client).text

    achado = re.search(
        r'<script type="application/json" id="dados-municipios">(\[.*?\])</script>',
        html,
        re.DOTALL,
    )
    assert achado, "ilha JSON de municípios ausente"
    pares = json.loads(achado.group(1))

    assert len(pares) == 853
    assert all(
        len(par) == 2
        and par[0].strip()
        and re.fullmatch(r"^31\d{5}$", par[1])
        for par in pares
    )


def test_app_js_liga_a_combobox_do_ssr_e_a_ordenacao_por_url():
    """Contrato do markup que o JS consome (comportamento: evidência de navegador)."""
    js = APP_JS.read_text(encoding="utf-8")

    assert 'form.querySelector("input#co_municipio")' in js
    assert 'form.querySelector("ul#lista-municipios")' in js
    assert 'form.querySelector("button#botao-municipio")' in js
    assert 'form.querySelector("input[data-combo-codigo]")' in js
    assert "select#municipio" not in js
    assert 'destino.searchParams.set("ordem", th.dataset.campo)' in js
    assert 'destino.searchParams.set("direcao", direcao)' in js
    assert 'destino.searchParams.delete("offset")' in js


# -- filtros etapa / ano / situação (B10–B12) ---------------------------------


def test_os_3_selects_tem_os_options_literais_do_prototipo(client, repository):
    html = _get(client).text

    assert '<label for="etapa">Etapa ofertada</label>' in html
    assert _options(html, "etapa") == [
        "Todas as etapas",
        "Creche",
        "Pré-escola",
        "Ensino fundamental I",
        "Ensino fundamental II",
        "Ensino médio",
    ]
    assert '<label for="ano">Ano de referência</label>' in html
    assert _options(html, "ano") == ["2025", "2024", "2023", "2022", "2021"]
    assert '<option value="2025" selected>2025</option>' in html
    assert '<label for="situacao">Situação de funcionamento</label>' in html
    assert _options(html, "situacao") == [
        "Qualquer situação",
        "Em atividade",
        "Paralisada",
    ]
    assert "Só escolas que ofertam a etapa." in html
    assert "Ano do Censo exibido na matrícula." in html


def test_checkbox_apenas_ativas_saiu(client, repository):
    html = _get(client).text

    assert 'id="apenas-ativas"' not in html
    assert "apenas_ativas" not in html


def test_codigos_dos_options_sao_a_allowlist_do_sql():
    assert {codigo for codigo, _ in OPCOES_ETAPA_BUSCA} == set(queries.ETAPAS_RECORTE)
    assert {codigo for codigo, _ in OPCOES_SITUACAO_BUSCA} == set(
        queries.SITUACOES_RECORTE
    )


def test_get_com_filtros_e_ordem_altera_a_consulta(client, repository):
    repository.recorte = _escolas(2)

    _get(
        client,
        params={
            "etapa": "fund_ai",
            "ano": "2023",
            "situacao": "2",
            "ordem": "share",
            "direcao": "asc",
        },
    )

    ((_nome, kwargs),) = _consultas_de_escola(repository)
    assert kwargs["etapa"] == "fund_ai"
    assert kwargs["ano"] == 2023
    assert kwargs["situacao"] == "2"
    assert kwargs["ordem"] == "share"
    assert kwargs["direcao"] == "asc"


def test_filtros_combinam_e_mudam_as_linhas(client, repository):
    repository.recorte = [
        recorte_row(co_entidade="31000001", no_entidade="CRECHE ATIVA", of_creche=1),
        recorte_row(co_entidade="31000002", no_entidade="SEM CRECHE", of_creche=0),
        recorte_row(
            co_entidade="31000003",
            no_entidade="CRECHE PARALISADA",
            of_creche=1,
            tp_situacao_funcionamento="2",
            qt_mat_bas=None,
            share_privado_pct=None,
            crescimento_yoy_pct=None,
        ),
    ]

    html = _get(client, params={"etapa": "creche", "situacao": "2"}).text

    assert "CRECHE PARALISADA" in html
    assert "CRECHE ATIVA" not in html
    assert "SEM CRECHE" not in html


def test_filtros_selecionados_voltam_marcados(client, repository):
    html = _get(
        client, params={"etapa": "med", "ano": "2024", "situacao": "1"}
    ).text

    assert '<option value="med" selected>Ensino médio</option>' in html
    assert '<option value="2024" selected>2024</option>' in html
    assert '<option value="1" selected>Em atividade</option>' in html


@pytest.mark.parametrize(
    "params",
    [
        {"q": "ab"},
        {"co_municipio": "0000000"},
        {"co_municipio": "3500000"},
        {"offset": 1001},
        {"offset": 2000},
        {"offset": -1},
        {"offset": "abc"},
        {"etapa": "bas"},
        {"etapa": "Creche"},
        {"situacao": "3"},
        {"ordem": "cnpj"},
        {"direcao": "descending"},
        {"ano": "1999"},
        {"ano": "abc"},
    ],
)
def test_parametro_invalido_responde_422_sem_consultar_repositorio(
    client, repository, params
):
    resposta = _get(client, params=params)

    assert resposta.status_code == 422
    assert resposta.headers["content-type"].startswith("text/html")
    assert _consultas_de_escola(repository) == []


def test_ano_fora_do_contrato_nao_consulta_o_repositorio(client, repository):
    resposta = _get(client, params={"ano": "2019"})

    assert resposta.status_code == 404
    assert resposta.headers["content-type"].startswith("text/html")
    assert _consultas_de_escola(repository) == []


# -- ordenação por coluna no servidor (B14) -----------------------------------


def _cabecalhos(html: str) -> list[str]:
    cabecalho = _bloco(html, "<thead>", "</thead>")
    return re.findall(r"<th\b[^>]*>.*?</th>", cabecalho, re.S)


def _campo(th: str) -> str:
    achado = re.search(r'data-campo="([^"]+)"', th)
    assert achado, th
    return achado.group(1)


def test_cabecalho_tem_os_7_th_ordenaveis_do_prototipo(client, repository):
    repository.recorte = _escolas(1)

    ths = _cabecalhos(_get(client).text)

    assert [_campo(th) for th in ths] == [
        "nome",
        "municipio",
        "dependencia",
        "matricula",
        "share",
        "variacao",
        "situacao",
    ]
    rotulos = [
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", th)).replace("▼", "").strip()
        for th in ths
    ]
    assert rotulos == [
        "Escola",
        "Município",
        "Dependência",
        "Matrícula",
        "Share municipal",
        "Variação anual",
        "Situação",
    ]
    for th in ths:
        assert re.match(r'<th class="ordenavel( num)?" data-campo="[a-z]+" scope="col"', th)
        assert '<button type="button">' in th
    assert ths[3].startswith('<th class="ordenavel num" data-campo="matricula"')


def test_aria_sort_descending_na_matricula_por_padrao(client, repository):
    repository.recorte = _escolas(1)

    ths = _cabecalhos(_get(client).text)

    assert 'aria-sort="descending"' in ths[3]
    assert "<span>▼</span>" in ths[3]
    assert sum("aria-sort" in th for th in ths) == 1
    assert all("<span></span>" in th for i, th in enumerate(ths) if i != 3)


def test_aria_sort_acompanha_a_ordem_pedida(client, repository):
    repository.recorte = _escolas(1)

    ths = _cabecalhos(
        _get(client, params={"ordem": "nome", "direcao": "asc"}).text
    )

    assert 'aria-sort="ascending"' in ths[0]
    assert "<span>▲</span>" in ths[0]
    assert sum("aria-sort" in th for th in ths) == 1


def test_ordenacao_reordena_as_linhas_no_servidor(client, repository):
    repository.recorte = [
        recorte_row(co_entidade="31000001", no_entidade="BETA", qt_mat_bas=10),
        recorte_row(co_entidade="31000002", no_entidade="ALFA", qt_mat_bas=30),
        recorte_row(co_entidade="31000003", no_entidade="GAMA", qt_mat_bas=None),
    ]

    padrao = _get(client).text
    por_nome = _get(client, params={"ordem": "nome", "direcao": "asc"}).text

    assert padrao.index("ALFA") < padrao.index("BETA") < padrao.index("GAMA")
    assert por_nome.index("ALFA") < por_nome.index("BETA") < por_nome.index("GAMA")


@pytest.mark.parametrize("campo", sorted(queries.ORDENACAO_RECORTE))
@pytest.mark.parametrize("direcao", ["asc", "desc"])
def test_sql_ordena_com_nulls_last_em_toda_coluna(campo, direcao):
    sql, _ = queries.escolas_recorte(
        lambda tabela: f"`p.d.{tabela}`",
        ano=2025,
        q=None,
        co_municipio=None,
        etapa=None,
        situacao=None,
        ordem=campo,
        direcao=direcao,
        limit=20,
        offset=0,
    )

    coluna = queries.ORDENACAO_RECORTE[campo]
    assert (
        f"ORDER BY {coluna} {direcao.upper()} NULLS LAST, e.co_entidade ASC" in sql
    )


def test_sql_do_recorte_e_left_join_do_ano_com_filtros_parametrizados():
    sql, params = queries.escolas_recorte(
        lambda tabela: f"`p.d.{tabela}`",
        ano=2024,
        q="Modelo",
        co_municipio="3106200",
        etapa="creche",
        situacao="2",
        ordem="matricula",
        direcao="desc",
        limit=20,
        offset=40,
    )

    assert "FROM `p.d.dim_escola` AS e\nLEFT JOIN `p.d.mart_escola_indicadores` AS i" in sql
    assert "INNER JOIN" not in sql
    assert "ON i.co_entidade = e.co_entidade AND i.nu_ano_censo = @ano" in sql
    assert "e.sg_uf = 'MG'" in sql
    assert "STRPOS(LOWER(e.no_entidade), @q) > 0" in sql
    assert "e.co_municipio = @co_municipio" in sql
    assert "e.of_creche = 1" in sql
    assert "e.tp_situacao_funcionamento = @situacao" in sql
    assert sql.endswith("LIMIT 21 OFFSET 40")
    assert params == [
        ("ano", "INT64", 2024),
        ("q", "STRING", "modelo"),
        ("co_municipio", "STRING", "3106200"),
        ("situacao", "STRING", "2"),
    ]
    # Nada vindo do cliente entra no texto do SQL fora da allowlist.
    assert "Modelo" not in sql and "3106200" not in sql


def test_sql_recusa_ordem_fora_da_allowlist():
    with pytest.raises(KeyError):
        queries.escolas_recorte(
            lambda tabela: tabela,
            ano=2025,
            q=None,
            co_municipio=None,
            etapa=None,
            situacao=None,
            ordem="no_entidade; DROP",
            direcao="desc",
            limit=20,
            offset=0,
        )


# -- métricas: valor real ou `sem dado`, nunca 0 (decisão d) ------------------


def test_metricas_reais_aparecem_formatadas(client, repository):
    repository.recorte = [
        recorte_row(qt_mat_bas=1680, share_privado_pct=12.5, crescimento_yoy_pct=-3.2)
    ]

    html = _get(client).text
    corpo = _bloco(html, '<tbody id="corpo-resultados">', "</tbody>")

    assert '<td class="num metrica">1.680</td>' in corpo
    assert '<td class="num metrica">12,5%</td>' in corpo
    assert '<td class="num"><span class="var-neg">−3,2%</span></td>' in corpo


def test_metrica_ausente_sai_sem_dado_nunca_zero(client, repository):
    repository.recorte = [
        recorte_row(
            tp_dependencia="2",
            qt_mat_bas=0,
            is_qt_mat_bas_missing=True,
            share_privado_pct=None,
            crescimento_yoy_pct=None,
        )
    ]

    html = _get(client).text
    corpo = _bloco(html, '<tbody id="corpo-resultados">', "</tbody>")

    assert corpo.count('<span class="sem-dado">sem dado</span>') == 3
    assert ">0<" not in corpo
    assert "0%" not in corpo


def test_linha_usa_classes_e_rotulos_do_prototipo(client, repository):
    """`td.sec` + `td.num.metrica` + link `nome-escola`; rótulo sem código (D5)."""
    repository.recorte = [recorte_row()]

    html = _get(client).text
    corpo = _bloco(html, '<tbody id="corpo-resultados">', "</tbody>")

    assert '<td><a class="nome-escola" href="/app/escolas/31000001">ESCOLA MODELO</a></td>' in corpo
    assert '<td class="sec">BELO HORIZONTE</td>' in corpo
    assert '<td class="sec">Privada</td>' in corpo
    assert '<td class="sec">Em atividade</td>' in corpo
    assert "4 — Privada" not in corpo
    assert "1 — Em atividade" not in corpo


# -- estado vazio único (B16/B17) ---------------------------------------------


def test_estado_vazio_unico_do_prototipo(client, repository):
    repository.recorte = []

    html = _get(client, params={"q": "zzzxxyy"}).text

    assert html.count('class="estado-vazio"') == 1
    vazio = _bloco(html, '<div id="estado-vazio" class="estado-vazio"', "</div>")
    assert "hidden" not in vazio.split(">", 1)[0]
    assert "<h3>Nenhuma escola para este recorte</h3>" in vazio
    assert "<p>Ajuste o nome, o município ou a etapa.</p>" in vazio
    assert (
        '<caption id="caption-resultados">Nenhuma escola para o recorte '
        "selecionado.</caption>"
    ) in html
    assert '<nav class="paginacao" id="paginacao" aria-label="Paginação dos resultados" hidden>' in html


def test_com_linhas_o_estado_vazio_fica_oculto(client, repository):
    repository.recorte = _escolas(2)

    html = _get(client).text

    assert '<div id="estado-vazio" class="estado-vazio" hidden>' in html
    assert '<nav class="paginacao" id="paginacao" aria-label="Paginação dos resultados">' in html


# -- chips e "Limpar" ---------------------------------------------------------

LINK_LIMPAR = re.compile(
    r'<a class="botao botao--secundario botao--mini" href="/app/">Limpar</a>'
)


def test_chips_mostram_os_filtros_aplicados(client, repository):
    html = _get(
        client,
        params={
            "q": "zzzxxyy",
            "co_municipio": "3106200",
            "etapa": "creche",
            "situacao": "1",
        },
    ).text

    assert '<span class="chip">nome: <strong>zzzxxyy</strong></span>' in html
    assert (
        '<span class="chip">município: <strong>Belo Horizonte</strong></span>'
    ) in html
    assert '<span class="chip">etapa: <strong>Creche</strong></span>' in html
    assert '<span class="chip">situação: <strong>Em atividade</strong></span>' in html
    assert LINK_LIMPAR.search(html)


def test_sem_filtro_nao_ha_chip_nem_limpar(client):
    html = _get(client).text

    assert 'class="chip"' not in html
    assert ">Limpar</a>" not in html


# -- paginação (B9) -----------------------------------------------------------


def test_proxima_so_aparece_quando_ha_mais_resultados(client, repository):
    repository.recorte = _escolas(20)
    html = _get(client).text
    assert not _tem_link(html, "next")
    assert (
        '<span class="botao botao--secundario" aria-disabled="true">Próxima</span>'
        in html
    )
    assert _estado_paginacao(html) == "Mostrando 1–20"

    repository.recorte = _escolas(21)
    html = _get(client).text
    assert _tem_link(html, "next")
    assert "offset=20" in html


def test_anterior_so_aparece_com_offset_positivo(client, repository):
    repository.recorte = _escolas(45)

    primeira = _get(client).text
    assert not _tem_link(primeira, "prev")

    terceira = _get(client, params={"offset": 40}).text
    assert _tem_link(terceira, "prev")
    assert "offset=20" in terceira
    assert not _tem_link(terceira, "next")
    assert _estado_paginacao(terceira) == "Mostrando 41–45"


def test_links_de_paginacao_preservam_os_filtros(client, repository):
    repository.recorte = _escolas(45)

    html = _get(
        client,
        params={
            "co_municipio": "3106200",
            "etapa": "pre",
            "ano": "2024",
            "situacao": "1",
            "ordem": "nome",
            "direcao": "asc",
        },
    ).text
    achado = re.search(r'<a[^>]*href="([^"]+)" rel="next"', html)
    assert achado, "link Próxima ausente"
    proxima = achado.group(1)

    for par in (
        "co_municipio=3106200",
        "etapa=pre",
        "ano=2024",
        "situacao=1",
        "ordem=nome",
        "direcao=asc",
        "offset=20",
    ):
        assert par in proxima


def test_padrao_de_ano_e_ordem_nao_entra_na_url(client, repository):
    repository.recorte = _escolas(45)

    html = _get(client).text

    assert 'href="/app/?offset=20" rel="next"' in html


def test_offset_no_teto_esconde_proxima_e_mostra_o_texto_do_prototipo(
    client, repository
):
    repository.recorte = _escolas(1025)

    html = _get(client, params={"offset": 1000}).text

    assert not _tem_link(html, "next")
    assert _estado_paginacao(html) == TEXTO_TETO


def test_ultimo_offset_permitido_ainda_tem_proxima(client, repository):
    repository.recorte = _escolas(1025)

    html = _get(client, params={"offset": 980}).text

    assert _tem_link(html, "next")
    assert "offset=1000" in html
    assert TEXTO_TETO not in html


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": "modelo"},
        {"q": "modelo", "offset": 20},
        {"q": "modelo", "offset": 1000},
    ],
)
def test_html_nunca_mostra_o_total_de_resultados(client, repository, params):
    repository.recorte = _escolas(1025)

    html = _get(client, params=params).text

    assert not TEXTO_DE_TOTAL.search(html)
    assert "total de resultados" not in html.lower()


# -- meta e cache -------------------------------------------------------------


def test_meta_busca_declara_ano_etapa_universo_e_fonte(client, repository):
    repository.recorte = _escolas(1)

    html = _get(client, params={"etapa": "creche", "ano": "2024"}).text
    meta = _bloco(html, '<dl class="rodape-meta" id="meta-busca">', "</dl>")

    assert "<dt>Ano de referência</dt><dd>2024</dd>" in meta
    assert "<dt>Etapa</dt><dd>Creche</dd>" in meta
    assert "<code>escolas_mg</code>" in meta
    assert "INEP · Censo Escolar · <code>dim_escola + mart_escola_indicadores</code>" in meta
    assert "<dt>Etapa</dt><dd>todas as etapas</dd>" in _get(client).text


def test_lru_do_recorte_tem_ao_menos_64_entradas_e_evita_refazer_a_consulta(
    client, repository
):
    """Decisão a do V6-P4: o vaivém de paginação/ordem não refaz a consulta."""
    repository.recorte = _escolas(45)
    _get(client)  # limpa os dois caches e popula o do recorte

    # Cache de páginas frio, LRU do recorte quente: a mesma URL não consulta.
    pilha = client.app.middleware_stack
    while not (isinstance(pilha, HttpCacheMiddleware) and pilha.pagina):
        pilha = getattr(pilha, "app")
    pilha.cache.clear()
    client.get(BUSCA)

    assert len(_consultas_de_escola(repository)) == 1
    assert dados.CAPACIDADE_CACHE_RECORTE >= 64
    assert client.app.state.cache_recorte.max_entries >= 64


# -- vocabulário e URL do hero -------------------------------------------------


def test_busca_nao_usa_termos_geograficos_proibidos(client, repository):
    repository.recorte = _escolas(3)

    html = _get(client, params={"q": "modelo"}).text.lower()

    for termo in TERMOS_PROIBIDOS:
        assert termo not in html, f"termo proibido na tela de busca: {termo!r}"


@pytest.mark.parametrize(
    ("termo", "esperado"),
    [
        ("modelo", "ESCOLA MODELO"),
        # Termo sem resultado: a URL do hero responde 200 com o estado vazio.
        ("magnum", "Nenhuma escola para este recorte"),
    ],
)
def test_url_do_hero_responde_como_a_busca(client, repository, termo, esperado):
    """A URL que a barra do hero gera (`q` + `co_municipio`) é a busca normal."""
    repository.recorte = _escolas(1)

    resposta = _get(client, params={"q": termo, "co_municipio": "3106200"})

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/html")
    ((nome, kwargs),) = _consultas_de_escola(repository)
    assert nome == "list_escolas_recorte"
    assert kwargs["q"] == termo
    assert kwargs["co_municipio"] == "3106200"
    assert esperado in resposta.text
