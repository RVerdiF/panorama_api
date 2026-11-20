# API v1 — implementação do contrato `serving-marts` / `mvp-1`

Card `t_51cb08b2`. Spec canônica: `api-v1-contrato.md` §10 + regras comuns do 2b
(`t_7761f96d-regras-resposta.md`), com as emendas do gateway de 2026-11-17.

## Regras transversais

1. **Allowlist fixa no código.** Cada endpoint tem uma consulta parametrizada
   (`@param` do BigQuery). Nome de tabela/coluna/ordenação nunca vem do cliente;
   `order`/`fields` não existem e qualquer query string fora da allowlist do
   endpoint responde **400** `PARAMETRO_INVALIDO`.
2. **Origem = views estáveis** `` `${BQ_PROJECT}.${BQ_DATASET}.<tabela>` ``.
   Nunca `__history_*`, `__publish_*`.
3. **Escopo MG** (`sg_uf = 'MG'`, `is_mg = TRUE`).
4. **NULL ≠ 0.** NULL do mart sai como `null`; nenhum `COALESCE(...,0)` e nenhum
   default `0` em schema de resposta. Métricas anuláveis vão junto da flag
   `is_*_missing` do mart.
5. **Oferta tri-estado.** `of_<etapa>` (INTEGER 1/0/NULL) → `oferta.<etapa>` =
   `true` / `false` / `null`. `is_oferta_desconhecida=true` **não** significa
   "sem oferta"; `null` **não** pode ser lido como `false`.
6. **Validação antes do BigQuery** (422): `co_entidade` `^\d{8}$` (STRING),
   `co_municipio` `^31\d{5}$` (STRING), `ano` inteiro 2000–2100,
   `etapa ∈ {bas, creche, pre, fund_ai, fund_af, med, prof, eja, esp}`,
   `entidade_tipo ∈ {escola, mantenedora}`, `limit`/`offset` com teto por endpoint,
   `offset ≤ 1000`.
7. **Teto de bytes por consulta** via `API_BQ_MAX_BYTES_BILLED` (**256 MB**,
   teto canônico da decisão D2 — ver "Custo por consulta").
   Excesso/timeout/erro do BigQuery → **503** `FONTE_INDISPONIVEL` (sem SQL no corpo).
8. **Cache HTTP.** Resposta `200` de `GET /v1/*` leva
   `Cache-Control: public, max-age=86400, stale-while-revalidate=604800` e
   `ETag = sha256(DATA_VERSION + caminho + query canônica)`. `If-None-Match`
   igual → **304** sem corpo. Erro nunca é cacheado nem recebe esses
   cabeçalhos. Detalhes em `docs/operacao-custo.md`.

## Envelope

```json
{
  "data": "<objeto ou lista>",
  "meta": {
    "contract": "serving-marts",
    "contract_version": "mvp-1",
    "ano_referencia": 2025,
    "etapa": "bas",
    "universo": "escolas_mg",
    "fonte": {"orgao": "INEP", "base": "Censo Escolar", "tabela": "dim_escola"},
    "cobertura": {"n_escolas_ativas": 100},
    "avisos": [],
    "definicoes": {"retencao_liquida_proxy_pct": "..."}
  },
  "page": {"limit": 20, "offset": 0, "returned": 20, "has_more": true}
}
```

- `page` existe **somente** em endpoints de lista (`/v1/schools`,
  `/v1/markets/{co}/share`). `has_more` vem de `LIMIT L+1`; **não existe `total`**
  (`COUNT(*)` no BigQuery seria um scan extra).
- `meta.etapa` é `null` quando a resposta cobre as 9 etapas (`/v1/markets` sem
  `etapa`) e `bas` nos endpoints sem dimensão de etapa (o total oficial nunca é
  obtido somando subetapas).
- `meta.universo`: `escolas_mg` (dim_escola/mart_escola),
  `privadas_ativas_mg` (indicadores/competidores),
  `escolas_ativas_mg` (mercado/share).
