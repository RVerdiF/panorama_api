# Observabilidade do front `/app` (card `t_88589ae7`, plano §7)

Mínimo do plano: **uma linha de log por requisição de página**, a métrica
derivada dessa linha, o alerta de 503 e um smoke manual. Não há RUM, não há
telemetria de JavaScript (o front não tem JS de aplicação) e **não há uptime
check** — o IAP bloqueia sonda anônima, e uma sonda que abrisse página com
BigQuery numa instância fria gastaria cota sem usuário real (plano §7.3).

Tudo reusa a infra de log existente: `panorama_api.core.logging_config` deixa o
logger `panorama_api` em `INFO` e emite **uma linha JSON por registro no
stdout**, que o Cloud Logging lê como `jsonPayload` (campos consultáveis).

## Linha `page_view`

Emitida por `panorama_api.web.observability.PageViewMiddleware` em toda
requisição de página sob `/app` — inclusive 4xx/5xx, e inclusive a resposta
servida sem executar o handler (LRU e 304). Assets `/app/static/*`, `/v1/*` e
`/health` **não** geram essa linha (não são páginas; o `/v1` já tem
`http_cache`/`bq_query`).

```json
{"severity": "INFO", "message": "page_view", "logger": "panorama_api.web.observability", "timestamp": "2026-11-23T18:38:34.454Z", "route": "/app/escolas/{co_entidade}", "status": 200, "cache": "miss", "ms": 32.7, "data_version": "2026.11.17", "app_build": "build-a", "user_hash": "9f1c0e5b7a2d4c88"}
```

| campo | origem |
|---|---|
| `route` | template da rota (`/app/escolas/{co_entidade}`), nunca o caminho concreto. Agregar por rota exige isso; caminho que não casa rota nenhuma (404) sai literal. |
| `status` | status HTTP entregue ao cliente (503 de fonte indisponível sai 503, não 500). |
| `cache` | `hit` (LRU) · `miss` (handler executado) · `304` (revalidação por `ETag`). A decisão vem do middleware de cache, que a publica em `request.scope`; o observador não reimplementa. |
| `ms` | duração da requisição inteira, em milissegundos. |
| `data_version` | `DATA_VERSION` do deploy. |
| `app_build` | `APP_BUILD` do deploy. |
| `user_hash` | `sha256(salt + email)[:16]` do e-mail do piloto; `anon` sem identidade. |

### `user_hash` — o e-mail nunca vai para o log

O e-mail vem de `X-Goog-Authenticated-User-Email`, que o IAP injeta como
`<emissor>:<email>` (ex. `accounts.google.com:piloto@exemplo.com`). Só o hash de
16 hex é logado: o critério de aceite do card é que o e-mail em claro **nunca**
apareça no stdout (há teste que captura o stdout e procura o e-mail).

O salt vem de `API_OBS_USER_HASH_SALT` (`Settings.obs_user_hash_salt`) e é
definido no deploy (F8), fora do manifesto versionado — é segredo operacional,
não configuração pública. Sem salt configurado o `user_hash` degrada para
`anon` e uma linha `page_view_user_hash_sem_salt` (severity `WARNING`) é emitida
uma vez por processo: e-mails corporativos são poucos e previsíveis, então um
SHA-256 sem salt seria reversível por dicionário — hashear sem salt esconderia
isso e daria aparência de anonimato.

Consequência operacional: trocar o salt muda os hashes de todos os pilotos (o
histórico antigo não correlaciona com o novo). Fixe o salt por temporada de
piloto e registre-o no gerenciador de segredos, não no repositório.

## Métricas de log e alerta de 503

`infra/gcp/cost-controls.yaml` declara duas métricas baseadas em log e o alerta:

| nome | base | uso |
|---|---|---|
| `page_view_por_rota` | `jsonPayload.message="page_view"` | uso do front agregado por `route`, `data_version`, `app_build` — base do critério de expansão do fundador (uso repetido por piloto, via `user_hash`) |
| `http_503_por_rota` | `jsonPayload.message="http_cache" AND jsonPayload.status=503` | superfícies que devolveram 503, separadas por `path` |
| alerta `http_503_acima_de_5_em_15min` | **≥ 5 respostas 503 em `/app` ou `/v1` em 15 min** | modo de falha mais provável: cota/teto de bytes do BigQuery estourado |

O 503 é diagnóstico de cota, não de código: `ProblemError(FONTE_INDISPONIVEL)`
(com `Retry-After: 300`) é o que a API devolve quando o BigQuery recusa o job.
Cinco ocorrências em 15 min é sinal de fonte recusando consultas, não ruído de
instância fria.

**Nada disso está aplicado no GCP** por este card: criar política de alerta,
métrica baseada em log e binding de notificação exige autorização do dono (F8).
O YAML é a fonte única da descrição; aplicar é o passo de deploy.

## Smoke manual pós-deploy (4 telas)

Não há sonda automática (ver plano §7.3). Após o deploy, o smoke é manual, com
login de piloto autorizado no IAP. Em cada URL, confirme **200**, conteúdo
esperado e **uma linha `page_view`** com o `route` correspondente.

Pré-requisito: `gcloud auth login` com uma conta na allowlist do IAP e o serviço
já implantado com IAP configurado (`docs/iap-cloud-run.md`).

```bash
SERVICE_URL="https://panorama-api-<hash>-uc.a.run.app"
TOKEN="$(gcloud auth print-identity-token)"
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $TOKEN" "$SERVICE_URL/app/metodologia"
```

| # | URL | deve responder | o que confirma |
|---|---|---|---|
| 1 | `/app/metodologia` | 200, HTML com `DATA_VERSION` e definições | fundação SSR viva, texto estático correto |
| 2 | `/app/?q=colegio` | 200, lista com paginação | busca consultando o serving (1 `miss` + `bq_query`) |
| 3 | `/app/escolas/<co_entidade privada ativa>` | 200, série + oferta + posição municipal | seções condicionais só para privada ativa |
| 4 | `/app/mercados/<co_municipio>?ano=<ano>&etapa=bas` | 200, tamanho/composição + share | seletor de ano e paginação do share |

Repetir a URL 1 com o navegador (segunda visita) deve devolver **304** — o
`page_view` correspondente sai com `cache: "304"`, o que confirma que a
revalidação não executa o handler.

Conferir as linhas emitidas (após os requests acima):

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND jsonPayload.message="page_view"' \
  --project panorama-escola-staging --freshness=15m --limit=20 \
  --format='value(jsonPayload.route,jsonPayload.status,jsonPayload.cache,jsonPayload.ms,jsonPayload.user_hash)'
```

Esperado: uma linha por request, `route` no formato de template, `status` 200
(nenhum 503), `cache` `miss` na primeira visita e `hit`/`304` na repetição, e
`user_hash` **igual** entre as visitas do mesmo piloto (identidade estável) mas
diferente de `anon`.

Falhas típicas:

- **403/302 para o login** → IAP/allowlist, não observabilidade; ver
  `docs/iap-cloud-run.md`.
- **503 com `Retry-After: 300`** → cota/teto de bytes; o alerta
  `http_503_acima_de_5_em_15min` deve aparecer se persistir.
- **nenhuma linha `page_view`** → `route` não pertence a `/app` (assets, `/v1`,
  `/health` não geram) ou `configure_logging` não rodou no processo.

## Registro do que este card não faz

- Sem RUM/telemetria JS, sem uptime check, sem dashboard novo.
- Sem mudança em `/v1` (resposta, status, headers, formato de erro).
- Sem alteração de `min-instances`, `max-instances`, `concurrency`, `timeout`,
  região, `maximum_bytes_billed` ou cota diária do BigQuery.
- Sem aplicar nada no GCP: alerta, métrica e budget só valem depois do F8.
