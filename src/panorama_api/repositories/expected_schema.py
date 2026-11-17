"""Colunas e tipos esperados nas views do contrato mvp-1 (evidência: BQ `tables.get`).

Validação de startup: nome + tipo das colunas usadas pela API. Falha fechada —
o app não sobe se a view mudar de forma que a consulta deixe de ser correta.
Somente as colunas efetivamente usadas (SELECT ou filtro/ordenação) são exigidas;
colunas novas em `mvp-2` não derrubam o startup.
"""

from __future__ import annotations

from typing import Final

STRING: Final = "STRING"
INTEGER: Final = "INTEGER"
FLOAT: Final = "FLOAT"
BOOLEAN: Final = "BOOLEAN"

_OFERTA: Final[dict[str, str]] = {
    "of_bas": INTEGER,
    "of_creche": INTEGER,
    "of_pre": INTEGER,
    "of_fund_ai": INTEGER,
    "of_fund_af": INTEGER,
    "of_med": INTEGER,
    "of_prof": INTEGER,
    "of_eja": INTEGER,
    "of_esp": INTEGER,
}

_MATRICULA_ETAPAS: Final[dict[str, str]] = {
    name: tipo
    for etapa in ("creche", "pre", "fund_ai", "fund_af", "med", "prof", "eja", "esp")
    for name, tipo in (
        (f"qt_mat_{etapa}", INTEGER),
        (f"is_qt_mat_{etapa}_missing", BOOLEAN),
    )
}

_TX: Final[dict[str, str]] = {
    # Taxas por etapa (4 recortes).
    "tx_aprov_fund_t": FLOAT,
    "tx_aprov_fund_ai": FLOAT,
    "tx_aprov_fund_af": FLOAT,
    "tx_aprov_med_t": FLOAT,
    "tx_reprov_fund_t": FLOAT,
    "tx_reprov_fund_ai": FLOAT,
    "tx_reprov_fund_af": FLOAT,
    "tx_reprov_med_t": FLOAT,
    "tx_aband_fund_t": FLOAT,
    "tx_aband_fund_ai": FLOAT,
    "tx_aband_fund_af": FLOAT,
    "tx_aband_med_t": FLOAT,
    # Flags de missing: o mart só publica estas 6 (não é 1:1 com as taxas).
    "is_tx_aprov_fund_t_missing": BOOLEAN,
    "is_tx_aprov_fund_ai_missing": BOOLEAN,
    "is_tx_aprov_fund_af_missing": BOOLEAN,
    "is_tx_aprov_med_t_missing": BOOLEAN,
    "is_tx_reprov_fund_t_missing": BOOLEAN,
    "is_tx_aband_fund_t_missing": BOOLEAN,
}

_DIM_ESCOLA: Final[dict[str, str]] = {
    "co_entidade": STRING,
    "no_entidade": STRING,
    "sg_uf": STRING,
    "co_municipio": STRING,
    "no_municipio": STRING,
    "tp_dependencia": STRING,
    "tp_categoria_escola_privada": STRING,
    "tp_localizacao": STRING,
    "tp_situacao_funcionamento": STRING,
    "cnpj_raiz_mantenedora": STRING,
    "is_cnpj_generic": BOOLEAN,
    "is_oferta_desconhecida": BOOLEAN,
    "nu_ano_ultimo_registro": INTEGER,
    "n_anos_serie": INTEGER,
    "ano_primeiro_registro": INTEGER,
    "ano_ultimo_registro": INTEGER,
    **_OFERTA,
}

_MART_ESCOLA: Final[dict[str, str]] = {
    "nu_ano_censo": INTEGER,
    "co_entidade": STRING,
    "no_entidade": STRING,
    "co_municipio": STRING,
    "no_municipio": STRING,
    "is_mg": BOOLEAN,
    "tp_dependencia": STRING,
    "tp_categoria_escola_privada": STRING,
    "tp_localizacao": STRING,
    "tp_situacao_funcionamento": STRING,
    "cnpj_raiz_mantenedora": STRING,
    "is_cnpj_generic": BOOLEAN,
    "is_oferta_desconhecida": BOOLEAN,
    "qt_mat_bas": INTEGER,
    "is_qt_mat_bas_missing": BOOLEAN,
    "n_etapas_metodologia_incomparavel": INTEGER,
    "latitude": FLOAT,
    "longitude": FLOAT,
    "geocode_precision": STRING,
    "confidence_score": FLOAT,
    "needs_review": INTEGER,
    **_OFERTA,
    **_MATRICULA_ETAPAS,
    **_TX,
}

