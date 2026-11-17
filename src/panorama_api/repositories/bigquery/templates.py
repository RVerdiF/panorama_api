"""Templates fixos de consulta ao serving (allowlist).

Invariantes verificados no import (``TEMPLATES``):

* nenhum ``SELECT *`` — cada coluna é nomeada e validada por regex;
* toda consulta é ancorada em chave geográfica (``co_entidade`` ou
  ``co_municipio``), então não existe scan sem filtro;
* todo ``@param`` usado no SQL existe no template e todo parâmetro declarado é
  usado; valores nunca aparecem no texto do SQL;
* keyset só é declarado com chave monotônica não nula na última coluna.

Matriz de filtros obrigatórios (explícita e testada):

=====================  ==========================================
template               obrigatórios
=====================  ==========================================
``schools``            ``co_municipio`` (+ ``q`` opcional)
``school``             ``co_entidade``
``school_history``     ``co_entidade`` (+ faixa de ano opcional)
``school_indicators``  ``co_entidade`` (+ ``nu_ano_censo`` opcional)
``market``             ``co_municipio``, ``nu_ano_censo``
``market_share``       ``co_municipio``, ``nu_ano_censo``, ``etapa``
``market_concentration`` ``co_municipio``, ``nu_ano_censo``, ``etapa``
=====================  ==========================================

Onde o contrato da API permite omitir ``etapa`` (``/markets`` devolve as 9
etapas) o template não a exige; ``/share`` e concentração seguem a regra
``ano + etapa + geografia`` do card.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .config import BigQuerySettings
from .errors import InvalidQueryRequest, TemplateError
from .pagination import KeysetColumn, PaginationMode, PagePlan
from .parameters import (
    ANO_CENSO,
    ANO_FIM,
    ANO_INICIO,
    CO_ENTIDADE,
    CO_MUNICIPIO,
    ENTIDADE_TIPO,
    ETAPA,
    PREFIXO_BUSCA,
    ParamSpec,
)

_COLUMN_RE = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?$")
_PARAM_REF_RE = re.compile(r"@([a-z][a-z0-9_]*)")

#: Âncoras geográficas aceitas: nenhuma consulta pode varrer o serving inteiro.
GEO_ANCHORS: frozenset[str] = frozenset({"co_entidade", "co_municipio"})


@dataclass(frozen=True, slots=True)
class FilterClause:
    """Predicado constante + parâmetro tipado correspondente."""

    name: str
    sql: str
    spec: ParamSpec
    required: bool = False


@dataclass(frozen=True, slots=True)
class QueryTemplate:
    """Consulta fixa, identificada por nome; nada vem do cliente."""

    name: str
    relation: str
    columns: tuple[str, ...]
    clauses: tuple[FilterClause, ...] = ()
    fixed_where: tuple[str, ...] = ()
    order_by: str | None = None
    pagination: PaginationMode = PaginationMode.NONE
    keyset_columns: tuple[KeysetColumn, ...] = ()
    max_page_size: int | None = None
    row_cap: int | None = None
    cross_checks: tuple[Callable[[Mapping[str, Any]], None], ...] = ()

    # -- validação estrutural (import) ------------------------------------

    def validate(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.name):
            raise TemplateError(f"nome de template inválido: {self.name!r}")
        if not self.columns:
            raise TemplateError(f"{self.name}: nenhuma coluna declarada")
        for column in self.columns:
            if not _COLUMN_RE.match(column):
                raise TemplateError(f"{self.name}: coluna inválida {column!r}")
        names = [clause.name for clause in self.clauses]
        if len(set(names)) != len(names):
            raise TemplateError(f"{self.name}: filtros duplicados")
        params = [clause.spec.name for clause in self.clauses]
        if len(set(params)) != len(params):
            raise TemplateError(f"{self.name}: parâmetros duplicados")
        if not any(clause.required and clause.name in GEO_ANCHORS for clause in self.clauses):
            raise TemplateError(f"{self.name}: sem âncora geográfica obrigatória")
        if self.pagination is PaginationMode.KEYSET:
            if not self.keyset_columns:
                raise TemplateError(f"{self.name}: keyset sem colunas")
            if self.keyset_columns[-1].nullable:
                raise TemplateError(f"{self.name}: última coluna do keyset não pode ser nula")
            if self.order_by:
                raise TemplateError(
                    f"{self.name}: order_by fixo conflita com keyset (use keyset_columns)"
                )
        if self.pagination is not PaginationMode.NONE and not self.max_page_size:
            raise TemplateError(f"{self.name}: paginação sem max_page_size")
        if self.pagination is PaginationMode.KEYSET and self.keyset_columns:
            names_keyset = {column.name for column in self.keyset_columns}
            if not names_keyset.issubset(set(self.columns)):
                raise TemplateError(
                    f"{self.name}: coluna de keyset ausente do SELECT "
                    f"({sorted(names_keyset - set(self.columns))})"
                )

    # -- renderização ------------------------------------------------------

    def render(self, settings: BigQuerySettings, plan: PagePlan, present: frozenset[str]) -> str:
        """Monta o SQL: só constantes de código + ``{dataset}`` validado."""
        predicates = [self._render_fixed(clause) for clause in self.fixed_where]
        predicates.extend(clause.sql for clause in self.clauses if clause.name in present)
        if plan.keyset_predicate:
            predicates.append(plan.keyset_predicate)

        lines = [
            f"SELECT {', '.join(self.columns)}",
            f"FROM {settings.render_relation(self.relation)}",
        ]
        if predicates:
            lines.append("WHERE " + "\n  AND ".join(predicates))
        order_by = plan.order_by or self.order_by
        if order_by:
            lines.append(f"ORDER BY {order_by}")
        if plan.limit_sql:
            lines.append(plan.limit_sql)
        return "\n".join(lines)

    @staticmethod
    def _render_fixed(clause: str) -> str:
        # ``fixed_where`` é constante de código (ex.: sg_uf = 'MG'), mas o
        # dataset nunca aparece aqui.
        if "{" in clause:
            raise TemplateError(f"predicado fixo não pode conter placeholder: {clause!r}")
        return clause

    # -- parâmetros declarados --------------------------------------------

    @property
    def param_names(self) -> tuple[str, ...]:
        return tuple(clause.spec.name for clause in self.clauses)

    def referenced_params(self, settings: BigQuerySettings, plan: PagePlan, present: frozenset[str]) -> set[str]:
        sql = self.render(settings, plan, present)
        return set(_PARAM_REF_RE.findall(sql))

    def required_names(self) -> frozenset[str]:
        return frozenset(clause.name for clause in self.clauses if clause.required)


def check_ano_range(values: Mapping[str, Any]) -> None:
    inicio = values.get("ano_inicio")
    fim = values.get("ano_fim")
    if inicio is not None and fim is not None and inicio > fim:
        raise InvalidQueryRequest(
            "ano_inicio não pode ser maior que ano_fim", field="ano_inicio"
        )


# --- listas de colunas (contrato mvp-1) -------------------------------------

_DIM_ESCOLA_COLUMNS: tuple[str, ...] = (
    "co_entidade",
    "no_entidade",
    "co_municipio",
    "no_municipio",
    "sg_uf",
    "tp_dependencia",
    "tp_categoria_escola_privada",
    "tp_localizacao",
    "tp_situacao_funcionamento",
    "cnpj_raiz_mantenedora",
    "is_cnpj_generic",
    "of_creche",
    "of_pre",
    "of_fund_ai",
    "of_fund_af",
    "of_med",
    "of_prof",
    "of_eja",
    "of_esp",
    "of_bas",
    "is_oferta_desconhecida",
    "nu_ano_ultimo_registro",
    "n_anos_serie",
    "ano_primeiro_registro",
    "ano_ultimo_registro",
)

_MART_ESCOLA_COLUMNS: tuple[str, ...] = (
    "nu_ano_censo",
    "co_entidade",
    "no_entidade",
    "co_municipio",
    "no_municipio",
    "tp_dependencia",
    "tp_categoria_escola_privada",
    "tp_localizacao",
    "tp_situacao_funcionamento",
    "cnpj_raiz_mantenedora",
    "is_cnpj_generic",
    "of_creche",
    "of_pre",
    "of_fund_ai",
    "of_fund_af",
    "of_med",
    "of_prof",
    "of_eja",
    "of_esp",
    "of_bas",
    "is_oferta_desconhecida",
    "qt_mat_bas",
    "is_qt_mat_bas_missing",
    "qt_mat_creche",
    "is_qt_mat_creche_missing",
    "qt_mat_pre",
    "is_qt_mat_pre_missing",
    "qt_mat_fund_ai",
    "is_qt_mat_fund_ai_missing",
    "qt_mat_fund_af",
    "is_qt_mat_fund_af_missing",
    "qt_mat_med",
    "is_qt_mat_med_missing",
    "qt_mat_prof",
    "is_qt_mat_prof_missing",
    "qt_mat_eja",
    "is_qt_mat_eja_missing",
    "qt_mat_esp",
    "is_qt_mat_esp_missing",
    "n_etapas_metodologia_incomparavel",
    "tx_aprov_fund_t",
    "tx_aprov_fund_ai",
    "tx_aprov_fund_af",
    "tx_aprov_med_t",
    "tx_reprov_fund_t",
    "tx_reprov_fund_ai",
    "tx_reprov_fund_af",
    "tx_reprov_med_t",
    "tx_aband_fund_t",
    "tx_aband_fund_ai",
    "tx_aband_fund_af",
    "tx_aband_med_t",
    "is_tx_aprov_fund_t_missing",
    "is_tx_aprov_fund_ai_missing",
    "is_tx_aprov_fund_af_missing",
    "is_tx_aprov_med_t_missing",
    "is_tx_reprov_fund_t_missing",
    "is_tx_aband_fund_t_missing",
    "latitude",
    "longitude",
    "geocode_precision",
    "confidence_score",
    "needs_review",
)

_INDICADORES_COLUMNS: tuple[str, ...] = (
    "i.co_entidade",
    "i.nu_ano_censo",
    "i.no_entidade",
    "i.co_municipio",
    "i.no_municipio",
    "i.cnpj_raiz_mantenedora",
    "i.is_cnpj_generic",
    "i.is_oferta_desconhecida",
    "i.qt_mat_bas",
    "i.is_qt_mat_bas_missing",
    "i.qt_mat_creche",
    "i.qt_mat_pre",
    "i.qt_mat_fund_ai",
    "i.qt_mat_fund_af",
    "i.qt_mat_med",
    "i.qt_mat_prof",
    "i.qt_mat_eja",
    "i.qt_mat_esp",
    "i.prev_qt_mat_bas",
    "i.crescimento_yoy_pct",
    "i.saldo_serie_matriculas",
    "i.retencao_liquida_proxy_pct",
    "i.cagr_pct",
    "i.ano_ini_cagr",
    "i.ano_fim_cagr",
    "i.tx_aprov_fund_t",
    "i.tx_reprov_fund_t",
    "i.tx_aband_fund_t",
    "i.tx_aprov_med_t",
    "i.tx_reprov_med_t",
    "i.tx_aband_med_t",
    "i.is_tx_aprov_fund_t_missing",
    "i.is_tx_aprov_med_t_missing",
    "i.is_tx_reprov_fund_t_missing",
    "i.is_tx_aband_fund_t_missing",
    "i.share_privado_pct",
    "i.share_total_pct",
    "i.is_abaixo_porte",
    "i.hhi_municipio_priv_escola_bas",
    "i.rank_mat_municipio",
    "i.rank_crec_municipio",
    "i.rank_crec_mg",
    "i.flg_entrou_mercado",
    "i.n_etapas_metodologia_incomparavel",
    "c.n_concorrentes_privados_municipio",
    "c.n_concorrentes_com_matricula_bas",
    "c.rank_mat_bas_municipio",
    "c.lider_qt_mat_bas",
    "c.lider_no_entidade",
    "c.gap_mat_bas_para_lider",
)

_MERCADO_COLUMNS: tuple[str, ...] = (
    "m.co_municipio",
    "g.no_municipio",
    "m.nu_ano_censo",
    "m.etapa",
    "m.n_escolas_ativas",
    "m.n_escolas_publicas",
    "m.n_escolas_privadas",
    "m.n_escolas_mat_linha_missing",
    "m.n_escolas_mat_valor_missing",
    "m.n_escolas_mat_missing",
    "m.n_escolas_com_linha_matricula",
    "m.qt_mat_total",
    "m.qt_mat_publica",
    "m.qt_mat_privada",
    "m.pct_privada_no_total_pct",
    "m.n_escolas_entraram",
    "m.n_escolas_ativas_com_baseline",
    "m.n_escolas_sairam",
)

_MARKET_SHARE_COLUMNS: tuple[str, ...] = (
    "co_municipio",
    "nu_ano_censo",
    "etapa",
    "entidade_tipo",
    "id_entidade",
    "no_entidade",
    "n_unidades",
    "mat_entidade",
    "n_escolas_privadas",
    "n_escolas_ativas",
    "qt_mat_privada",
    "qt_mat_total",
    "share_privado_pct",
    "share_total_pct",
    "is_abaixo_porte",
)

_CONCENTRACAO_COLUMNS: tuple[str, ...] = (
    "co_municipio",
    "nu_ano_censo",
    "etapa",
    "recorte",
    "nivel",
    "n_competidores",
    "hhi",
    "share_lider_pct",
    "c4_pct",
    "soma_share_pct",
)


def _build_templates() -> dict[str, QueryTemplate]:
    templates = [
        # Busca de escolas: dimensão corrente, sem ano/etapa. A decisão B6
        # (prefixo em coluna normalizada) ainda não existe no serving; o ponto
        # de troca é esta única cláusula.
        QueryTemplate(
            name="schools",
            relation="{dataset}.dim_escola",
            columns=_DIM_ESCOLA_COLUMNS,
            fixed_where=("sg_uf = 'MG'",),
            clauses=(
                FilterClause(
                    "co_municipio", "co_municipio = @co_municipio", CO_MUNICIPIO, required=True
                ),
                FilterClause(
                    "no_entidade_prefix",
                    "STARTS_WITH(UPPER(no_entidade), @no_entidade_prefix)",
                    PREFIXO_BUSCA,
                ),
            ),
            pagination=PaginationMode.KEYSET,
            keyset_columns=(
                KeysetColumn("no_entidade", nullable=True),
                KeysetColumn("co_entidade"),
            ),
            max_page_size=100,
        ),
        QueryTemplate(
            name="school",
            relation="{dataset}.dim_escola",
            columns=_DIM_ESCOLA_COLUMNS,
            fixed_where=("sg_uf = 'MG'",),
            clauses=(
                FilterClause("co_entidade", "co_entidade = @co_entidade", CO_ENTIDADE, required=True),
            ),
            row_cap=1,
        ),
        QueryTemplate(
            name="school_history",
            relation="{dataset}.mart_escola",
            columns=_MART_ESCOLA_COLUMNS,
            clauses=(
                FilterClause("co_entidade", "co_entidade = @co_entidade", CO_ENTIDADE, required=True),
                FilterClause("ano_inicio", "nu_ano_censo >= @ano_inicio", ANO_INICIO),
                FilterClause("ano_fim", "nu_ano_censo <= @ano_fim", ANO_FIM),
            ),
            order_by="nu_ano_censo ASC",
            cross_checks=(check_ano_range,),
        ),
        QueryTemplate(
            name="school_indicators",
            relation=(
                "{dataset}.mart_escola_indicadores AS i\n"
                "LEFT JOIN {dataset}.mart_competidores AS c\n"
                "  ON i.co_entidade = c.co_entidade AND i.nu_ano_censo = c.nu_ano_censo"
            ),
            columns=_INDICADORES_COLUMNS,
            clauses=(
                FilterClause("co_entidade", "i.co_entidade = @co_entidade", CO_ENTIDADE, required=True),
                FilterClause("nu_ano_censo", "i.nu_ano_censo = @nu_ano_censo", ANO_CENSO),
            ),
            order_by="i.nu_ano_censo ASC",
        ),
        QueryTemplate(
            name="market",
            relation=(
                "{dataset}.mart_mercado AS m\n"
                "LEFT JOIN {dataset}.dim_geografia AS g\n"
                "  ON m.co_municipio = g.co_municipio AND g.is_mg"
            ),
            columns=_MERCADO_COLUMNS,
            clauses=(
                FilterClause("co_municipio", "m.co_municipio = @co_municipio", CO_MUNICIPIO, required=True),
                FilterClause("nu_ano_censo", "m.nu_ano_censo = @nu_ano_censo", ANO_CENSO, required=True),
                FilterClause("etapa", "m.etapa = @etapa", ETAPA),
            ),
            order_by="m.etapa ASC",
        ),
        QueryTemplate(
            name="market_share",
            relation="{dataset}.mart_market_share",
            columns=_MARKET_SHARE_COLUMNS,
            clauses=(
                FilterClause("co_municipio", "co_municipio = @co_municipio", CO_MUNICIPIO, required=True),
                FilterClause("nu_ano_censo", "nu_ano_censo = @nu_ano_censo", ANO_CENSO, required=True),
                FilterClause("etapa", "etapa = @etapa", ETAPA, required=True),
                FilterClause("entidade_tipo", "entidade_tipo = @entidade_tipo", ENTIDADE_TIPO),
            ),
            order_by="mat_entidade DESC NULLS LAST, id_entidade ASC",
            pagination=PaginationMode.OFFSET,
            max_page_size=200,
        ),
        QueryTemplate(
            name="market_concentration",
            relation="{dataset}.mart_concentracao",
            columns=_CONCENTRACAO_COLUMNS,
            clauses=(
                FilterClause("co_municipio", "co_municipio = @co_municipio", CO_MUNICIPIO, required=True),
                FilterClause("nu_ano_censo", "nu_ano_censo = @nu_ano_censo", ANO_CENSO, required=True),
                FilterClause("etapa", "etapa = @etapa", ETAPA, required=True),
            ),
            order_by="recorte ASC, nivel ASC",
        ),
    ]
    registry: dict[str, QueryTemplate] = {}
    for template in templates:
        template.validate()
        if template.name in registry:
            raise TemplateError(f"template duplicado: {template.name}")
        registry[template.name] = template
    return registry


#: Allowlist fechada: o nome do template é o único seletor aceito.
TEMPLATES: Mapping[str, QueryTemplate] = _build_templates()


def get_template(name: str) -> QueryTemplate:
    try:
        return TEMPLATES[name]
    except KeyError as exc:
        raise InvalidQueryRequest(f"template de consulta desconhecido: {name!r}") from exc
