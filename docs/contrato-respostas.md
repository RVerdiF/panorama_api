# Regras comuns de resposta — contrato `serving-marts` / `mvp-1`

Regras que valem para **toda** resposta de dados da API. O detalhe por endpoint e
as decisões de implementação estão em `docs/api-v1.md`; o escopo que ficou fora da
v1 está em `docs/escopo-adiado-v1.md`.

Origem: plano 2b (`t_7761f96d` — `~/hermes/docs/panorama-api/t_7761f96d-regras-resposta.md`),
registrado neste repositório pelo card `t_e6cd849e`.

Todo nome de coluna citado aqui existe em `panorama_escola/dbt/models/marts`
(`*.sql` + `schema.yml`) e foi conferido por grep nessa árvore. Quando uma regra
depende de algo que **não** está nos marts, isso é dito explicitamente — nenhuma
coluna fora do contrato é apresentada como servida.

## R1. Envelope e metadados (`meta`)

```json
{ "data": <objeto ou lista>, "meta": { ... }, "page": { ... } }
```

`data` e `meta` existem em toda resposta de dados; `page` existe **somente** em
endpoint de lista. Requisição inválida nunca produz `200` com `data` vazio nem com
zeros (ver R5).

| campo `meta` | origem real | regra |
|---|---|---|
| `contract` / `contract_version` | `panorama_escola/publish/marts_contract.json` → `serving-marts` / `mvp-1` | par fixado em um único ponto do código (`src/panorama_api/contract.py`), sobrescrevível por `API_CONTRACT_VERSION` quando o contrato virar `mvp-2` |
| `ano_referencia` | `nu_ano_censo` (not_null em todos os marts) | ano efetivamente servido; `null` quando a resposta não tem recorte de ano (ex.: dimensão corrente) |
| `etapa` | `etapa` | enum `bas`, `creche`, `pre`, `fund_ai`, `fund_af`, `med`, `prof`, `eja`, `esp`. `bas` é o total oficial (`qt_mat_bas`) — **nunca** somar subetapas para obtê-lo. `null` quando a resposta cobre as 9 etapas |
| `universo` | recorte populacional do endpoint | `escolas_ativas_mg` (mercado, share, concentração), `privadas_ativas_mg` (indicadores, competidores), `escolas_mg` (`dim_escola`/`mart_escola`, que incluem escolas inativas) |
| `fonte` | INEP — Censo Escolar, via `serving-marts` | `{"orgao":"INEP","base":"Censo Escolar","tabela":"<mart ou view>"}` — a tabela apontada é sempre uma view estável do contrato |
| `cobertura` | contagens `n_escolas_*` do `mart_mercado` | obrigatório onde a resposta tem agregado; ver R3 |
| `avisos` | `is_abaixo_porte`, `flg_metodologia_incomparavel` | lista de códigos aplicáveis (ex.: `IS_ABAIXO_PORTE`, `METODOLOGIA_INCOMPARAVEL_<ano>`); lista vazia quando não há |
| `definicoes` | texto contratual | definições semânticas obrigatórias do payload (ex.: `retencao_liquida_proxy_pct`, ver R4) |

`meta.universo` não tem valor `brasil`: a v1 é MG-only e nenhum endpoint serve
recorte nacional. `escolas_mg` é um valor adicional ao plano 2b, necessário porque
`dim_escola`/`mart_escola` incluem escolas não ativas — reutilizar
`escolas_ativas_mg` nesses endpoints seria incorreto.

## R2. NULL ≠ 0 (AGENTS.md §6)

- `NULL` do mart é serializado como JSON `null`. É proibido `COALESCE(..., 0)`,
  default `0` em schema de resposta e omissão do campo.
- Toda métrica anulável é exposta **junto da flag real** que explica a ausência:

| família | métrica | flag do mart |
|---|---|---|
| matrícula escola-ano (`mart_escola`) | `qt_mat_bas` | `is_qt_mat_bas_missing` |
| matrícula por etapa (`mart_escola`) | `qt_mat_<etapa>` | `is_qt_mat_<etapa>_missing` (creche, pre, fund_ai, fund_af, med, prof, eja, esp) |
| matrícula escola×etapa (`fato_escola_etapa_ano`) | `qt_matricula` | `is_missing` |
| rendimento (`fato_escola_ano`, `mart_escola`) | `tx_aprov_*`, `tx_reprov_*`, `tx_aband_*` | `is_tx_aprov_fund_t_missing`, `is_tx_reprov_fund_t_missing`, `is_tx_aband_fund_t_missing`, `is_tx_aprov_med_t_missing`, `is_tx_aprov_fund_ai_missing`, `is_tx_aprov_fund_af_missing` |
| rendimento escola×etapa (`fato_escola_etapa_ano`) | `tx_rendimento_*` | `is_tx_rendimento_missing` + `tem_rendimento_mapeado` |
| oferta (`dim_escola`, `mart_escola`) | `of_<etapa>` tri-estado | `is_oferta_desconhecida` |
| share / KPIs (`mart_market_share`, `mart_escola_indicadores`) | `share_privado_pct`, `share_total_pct`, `crescimento_yoy_pct` | `is_abaixo_porte` (ou ausência de ano anterior) |
| mantenedora (`dim_escola`, `mart_escola`) | CNPJ da mantenedora | `is_cnpj_mantenedora_missing`, `is_cnpj_generic` |
| denominadores (`mart_mercado`, `mart_market_share`) | `qt_mat_privada`, `qt_mat_total` | podem ser `null` ("nenhuma escola com valor declarado"); as contagens `n_escolas_*` são not_null |