_MART_ESCOLA_INDICADORES: Final[dict[str, str]] = {
    "co_entidade": STRING,
    "nu_ano_censo": INTEGER,
    "no_entidade": STRING,
    "co_municipio": STRING,
    "no_municipio": STRING,
    "cnpj_raiz_mantenedora": STRING,
    "is_cnpj_generic": BOOLEAN,
    "is_oferta_desconhecida": BOOLEAN,
    "qt_mat_bas": INTEGER,
    "is_qt_mat_bas_missing": BOOLEAN,
    "qt_mat_creche": INTEGER,
    "qt_mat_pre": INTEGER,
    "qt_mat_fund_ai": INTEGER,
    "qt_mat_fund_af": INTEGER,
    "qt_mat_med": INTEGER,
    "qt_mat_prof": INTEGER,
    "qt_mat_eja": INTEGER,
    "qt_mat_esp": INTEGER,
    "prev_qt_mat_bas": INTEGER,
    "crescimento_yoy_pct": FLOAT,
    "saldo_serie_matriculas": INTEGER,
    "retencao_liquida_proxy_pct": FLOAT,
    "cagr_pct": FLOAT,
    "ano_ini_cagr": INTEGER,
    "ano_fim_cagr": INTEGER,
    "tx_aprov_fund_t": FLOAT,
    "tx_reprov_fund_t": FLOAT,
    "tx_aband_fund_t": FLOAT,
    "tx_aprov_med_t": FLOAT,
    "tx_reprov_med_t": FLOAT,
    "tx_aband_med_t": FLOAT,
    "is_tx_aprov_fund_t_missing": BOOLEAN,
    "is_tx_aprov_med_t_missing": BOOLEAN,
    "is_tx_reprov_fund_t_missing": BOOLEAN,
    "is_tx_aband_fund_t_missing": BOOLEAN,
    "share_privado_pct": FLOAT,
    "share_total_pct": FLOAT,
    "is_abaixo_porte": BOOLEAN,
    "hhi_municipio_priv_escola_bas": FLOAT,
    "rank_mat_municipio": INTEGER,
    "rank_crec_municipio": INTEGER,
    "rank_crec_mg": INTEGER,
    "flg_entrou_mercado": BOOLEAN,
    "n_etapas_metodologia_incomparavel": INTEGER,
}

_MART_COMPETIDORES: Final[dict[str, str]] = {
    "nu_ano_censo": INTEGER,
    "co_entidade": STRING,
    "no_entidade": STRING,
    "co_municipio": STRING,
    "qt_mat_bas": INTEGER,
    "rank_mat_bas_municipio": INTEGER,
    "n_concorrentes_privados_municipio": INTEGER,
    "n_concorrentes_com_matricula_bas": INTEGER,
    "n_concorrentes_creche_xself": INTEGER,
    "n_concorrentes_pre_xself": INTEGER,
    "n_concorrentes_fund_ai_xself": INTEGER,
    "n_concorrentes_fund_af_xself": INTEGER,
    "n_concorrentes_med_xself": INTEGER,
    "lider_no_entidade": STRING,
    "lider_qt_mat_bas": INTEGER,
    "gap_mat_bas_para_lider": INTEGER,
}

_MART_MERCADO: Final[dict[str, str]] = {
    "co_municipio": STRING,
    "nu_ano_censo": INTEGER,
    "etapa": STRING,
    "n_escolas_ativas": INTEGER,
    "n_escolas_publicas": INTEGER,
    "n_escolas_privadas": INTEGER,
    "n_escolas_mat_linha_missing": INTEGER,
    "n_escolas_mat_valor_missing": INTEGER,
    "n_escolas_mat_missing": INTEGER,
    "n_escolas_com_linha_matricula": INTEGER,
    "qt_mat_total": FLOAT,
    "qt_mat_publica": FLOAT,
    "qt_mat_privada": FLOAT,
    "pct_privada_no_total_pct": FLOAT,
    "n_escolas_entraram": FLOAT,
    "n_escolas_ativas_com_baseline": FLOAT,
    "n_escolas_sairam": INTEGER,
}

_MART_CONCENTRACAO: Final[dict[str, str]] = {
    "co_municipio": STRING,
    "nu_ano_censo": INTEGER,
    "etapa": STRING,
    "recorte": STRING,
    "nivel": STRING,
    "n_competidores": INTEGER,
    "hhi": FLOAT,
    "share_lider_pct": FLOAT,
    "c4_pct": FLOAT,
    "soma_share_pct": FLOAT,
}

_MART_MARKET_SHARE: Final[dict[str, str]] = {
    "co_municipio": STRING,
    "nu_ano_censo": INTEGER,
    "etapa": STRING,
    "entidade_tipo": STRING,
    "id_entidade": STRING,
    "no_entidade": STRING,
    "n_unidades": INTEGER,
    "mat_entidade": FLOAT,
    "n_escolas_privadas": INTEGER,
    "n_escolas_ativas": INTEGER,
    "qt_mat_privada": FLOAT,
    "qt_mat_total": FLOAT,
    "share_privado_pct": FLOAT,
    "share_total_pct": FLOAT,
    "is_abaixo_porte": BOOLEAN,
}

_DIM_GEOGRAFIA: Final[dict[str, str]] = {
    "co_municipio": STRING,
    "no_municipio": STRING,
    "co_uf": STRING,
    "sg_uf": STRING,
    "is_mg": BOOLEAN,
}

_DIM_MANTENEDORA: Final[dict[str, str]] = {
    "cnpj_raiz_mantenedora": STRING,
    "cnpj_completo_amostra": STRING,
    "no_municipio_principal": STRING,
    "nu_ano_ultimo_registro": INTEGER,
    "no_grupo": STRING,
}

#: tabela -> {coluna: tipo}. Só tabelas usadas pela v1.
EXPECTED_COLUMNS: Final[dict[str, dict[str, str]]] = {
    "dim_escola": _DIM_ESCOLA,
    "dim_geografia": _DIM_GEOGRAFIA,
    "dim_mantenedora": _DIM_MANTENEDORA,
    "mart_escola": _MART_ESCOLA,
    "mart_escola_indicadores": _MART_ESCOLA_INDICADORES,
    "mart_competidores": _MART_COMPETIDORES,
    "mart_mercado": _MART_MERCADO,
    "mart_concentracao": _MART_CONCENTRACAO,
    "mart_market_share": _MART_MARKET_SHARE,
}
