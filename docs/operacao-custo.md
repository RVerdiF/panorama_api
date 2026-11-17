# Operação: cache, limites e custo (card `t_817a670c`)

Regra do dono (2026-11-17): o serviço precisa caber na franquia gratuita do
Cloud Run e **nunca** gerar cobrança. `min-instances=0` (scale-to-zero) é
obrigatório e `max-instances` não passa de 3. Nada neste documento autoriza
subir esses valores; mudanças exigem autorização explícita do dono.

Arquivos versionados (fonte única dos números):

| arquivo | conteúdo |
|---|---|
| `infra/cloud-run/service.yaml` | manifesto do serviço: min/max instances, concurrency, timeout, CPU/memória, env |
| `infra/cloud-run/deploy.sh` | `gcloud run services replace` com região fixa e guardas de min/max |
| `infra/gcp/cost-controls.yaml` | cota do BigQuery, budget e descrição dos alertas |

O teste `tests/unit/test_infra_config.py` falha se o manifesto deixar de ter
`minScale=0`, `maxScale<=3`, `concurrency=20`, `timeout=15` ou região
`us-central1`, e se `cost-controls.yaml` divergir do manifesto.

## Cache HTTP

Toda resposta `200` de `GET /v1/*` sai com:

```text
Cache-Control: public, max-age=86400, stale-while-revalidate=604800
ETag: "<32 hex>"
```

- `ETag = sha256(DATA_VERSION + caminho + query canônica)` truncado em 32 hex.
  A query é ordenada por chave/valor, então `?a=1&b=2` e `?b=2&a=1` produzem o
  mesmo `ETag`.
- `If-None-Match` igual (aceita `W/"..."`, listas e `*`) devolve **304** sem
  corpo, com o mesmo `ETag`/`Cache-Control`. O 304 é decidido pelo hash, não
  pela presença no LRU — vale inclusive numa instância fria (scale-to-zero),
  que é onde ele mais economiza consulta. Premissa: dentro de uma
  `DATA_VERSION` a representação é imutável — publicar dados exige subir a
  versão (ver abaixo).
- **Erros não são cacheados**: 4xx/5xx não recebem `ETag` nem `Cache-Control`,
  não entram no LRU e a próxima requisição consulta o BigQuery de novo.
- `GET /health`, `/docs` e `/openapi.json` ficam fora do cache (só `/v1/*`).

### Invalidação por `DATA_VERSION`

`DATA_VERSION` é variável de ambiente do serviço (no manifesto). A chave do
cache e o `ETag` incluem esse valor; publicar dados novos = subir o serviço com
`DATA_VERSION` novo. Não existe varredura nem TTL explícito:

1. o `ETag` muda e todo cliente revalida (recebe 200 com corpo novo);
2. as entradas antigas do LRU deixam de ser consultadas e saem pela própria
   política LRU (teto de 1000 entradas).

O valor é validado (`[A-Za-z0-9._-]{1,64}`); vazio ou com caractere estranho
derruba o boot (falha fechada).

### LRU em memória

- 1000 entradas por instância, política LRU (`OrderedDict` + `move_to_end`).
  O corpo é guardado já serializado (JSON); um *hit* não chama serviço nem
  repositório.
- Memória: o teto é por entradas, não por bytes. Se todas as 1000 entradas
  forem respostas grandes (pior caso teórico: `market_share` com 200 linhas),
  o cache pode chegar a ~200 MB numa instância de 512 MiB. Monitorar memória;
  reduzir `max_entries` é ajuste de uma linha, não muda contrato.
- Sem Redis: com `max-instances=3` o pior caso é 3 caches independentes, o que
  é aceitável — um *hit* evita o BigQuery, que é o custo que importa.

## Cloud Run

| parâmetro | valor | motivo |
|---|---|---|
| região | `us-central1` | mesma do dataset `panorama_serving` e do Artifact Registry; Tier 1 |
| `min-instances` | `0` | scale-to-zero: sem tráfego, sem cobrança |
| `max-instances` | `3` | teto da regra do dono |
| `concurrency` | `20` | 20 requisições simultâneas por instância |
| timeout | `15 s` | acima do timeout de 10 s da consulta; abaixo do limite do Cloud Run |
| CPU/memória | `1` vCPU / `512 MiB` | 1 vCPU por request na conta da franquia |
| CPU throttling | `true` | CPU só durante a requisição (default; explícito para não mudar) |

Referência de franquia medida em 2026-11-17: **2M requests, 180k vCPU-s e
360k GiB-s por mês**. A 300 ms e 1 vCPU por request, a franquia cobre ~600 mil
requests/mês; acima disso o custo é Tier 1 (`us-central1`).

## Cota e budget

| controle | valor | comportamento |
|---|---|---|
| cota diária do BigQuery | **50 GB/dia** | corte duro: jobs recusados acima disso (503 na API), custo zero |
| teto por consulta | 256 MB (`BQ_MAX_BYTES_BILLED`) | provisório até a clusterização (`t_cfe70dd5`) |
| budget mensal | **US$ 20** | aviso por e-mail em 50%, 90% e 100%; não corta o serviço |

O budget não desliga nada: ele existe para avisar antes de o cartão ser
tocado. Quem impede a cobrança é a cota diária.

## Alertas

Todos são **aviso** (e-mail/notificação). Nenhum deles altera o serviço.
A descrição canônica fica em `infra/gcp/cost-controls.yaml`:

| alerta | condição | janela |
|---|---|---|
| bytes acima de 10 GB/dia | bytes faturados pelo projeto > 10 GB no dia | 1 dia |
| `bytesBilledLimitExceeded` | ≥ 1 job recusado por estourar `maximum_bytes_billed` | 5 min |
| latência p95 | p95 das requisições > 2 s | 5 min |
| erros 5xx | > 1% das respostas | 5 min |
| instâncias no teto | instâncias ativas = `max-instances` sem parar | 10 min |

## Logs estruturados

Duas linhas de log por requisição, ambas com campos consultáveis:

- `http_cache` — campos `cache` (`hit`/`miss`), `status`, `path`,
  `data_version`. `hit` = servido do LRU ou 304; `miss` = foi ao BigQuery.
- `bq_query` — campos `bq_ms` (tempo da consulta no BigQuery, em ms),
  `endpoint` (ex. `market_share`) e `status` (`ok`/`error`).

`bq_ms` é medido no único ponto que fala com o BigQuery
(`BigQueryServingRepository._run`), então o alerta de p95 consegue separar
latência de consulta de latência de rede/serialização.

Exemplo:

```text
http_cache cache=miss status=200 path=/v1/markets/3106200 data_version=2026.11.17
bq_query bq_ms=412.7 endpoint=market status=ok
http_cache cache=hit status=200 path=/v1/markets/3106200 data_version=2026.11.17
```

## O que ainda não está implantado

O manifesto e os controles de custo estão versionados, mas **não foram
aplicados** em nenhum projeto: criar budget, cota e políticas de alerta exige
autorização explícita do dono (e credencial válida). O teste de leitura em
staging (`t_9ab4b208`) é quem executa o deploy depois da autorização.
