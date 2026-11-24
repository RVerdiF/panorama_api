"""Tela de busca `/app/` (card `t_f28d76a9`).

Cobre os critérios de aceite do card sobre o HTML renderizado de verdade
(``TestClient`` + repositório fake, nenhuma rede):

* "Próxima" só aparece quando `page.has_more` é `true`;
* o HTML nunca diz "de N resultados" (o contrato não tem `total`);
* `offset=1000` esconde "Próxima" e pede refinamento da busca;
* JSON de municípios com 853 entradas e código ``^31\\d{5}$``;
* busca vazia → ``200`` "nenhuma escola" **sem** consultar o repositório;
* parâmetro inválido → ``422`` **sem** consultar o repositório.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

import pytest

from panorama_api.core.http_cache import HttpCacheMiddleware
from panorama_api.web import PREFIXO_WEB
from panorama_api.web import municipios as modulo_municipios
from tests.unit.conftest import school_row

BUSCA = "/app/"
REPO_ROOT = Path(__file__).resolve().parents[2]
#: Nenhuma forma de total no HTML ("de 1.025 resultados", "de 20 resultados").
TEXTO_DE_TOTAL = re.compile(r"\bde\s+[\d.]+\s+resultados?\b", re.IGNORECASE)
#: Termos geográficos proibidos no vocabulário de comparação.
TERMOS_PROIBIDOS = ("raio", "próximos", "proximos", "na região", "na regiao")


def _consultas_de_escola(repository) -> list[tuple[str, dict]]:
    """Chamadas de busca de escola (o boot registra `get_table_columns` antes)."""
    return [chamada for chamada in repository.calls if chamada[0] == "search_schools"]


def _escolas(total: int, *, nome: str = "ESCOLA MODELO") -> list[dict]:
    """`total` escolas distinguíveis, todas com o mesmo município do fixture."""
    return [
        school_row(co_entidade=f"31{i:06d}", no_entidade=f"{nome} {i:03d}")
        for i in range(1, total + 1)
    ]


def _payload_ibge(total: int) -> list[dict]:
    """Carga sintética no formato da API de localidades do IBGE."""
    return [
        {"id": 3100000 + i, "nome": f"Município Teste {i:03d}"} for i in range(total)
    ]


def _limpar_cache_de_paginas(client) -> None:
    """Esvazia o LRU das páginas `/app` do app em teste.

    A chave do LRU é ``DATA_VERSION + APP_BUILD + caminho + query`` — contrato
    do card do cache de páginas (`t_68bd7615`), que **não** inclui a fonte de
    dados. Cada caso aqui troca o repositório fake: sem limpar, a página do
    caso anterior seria servida como *hit* e a asserção falharia por dado
    obsoleto. O `/app` real é cacheado por desenho; o isolamento é do teste.
    """
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
    """``GET /app/`` com o cache de páginas limpo antes da requisição."""
    _limpar_cache_de_paginas(client)
    return client.request("GET", path, **kwargs)


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


# -- busca vazia e validação --------------------------------------------------


@pytest.mark.parametrize("params", [{}, {"q": "   "}, {"co_municipio": ""}])
def test_busca_vazia_responde_200_nenhuma_escola_sem_consultar_repositorio(
    client, repository, params
):
    resposta = _get(client, params=params)

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/html")
    assert "nenhuma escola" in resposta.text.lower()
    assert _consultas_de_escola(repository) == []


@pytest.mark.parametrize(
    "params",
    [
        {"q": "ab"},
        {"co_municipio": "0000000"},
        {"co_municipio": "3500000"},
        {"q": "modelo", "offset": 1001},
        {"q": "modelo", "offset": "abc"},
        {"q": "modelo", "apenas_ativas": "talvez"},
    ],
)
def test_parametro_invalido_responde_422_sem_consultar_repositorio(
    client, repository, params
):
    resposta = _get(client, params=params)

    assert resposta.status_code == 422
    assert resposta.headers["content-type"].startswith("text/html")
    assert "parâmetro inválido" in resposta.text.lower()
    assert _consultas_de_escola(repository) == []


@pytest.mark.parametrize("offsets", [{"offset": 1001}, {"offset": 2000}])
def test_offset_invalido_sem_criterio_tambem_responde_422(
    client, repository, offsets
):
    """Sem critério a busca é 200 — mas o `offset` inválido continua 422 (C7)."""
    resposta = _get(client, params=offsets)

    assert resposta.status_code == 422
    assert resposta.headers["content-type"].startswith("text/html")
    assert "offset" in resposta.text.lower()
    assert _consultas_de_escola(repository) == []


@pytest.mark.parametrize("params", [{"offset": -1}, {"offset": "abc"}])
def test_offset_malformado_sem_criterio_responde_422(client, repository, params):
    resposta = _get(client, params=params)

    assert resposta.status_code == 422
    assert _consultas_de_escola(repository) == []


def test_offset_no_teto_sem_criterio_continua_200(client, repository):
    """O teto é aceito: `?offset=1000` sozinho não é erro de parâmetro."""
    resposta = _get(client, params={"offset": 1000})

    assert resposta.status_code == 200
    assert "nenhuma escola" in resposta.text.lower()


def test_busca_sem_resultado_responde_200_nenhuma_escola(client, repository):
    repository.schools = []

    resposta = _get(client, params={"q": "escola inexistente"})

    assert resposta.status_code == 200
    assert "nenhuma escola" in resposta.text.lower()


# -- estado vazio: sugestões de próximo passo (C4) ---------------------------


def test_estado_vazio_sugere_menos_letras(client, repository):
    repository.schools = []

    html = _get(client, params={"q": "zzzxxyy"}).text

    assert "Nenhuma escola encontrada" in html
    assert "Use menos letras" in html


def test_estado_vazio_sem_termo_sugere_informar_o_nome(client, repository):
    """Sem `q` a dica é informar o nome — não "menos letras" de nada."""
    repository.schools = []

    html = _get(client, params={"co_municipio": "3106200"}).text

    assert "Informe o nome da escola" in html
    assert "Use menos letras" not in html


def test_estado_vazio_oferece_busca_sem_o_filtro_de_municipio(client, repository):
    """Com `q` + município, o link remove só o município."""
    repository.schools = []

    html = _get(
        client, params={"q": "zzzxxyy", "co_municipio": "3106200"}
    ).text

    assert 'href="/app/?q=zzzxxyy"' in html


def test_estado_vazio_nao_oferece_remover_municipio_sem_termo(client, repository):
    """Sem `q`, remover o município cairia na busca sem critério (beco sem saída)."""
    repository.schools = []

    html = _get(client, params={"co_municipio": "3106200"}).text

    assert "sem o filtro de município" not in html
    # A busca vazia continua sendo renderizada (200), não um link morto.
    assert "Nenhuma escola encontrada" in html


def test_estado_vazio_oferece_incluir_escolas_inativas(client, repository):
    repository.schools = []

    html = _get(
        client, params={"q": "zzzxxyy", "co_municipio": "3106200", "apenas_ativas": "true"}
    ).text

    assert 'href="/app/?q=zzzxxyy&amp;co_municipio=3106200"' in html
    assert "Incluir escolas inativas" in html


def test_estado_vazio_sem_filtros_so_sugere_menos_letras(client, repository):
    repository.schools = []

    html = _get(client, params={"q": "zzzxxyy"}).text

    assert "sem o filtro de município" not in html
    assert "Incluir escolas inativas" not in html


def test_sugestoes_do_vazio_apontam_para_paginas_que_respondem_200(client, repository):
    """Todo link sugerido é uma página real da busca (não o `/v1` nem 422)."""
    repository.schools = []

    html = _get(
        client, params={"q": "zzzxxyy", "co_municipio": "3106200", "apenas_ativas": "true"}
    ).text
    hrefs = re.findall(r'href="(/app/\?[^"]+)"', html)
    assert hrefs

    for href in hrefs:
        destino = href.replace("&amp;", "&")
        assert _get(client, path=destino).status_code == 200, destino


# -- resultados, recorte e filtros -------------------------------------------


def test_busca_por_municipio_renderiza_a_escola_e_o_recorte_obrigatorio(
    client, repository
):
    repository.schools = [school_row()]

    resposta = _get(client, params={"co_municipio": "3106200"})
    html = resposta.text

    assert resposta.status_code == 200
    assert "ESCOLA MODELO" in html
    assert "31000001" in html
    # Regras da seção 1 do plano: ano, etapa, universo, fonte e avisos.
    assert "2025" in html
    assert "Educação básica (total)" in html
    assert "escolas_mg" in html
    assert "Todas as escolas do recorte" in html
    assert "INEP" in html and "Censo Escolar" in html and "dim_escola" in html
    assert "nenhum aviso" in html
    # "Mostrando N–M" (posição), nunca "de N resultados".
    assert "Mostrando 1–1" in html
    assert not TEXTO_DE_TOTAL.search(html)


def test_busca_envia_limit_20_e_os_filtros_ao_repositorio(client, repository):
    repository.schools = [school_row()]

    _get(
        client,
        params={"co_municipio": "3106200", "apenas_ativas": "true"},
    )

    ((nome, kwargs),) = _consultas_de_escola(repository)
    assert nome == "search_schools"
    assert kwargs["co_municipio"] == "3106200"
    assert kwargs["q"] is None
    assert kwargs["apenas_ativas"] is True
    assert kwargs["limit"] == 20
    assert kwargs["offset"] == 0


def test_busca_por_nome_chega_ao_repositorio_como_q(client, repository):
    repository.schools = [school_row()]

    _get(client, params={"q": "modelo"})

    ((_nome, kwargs),) = _consultas_de_escola(repository)
    assert kwargs["q"] == "modelo"
    assert kwargs["co_municipio"] is None


def test_select_de_municipio_usa_a_lista_versionada_de_853(client, repository):
    html = _get(client).text

    assert html.count('<option value="31') == 853
    assert '<option value="3106200"' in html
    assert "Belo Horizonte" in html
    assert _consultas_de_escola(repository) == []


def test_valor_ausente_sai_como_sem_dado_e_oferta_desconhecida(
    client, repository
):
    repository.schools = [
        school_row(
            no_entidade=None,
            no_municipio=None,
            of_bas=None,
            is_oferta_desconhecida=True,
        )
    ]

    html = _get(client, params={"co_municipio": "3106200"}).text

    assert "sem dado" in html
    # `oferta.bas = null` é "Desconhecido", nunca "Não" nem 0.
    assert "Desconhecido" in html
    assert "is_oferta_desconhecida" in html


def test_busca_nao_usa_termos_geograficos_proibidos(client, repository):
    repository.schools = _escolas(3)

    html = _get(client, params={"q": "modelo"}).text.lower()

    for termo in TERMOS_PROIBIDOS:
        assert termo not in html, f"termo proibido na tela de busca: {termo!r}"


# -- paginação ----------------------------------------------------------------


def test_proxima_so_aparece_quando_ha_mais_resultados(client, repository):
    repository.schools = _escolas(20)
    html = _get(client, params={"q": "modelo"}).text
    assert "Próxima" not in html
    assert "Mostrando 1–20" in html

    repository.schools = _escolas(21)
    html = _get(client, params={"q": "modelo"}).text
    assert "Próxima" in html
    assert "offset=20" in html


def test_anterior_so_aparece_com_offset_positivo(client, repository):
    repository.schools = _escolas(45)

    primeira = _get(client, params={"q": "modelo"}).text
    assert "Anterior" not in primeira

    terceira = _get(client, params={"q": "modelo", "offset": 40}).text
    assert "Anterior" in terceira
    assert "offset=20" in terceira
    assert "Próxima" not in terceira


def test_links_de_paginacao_preservam_os_filtros(client, repository):
    repository.schools = _escolas(45)

    html = _get(
        client, params={"co_municipio": "3106200", "apenas_ativas": "true"}
    ).text

    assert "co_municipio=3106200" in html
    assert "apenas_ativas=true" in html
    assert "offset=20" in html


def test_offset_no_teto_esconde_proxima_e_pede_para_refinar(client, repository):
    repository.schools = _escolas(1025)

    html = _get(client, params={"q": "modelo", "offset": 1000}).text

    assert "Próxima" not in html
    assert "refine a busca" in html.lower()
    assert "Mostrando 1001–1020" in html


def test_ultimo_offset_permitido_ainda_tem_proxima(client, repository):
    repository.schools = _escolas(1025)

    html = _get(client, params={"q": "modelo", "offset": 980}).text

    assert "Próxima" in html
    assert "offset=1000" in html
    assert "refine a busca" not in html.lower()


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
    repository.schools = _escolas(1025)

    html = _get(client, params=params).text

    assert not TEXTO_DE_TOTAL.search(html)
    assert "total de resultados" not in html.lower()