- `meta.avisos`: códigos como `IS_ABAIXO_PORTE` e
  `METODOLOGIA_INCOMPARAVEL_<ano>`.
- `meta.cobertura`: obrigatório onde há agregado. Em `mart_mercado` a cobertura é
  **por etapa**, então ela aparece em cada item e em `meta` só quando a resposta
  tem uma única linha — não se agregam 9 etapas inventando somas.

## Erros (RFC 9457)

```json
{
  "type": "https://api.panorama/erros/parametro-invalido",
  "title": "Parâmetro inválido",
  "status": 422,
  "detail": "etapa 'xyz' não pertence a {bas,creche,pre,fund_ai,fund_af,med,prof,eja,esp}",
  "instance": "/v1/markets/3106200",
  "code": "PARAMETRO_INVALIDO",
  "errors": [{"loc": ["query", "etapa"], "msg": "..."}]
}
```

| HTTP | `code` | quando |
|---|---|---|
| 400 | `PARAMETRO_INVALIDO` | busca sem critério; parâmetro desconhecido |
| 404 | `NAO_ENCONTRADO` | escola/município inexistente no recorte MG; escola fora do universo de indicadores |
| 404 | `ANO_FORA_DO_CONTRATO` | ano/etapa sem linha no mart |
| 422 | `PARAMETRO_INVALIDO` | formato/domínio inválido, `limit`/`offset` fora do teto |
| 503 | `FONTE_INDISPONIVEL` | BigQuery indisponível, timeout ou teto de bytes |
| 500 | `ERRO_INTERNO` | fallback sem stack/SQL no corpo |

Erro nunca vira `200` com lista vazia nem com zeros. `200` com `data: []` só
acontece onde a ausência é legítima (busca por nome sem resultado; mercado
existente sem linhas de share).

## Endpoints

### `GET /health`
Liveness puro: não toca no BigQuery.
`{"status":"ok","version":"<app>","contract":"serving-marts/mvp-1"}`.

### `GET /v1/schools`
`q` (contém, case-insensitive, 3–100 chars), `co_entidade`, `co_municipio`,
`tp_dependencia` (código INEP cru), `apenas_ativas` (bool, default `false`),
`limit` (default 20, máx 100), `offset` (máx 1000). Ao menos um de
`q`/`co_entidade`/`co_municipio` é obrigatório (senão 400).
`co_entidade` sem linha → 404 (lookup por identidade); `q` sem resultado → `[]`.
Ordenação: `no_entidade ASC NULLS LAST, co_entidade ASC` — implementada como
`ORDER BY (no_entidade IS NULL), no_entidade, co_entidade` porque o BigQuery não
garante `NULLS LAST` em todas as versões.
Excluídos na v1: `nu_cnpj_escola_privada`, `cnpj_completo_mantenedora`, `co_uf`,
`co_distrito`, `tp_localizacao_diferenciada`, `is_cnpj_mantenedora_missing`.

### `GET /v1/schools/{co_entidade}/history`
`ano_inicio`, `ano_fim` opcionais (`ano_inicio ≤ ano_fim`, senão 422). Sem
paginação; ordenado por `nu_ano_censo ASC`. Cabeçalho
(`co_entidade`, `no_entidade`, `co_municipio`, `no_municipio`) vem do ano mais
recente da resposta; `items[]` tem uma linha por ano com identificação, oferta,
matrícula + flags, rendimento + flags e geolocalização. 0 linhas → 404.
Excluídos: `geom`, `endereco_origem`, `ano_endereco_origem`, `geocoder`,
CNPJs completos, `is_mg`.