- **Oferta é tri-estado.** `of_<etapa>` = `1` (matrícula > 0), `0` (zero
  declarado), `NULL` (desconhecido). A API expõe `oferta.<etapa>` como
  `true` / `false` / `null`. `is_oferta_desconhecida = true` **não** significa
  "sem oferta", e `null` não pode ser lido como `false`.
- **As flags de rendimento não são 1:1 com as taxas.** O mart publica 6 flags de
  rendimento; não existem `is_tx_reprov_fund_ai_missing`,
  `is_tx_aband_med_t_missing` etc. A API não inventa flag que o mart não tem.
- Ausência legítima de linha é `200` com `data: []` (ex.: busca por nome sem
  resultado). Ausência de **dado** nunca é convertida em zero.

## R3. Histórico da escola e `mart_mercado`

- **Histórico** (`/v1/schools/{co_entidade}/history`): série por `nu_ano_censo`,
  com identificação, oferta, matrícula + flags, rendimento + flags e
  geolocalização, sempre a partir das tabelas do contrato (`fato_escola_ano`,
  `fato_escola_etapa_ano`, `mart_escola_indicadores` — inclusive
  `flg_entrou_mercado`).
- As flags de mudança de atributo da escola (nome, mantenedora, situação,
  categoria, oferta) vivem em `int_escola_historico`, que **não** faz parte do
  contrato `mvp-1`: a v1 não as publica. Decisão registrada no card `t_1896a564`;
  nada é inferido no lugar delas.
- **`mart_mercado`**: `cobertura` é sempre presente e traz as 5 contagens
  `n_escolas_ativas`, `n_escolas_com_linha_matricula`,
  `n_escolas_mat_linha_missing`, `n_escolas_mat_valor_missing`,
  `n_escolas_mat_missing`. O mart serve **9 etapas** (`bas` + 8 subetapas), e a
  cobertura é por etapa: não se agregam etapas somando-as.
- `n_escolas_entraram`, `n_escolas_sairam` e `n_escolas_ativas_com_baseline` são
  `null` no primeiro ano da série (sem baseline) e continuam `null`.

## R4. "Evasão" não é exposta

- Nenhum campo, rota, filtro, label ou aviso chamado `evasao`/`evasão`.
- O único indicador correlato é `retencao_liquida_proxy_pct`
  (`mart_escola_indicadores`), sempre acompanhado da definição em `meta.definicoes`
  e no OpenAPI:
  > Proxy de retenção líquida (saldo de série): mat_t / mat_{t-1} × 100.
  > **Não é taxa de evasão.**
- `tx_aband_fund_t` / `tx_aband_med_t` são **taxa de abandono** (rendimento INEP),
  não evasão.

## R5. Erro — RFC 9457 (`application/problem+json`)

```json
{
  "type": "https://api.panorama/erros/parametro-invalido",
  "title": "Parâmetro inválido",
  "status": 422,
  "detail": "etapa 'xyz' não pertence a {bas,creche,pre,fund_ai,fund_af,med,prof,eja,esp}",
  "instance": "/v1/markets/3106200",
  "code": "PARAMETRO_INVALIDO",
  "errors": [{ "loc": ["query", "etapa"], "msg": "..." }]
}
```

| HTTP | `code` | quando |
|---|---|---|
| 400 | `PARAMETRO_INVALIDO` | busca sem critério; parâmetro fora da allowlist do endpoint |
| 404 | `NAO_ENCONTRADO` | escola/município inexistente no recorte MG; escola fora do universo do endpoint |
| 404 | `ANO_FORA_DO_CONTRATO` | ano/etapa sem linha no mart |
| 422 | `PARAMETRO_INVALIDO` | formato ou domínio inválido; `limit`/`offset` fora do teto |
| 503 | `FONTE_INDISPONIVEL` | BigQuery indisponível, timeout ou teto de bytes |
| 500 | `ERRO_INTERNO` | fallback, sem stack nem SQL no corpo |

