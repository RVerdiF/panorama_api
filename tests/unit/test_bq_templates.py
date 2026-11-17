"""Invariantes dos templates: allowlist, colunas explícitas, parâmetros."""

from __future__ import annotations

import re

import pytest

from panorama_api.repositories.bigquery import (
    BigQuerySettings,
    PageRequest,
    QueryTemplate,
    TEMPLATES,
    TemplateError,
)
from panorama_api.repositories.bigquery.errors import InvalidQueryRequest
from panorama_api.repositories.bigquery.pagination import PaginationMode, plan_page
from panorama_api.repositories.bigquery.parameters import ParamSpec, ParamType
from panorama_api.repositories.bigquery.templates import (
    FilterClause,
    GEO_ANCHORS,
    get_template,
)

SAMPLE_FILTERS: dict[str, dict[str, object]] = {
    "schools": {"co_municipio": "3106200"},
    "school": {"co_entidade": "31000000"},
    "school_history": {"co_entidade": "31000000"},
    "school_indicators": {"co_entidade": "31000000"},
    "market": {"co_municipio": "3106200", "nu_ano_censo": 2024},
    "market_share": {"co_municipio": "3106200", "nu_ano_censo": 2024, "etapa": "fund_ai"},
    "market_concentration": {
        "co_municipio": "3106200",
        "nu_ano_censo": 2024,
        "etapa": "fund_ai",
    },
}


def _plan(template: QueryTemplate):
    return plan_page(
        mode=template.pagination,
        request=PageRequest(),
        page_size_default=50,
        page_size_max=template.max_page_size or 500,
        offset_max=1000,
        row_cap=template.row_cap or 1000,
        keyset_columns=template.keyset_columns,
    )


def test_todo_template_tem_amostra_de_filtros() -> None:
    assert set(SAMPLE_FILTERS) == set(TEMPLATES)


def test_allowlist_fechada() -> None:
    with pytest.raises(InvalidQueryRequest):
        get_template("dim_escola; DROP TABLE")


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_sem_select_estrela_e_colunas_explicitas(name: str) -> None:
    template = TEMPLATES[name]
    for column in template.columns:
        assert column != "*"
        assert not column.endswith(".*")
        assert re.fullmatch(r"[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?", column)


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_parametros_usados_e_declarados_coincidem(name: str) -> None:
    template = TEMPLATES[name]
    filters = SAMPLE_FILTERS[name]
    present = frozenset(filters)
    plan = _plan(template)
    settings = BigQuerySettings(project="p", dataset="serving")

    referenced = template.referenced_params(settings, plan, present)
    expected = {clause.spec.name for clause in template.clauses if clause.name in present}
    expected |= {param for param, _type, _value in plan.parameters}

    assert referenced == expected
    assert "@" in template.render(settings, plan, present)


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_toda_consulta_tem_ancora_geografica(name: str) -> None:
    required = TEMPLATES[name].required_names()
    assert required & GEO_ANCHORS, f"{name} permitiria scan sem filtro geográfico"


def test_regra_do_card_em_share_e_concentracao() -> None:
    # "ano + etapa + (co_escola ou co_municipio)" — card t_ea2c4d84.
    for name in ("market_share", "market_concentration"):
        required = TEMPLATES[name].required_names()
        assert {"co_municipio", "nu_ano_censo", "etapa"} <= required


def test_market_permite_omitir_etapa_conforme_contrato() -> None:
    # /markets sem etapa devolve as 9 etapas (contrato §5); ano continua obrigatório.
    required = TEMPLATES["market"].required_names()
    assert "nu_ano_censo" in required
    assert "co_municipio" in required
    assert "etapa" not in required


def test_dataset_vem_so_da_config() -> None:
    template = TEMPLATES["school"]
    plan = _plan(template)
    present = frozenset({"co_entidade"})
    sql_a = template.render(BigQuerySettings(project="p", dataset="serving"), plan, present)
    sql_b = template.render(BigQuerySettings(project="p", dataset="outro"), plan, present)
    assert "serving.dim_escola" in sql_a
    assert "outro.dim_escola" in sql_b


def test_template_sem_ancora_geografica_e_rejeitado() -> None:
    broken = QueryTemplate(
        name="scan_livre",
        relation="{dataset}.dim_escola",
        columns=("co_entidade",),
        clauses=(FilterClause("nu_ano_censo", "nu_ano_censo = @nu_ano_censo", ParamSpec("nu_ano_censo", ParamType.INT64), required=True),),
    )
    with pytest.raises(TemplateError):
        broken.validate()


def test_keyset_exige_coluna_no_select_e_nao_nula_no_fim() -> None:
    broken = QueryTemplate(
        name="quebrado",
        relation="{dataset}.dim_escola",
        columns=("co_entidade",),
        clauses=(FilterClause("co_municipio", "co_municipio = @co_municipio", ParamSpec("co_municipio", ParamType.STRING), required=True),),
        pagination=PaginationMode.KEYSET,
        keyset_columns=(),
        max_page_size=10,
    )
    with pytest.raises(TemplateError):
        broken.validate()


def test_keyset_nao_usa_order_by_fixo() -> None:
    from panorama_api.repositories.bigquery import KeysetColumn

    broken = QueryTemplate(
        name="conflito",
        relation="{dataset}.dim_escola",
        columns=("co_entidade",),
        clauses=(FilterClause("co_municipio", "co_municipio = @co_municipio", ParamSpec("co_municipio", ParamType.STRING), required=True),),
        order_by="co_entidade ASC",
        pagination=PaginationMode.KEYSET,
        keyset_columns=(KeysetColumn("co_entidade"),),
        max_page_size=10,
    )
    with pytest.raises(TemplateError):
        broken.validate()