### `GET /v1/schools/{co_entidade}/indicators`
`ano` opcional (sem ele, a série inteira). Base `mart_escola_indicadores`
(privadas ativas MG, base BAS) + `mart_competidores` no mesmo grão.
Escola ausente de `dim_escola` → 404 `NAO_ENCONTRADO`; presente em MG mas fora do
universo (pública/inativa) → 404 `NAO_ENCONTRADO` com detalhe do universo;
`ano` sem linha mas com série em outros anos → 404 `ANO_FORA_DO_CONTRATO`.
`meta.definicoes.retencao_liquida_proxy_pct`: "Proxy de retenção líquida (saldo
de série): mat_t / mat_{t-1} × 100. **Não é taxa de evasão.**" (2b R4 — nenhum
campo/rota/label chamado "evasão").

### `GET /v1/schools/{co_entidade}/competitors`
Comparação **municipal**: "Escolas privadas ativas no mesmo município e ano
censitário (MG)". Fonte `mart_competidores` (grão `co_entidade × nu_ano_censo`,
nível BAS); sem parâmetros de query (qualquer query string → 400), sem
paginação e ordenado por `nu_ano_censo ASC`. Cabeçalho
(`co_entidade`, `no_entidade`, `co_municipio`) vem do ano mais recente da
resposta.

Campos por ano: `qt_mat_bas`, `rank_mat_bas_municipio`,
`n_concorrentes_privados_municipio`, `n_concorrentes_com_matricula_bas`,
`n_concorrentes_{creche,pre,fund_ai,fund_af,med}_xself`, `lider_no_entidade`,
`lider_qt_mat_bas`, `gap_mat_bas_para_lider`. A mart não fornece lista nominal
de concorrentes, então a resposta **nunca** traz as escolas concorrentes por
nome.

Escola pública, inativa ou fora de MG → 404 `NAO_ENCONTRADO` com o universo no
detalhe; privada ativa sem matrícula BAS observada (portanto sem linha na mart)
→ 404 `NAO_ENCONTRADO` — ausência de dado nunca vira `0` concorrentes.
`gap_mat_bas_para_lider = 0` é medição válida (a própria escola lidera).
A unidade de comparação é o município e o ano censitário: não existe filtro
geográfico além de `co_municipio` e a resposta não traz lista nominal de escolas.

### `GET /v1/markets/{co_municipio}`
`ano` **obrigatório**, `etapa` opcional (sem ela, as 9 etapas do ano).
Município ausente de `dim_geografia` com `is_mg` → 404 `NAO_ENCONTRADO`;
`(município, ano[, etapa])` sem linha → 404 `ANO_FORA_DO_CONTRATO`.
Cada item traz `cobertura` (5 contagens de `mart_mercado`) e `concentracao[]`
(`mart_concentracao` do mesmo recorte, com `hhi`, `share_lider_pct`, `c4_pct`,
`soma_share_pct`, `recorte`, `nivel`, `n_competidores`).
`n_escolas_entraram`/`n_escolas_ativas_com_baseline`/`n_escolas_sairam` são NULL
no primeiro ano da série e continuam `null`.

### `GET /v1/markets/{co_municipio}/share`
`ano` e `etapa` **obrigatórios**; `entidade_tipo` default `escola`;
`limit` default 50 (máx 200), `offset` máx 1000.
Ordenação `mat_entidade DESC NULLS LAST, id_entidade ASC`.
Denominadores do mercado são enviados uma vez em `data.mercado`
(`n_escolas_privadas`, `n_escolas_ativas`, `qt_mat_privada`, `qt_mat_total`),
lidos da linha de share e, sem linhas, de `mart_mercado` — nunca zero inventado.
Para `entidade_tipo=mantenedora`, `no_entidade` vem de `dim_mantenedora.no_grupo`
(B5); `n_unidades` é NULL para escola; `no_entidade` pode ser NULL quando não há
grupo identificado. Escolas ausentes da tabela **não** são 0%.
Mercado existente sem linhas de share → `200` com `data.items: []`; mercado
inexistente → 404.

## Decisões de implementação (registradas)