`code` é sempre um dos cinco valores acima (enum fechado em `core/errors.py`), de
modo que o cliente pode ramificar sem parsear `detail`. Erro nunca vira `200` com
lista vazia nem com zeros.

## R6. Paginação

- Offset/limit: `limit` (default e teto **por endpoint**, conforme o custo da
  consulta) e `offset` (default `0`), com `offset ≤ 1000`.
  - `/v1/schools`: `limit` default 20, máx 100.
  - `/v1/markets/{co_municipio}/share`: `limit` default 50, máx 200.
- Resposta de lista: `page = {"limit", "offset", "returned", "has_more"}`.
  `has_more` vem de `LIMIT L+1` (uma linha extra, descartada). O próximo offset é
  `offset + returned` quando `has_more` é `true`.
- **Não existe `page.total`.** Um `COUNT(*)` no BigQuery seria um scan extra por
  requisição; ver "Emendas ao plano 2b" abaixo.
- Ordenação determinística obrigatória para que `offset` seja estável: chave
  natural do `unique_composite` do mart, sempre com desempate explícito por
  identificador, e `NULL` sempre por último.

## Exemplos de estrutura (sem valores inventados)

Escola com matrícula suprimida e oferta desconhecida:

```json
{
  "data": {
    "co_entidade": "<co_entidade>",
    "nu_ano_censo": "<ano>",
    "matricula": { "qt_mat_bas": null, "is_qt_mat_bas_missing": true },
    "oferta": { "fund_ai": null, "fund_af": null, "med": null, "is_oferta_desconhecida": true },
    "rendimento": { "tx_aprov_fund_t": null, "is_tx_aprov_fund_t_missing": true }
  },
  "meta": {
    "contract": "serving-marts",
    "contract_version": "mvp-1",
    "ano_referencia": "<ano>",
    "etapa": "bas",
    "universo": "escolas_mg",
    "fonte": { "orgao": "INEP", "base": "Censo Escolar", "tabela": "mart_escola" },
    "cobertura": null,
    "avisos": []
  }
}
```

Mercado municipal com denominador ausente:

```json
{
  "data": {
    "co_municipio": "<co_municipio>",
    "nu_ano_censo": "<ano>",
    "etapa": "med",
    "qt_mat_privada": null,
    "qt_mat_total": "<valor ou null>"
  },
  "meta": {
    "contract": "serving-marts",
    "contract_version": "mvp-1",
    "ano_referencia": "<ano>",
    "etapa": "med",
    "universo": "escolas_ativas_mg",
    "fonte": { "orgao": "INEP", "base": "Censo Escolar", "tabela": "mart_mercado" },
    "cobertura": {
      "n_escolas_ativas": "<n>",
      "n_escolas_com_linha_matricula": "<n>",
      "n_escolas_mat_linha_missing": "<n>",
      "n_escolas_mat_valor_missing": "<n>",
      "n_escolas_mat_missing": "<n>"
    },
    "avisos": ["IS_ABAIXO_PORTE"]
  }
}
```

`<...>` marca valor que vem do mart: nenhum número é inventado neste documento.

## Emendas ao plano 2b (registro)

Três pontos do plano 2b foram decididos de outra forma durante a implementação da
v1. Ficam registrados aqui para que a documentação não descreva um contrato que o
serviço não serve:

| plano 2b (`t_7761f96d`) | regra em vigor | motivo |
|---|---|---|
| `page = {limit, offset, total, next_offset}` | `page = {limit, offset, returned, has_more}`; próximo offset = `offset + returned` | `COUNT(*)` no BigQuery é scan extra por requisição; `has_more` usa `LIMIT L+1` (decisão registrada em `docs/api-v1.md` e em `schemas/common.py`) |
| `limit` default 50 / máx 500 para toda a API | default e teto por endpoint (20/100 em `/v1/schools`, 50/200 em `/share`), `offset ≤ 1000` | teto calibrado pelo custo da consulta de cada endpoint |
| `universo` incluía `brasil` (endpoints de `fato_*`) | v1 é MG-only: `brasil` não existe; `escolas_mg` foi acrescentado | `dim_escola`/`mart_escola` incluem escolas não ativas, então `escolas_ativas_mg` mentiria nesses endpoints |

## Como verificar

```bash
# todo identificador citado neste documento existe nos marts?
grep -rnoE 'is_qt_mat_[a-z_]+_missing|is_tx_[a-z_]+_missing|of_(creche|pre|fund_ai|fund_af|med|prof|eja|esp)|n_escolas_[a-z_]+' \
  ../../panorama_escola/dbt/models/marts/
```

O contrato implementado (tipos, validações e custo por consulta) está em
`docs/api-v1.md`.
