"""Constantes do contrato de serving (`serving-marts` / `mvp-1`).

Fonte: `panorama_escola/publish/marts_contract.json` (o repositório de dados não é
deployado junto com a API, então o par contrato/versão é fixado aqui — único ponto
do código — e pode ser sobrescrito por `API_CONTRACT_VERSION` quando o contrato virar
`mvp-2`).
"""

from __future__ import annotations

from typing import Final, Literal

CONTRACT: Final = "serving-marts"
CONTRACT_VERSION_DEFAULT: Final = "mvp-1"

#: `fonte` de todo payload de dados (2b R1).
FONTE_ORGAO: Final = "INEP"
FONTE_BASE: Final = "Censo Escolar"

Etapa = Literal[
    "bas",
    "creche",
    "pre",
    "fund_ai",
    "fund_af",
    "med",
    "prof",
    "eja",
    "esp",
]

#: 9 etapas servidas por `mart_mercado` (não somar subetapas para obter `bas`).
ETAPAS: Final[tuple[Etapa, ...]] = (
    "bas",
    "creche",
    "pre",
    "fund_ai",
    "fund_af",
    "med",
    "prof",
    "eja",
    "esp",
)

#: Etapas cujo `of_<etapa>` existe em `dim_escola`/`mart_escola`.
OFERTA_ETAPAS: Final[tuple[Etapa, ...]] = ETAPAS

EntidadeTipo = Literal["escola", "mantenedora"]
ENTIDADES_TIPO: Final[tuple[EntidadeTipo, ...]] = ("escola", "mantenedora")

#: `meta.universo` (2b R1 + extensão para `dim_escola`, que inclui inativas).
UNIVERSO_ESCOLAS_MG: Final = "escolas_mg"
UNIVERSO_PRIVADAS_ATIVAS_MG: Final = "privadas_ativas_mg"
UNIVERSO_ESCOLAS_ATIVAS_MG: Final = "escolas_ativas_mg"

#: Definição publicada em `meta.definicoes` e no OpenAPI (2b R4:
#: `retencao_liquida_proxy_pct` nunca é "evasão").
DEFINICAO_RETENCAO: Final = (
    "Proxy de retenção líquida (saldo de série): mat_t / mat_{t-1} × 100. "
    "Não é taxa de evasão."
)
