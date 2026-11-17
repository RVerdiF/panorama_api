# panorama_api

API read-only do Panorama Escola (FastAPI) sobre as views do contrato de serving
`serving-marts` / `mvp-1` no BigQuery.

## Endpoints da v1

| método | rota | origem |
|---|---|---|
| GET | `/health` | nenhuma (liveness, sem BigQuery) |
| GET | `/v1/schools` | `dim_escola` (MG) |
| GET | `/v1/schools/{co_entidade}/history` | `mart_escola` |
| GET | `/v1/schools/{co_entidade}/indicators` | `mart_escola_indicadores` + `mart_competidores` |
| GET | `/v1/markets/{co_municipio}` | `mart_mercado` + `mart_concentracao` + `dim_geografia` |
| GET | `/v1/markets/{co_municipio}/share` | `mart_market_share` + `dim_mantenedora` |

Envelope de dados: `{ "data": ..., "meta": {...}, "page"?: {...} }`.
Erros: RFC 9457 `application/problem+json` (`type`, `title`, `status`, `detail`,
`instance`, `code`, `errors[]`).

Contrato detalhado (campos, validações, decisões): `docs/api-v1.md`.
OpenAPI interativo: `/docs` e `/openapi.json`.

## Ambiente

```bash
bash scripts/bootstrap_env.sh     # cria .venv (Python 3.12) e instala deps
```

## Testes

Camada hermética — não acessa BigQuery, rede nem dataset:

```bash
.venv/bin/python -m pytest
```

## Executar

```bash
.venv/bin/uvicorn panorama_api.main:app --host 0.0.0.0 --port 8080
```

Variáveis de ambiente:

| variável | default | efeito |
|---|---|---|
| `BQ_PROJECT` | `panorama-escola-staging` | projeto das views |
| `BQ_DATASET` | `panorama_serving` | dataset do contrato (só tabelas fixas no código) |
| `BQ_LOCATION` | `us-central1` | localização das consultas (dataset está lá) |
| `API_BQ_MAX_BYTES_BILLED` | `268435456` (256 MB) | teto de bytes por consulta |
| `API_VALIDATE_SCHEMA_ON_STARTUP` | `true` | validação nome+tipo das colunas no boot |
| `API_CONTRACT_VERSION` | `mvp-1` | versão do contrato exposta em `meta` |

A autenticação no BigQuery usa Application Default Credentials.

## Estrutura

```text
src/panorama_api/
├── api/v1/          # Rotas HTTP (health, escolas, mercados)
├── core/            # Erros RFC 9457, validação de entrada, validação de schema
├── repositories/    # Consultas allowlist + cliente BigQuery
├── schemas/         # Envelope, meta, paginação e payloads
└── services/        # Mapeamento linha do mart → resposta

tests/unit/          # Suíte hermética (repositório fake)
tests/integration/   # (vazio — integração com BQ fica fora da v1)
scripts/             # bootstrap_env.sh
docs/                # Documentação técnica
```