1. **Busca por nome com `STRPOS`, não `LIKE`.** O BigQuery Standard SQL não
   aceita a cláusula `ESCAPE` do `LIKE` (verificado por dry-run: `Syntax error:
   Expected end of input but got keyword ESCAPE`). `STRPOS(LOWER(no_entidade),
   @q) > 0` dá o mesmo "contém" case-insensitive tratando `%`/`_` como texto
   literal, o que remove a necessidade de escaping.
2. **`NULLS LAST` explícito.** A ordenação fixa é escrita como
   `(coluna IS NULL), coluna ...` para não depender de suporte a `NULLS LAST`.
3. **`indicators` faz duas consultas allowlist** (`mart_escola_indicadores` e
   `mart_competidores`) e junta por `nu_ano_censo` em vez de um `LEFT JOIN` com
   prefixos de coluna. `meta.fonte.tabela` aponta a tabela primária.
4. **`mart_escola_indicadores` não tem colunas `of_*`** (confirmado no dataset):
   a oferta tri-estado é exposta em `/v1/schools` e `/history`, e em
   `/indicators` fica só `is_oferta_desconhecida`.
5. **Flags de rendimento não são 1:1 com as taxas.** O mart publica 6 flags
   (`is_tx_aprov_{fund_t,fund_ai,fund_af,med_t}_missing`,
   `is_tx_reprov_fund_t_missing`, `is_tx_aband_fund_t_missing`); não existem
   `is_tx_reprov_fund_ai_missing`, `is_tx_aband_med_t_missing` etc.
6. **`universo = escolas_mg`** em `/v1/schools` e `/history`: `dim_escola` e
   `mart_escola` incluem escolas não ativas, então reutilizar
   `escolas_ativas_mg` seria incorreto.
7. **`meta.etapa = null`** quando a resposta cobre as 9 etapas de um mercado:
   `bas` ali seria mentira (resposta não é só o total oficial).
8. **Validação de schema no startup** compara apenas nome + tipo das colunas
   usadas pela API (colunas novas não derrubam o boot; coluna faltando ou tipo
   trocado derrubam — falha fechada). Tipos de `INFORMATION_SCHEMA` são
   normalizados (`INT64→INTEGER`, `FLOAT64→FLOAT`, `BOOL→BOOLEAN`).
9. **`/competitors` reusa a linha de `mart_competidores` já usada por
   `/indicators`.** O schema `Competicao` virou `schemas/competitors.py` e é
   importado pelos dois endpoints (re-exportado de `schemas/indicators.py`), e o
   mapeamento linha→campos é uma função só, em `services/schools.py`. Assim os
   dois payloads não divergem quando a mart mudar. O endpoint é comparação
   municipal: `meta.definicoes.competidores` carrega a definição obrigatória e
   não há campo, filtro ou parâmetro de proximidade/raio.

## Custo por consulta (dry-run contra `panorama-escola-staging`, sem faturamento)

| consulta | bytes |
|---|---|
| `share` (escola ou mantenedora) | 181,1 MB |
| busca `q` / por `co_municipio` / por `co_entidade` (`dim_escola`) | 152,4 MB |
| `history` | 123,0 MB |
| `concentracao` | 41,3 MB |
| `indicators` | 21,8 MB |
| `market` | 21,2 MB |
| `competidores` | 14,6 MB |
| `municipio` | 1,2 MB |

O teto canônico é **256 MB** (`API_BQ_MAX_BYTES_BILLED` = `268435456`), decisão
D2 do `t_ec4d1b26`: todas as consultas acima passam, com folga menor na de share
(~29%).

**Gatilho de revisão.** Quando a clusterização do `t_cfe70dd5` entrar em
staging, remedir o pior caso por endpoint e fixar o teto em
`max(10 MB, menor potência de 2 em MB ≥ 2× pior caso)`. Até lá, 256 MB.
Referências que não são teto: **100 MB** (plano 2d original, superado pelo pior
caso medido) e **10 MB** (mínimo faturado por tabela, piso de faturamento, não
teto).

Reduzir o custo por consulta depende da clusterização por
`(__publish_run_id, co_municipio, co_entidade, nu_ano_censo)` no publish.
