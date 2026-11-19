# Identidade da API no GCP: SA dedicada, IAM mínimo, sem chave

Card `t_b44f8df1` (origem: plano `t_1a70ba25` §1–3).

A API roda com uma service account própria — `panorama-api-runtime` — que **só**
cria jobs no projeto e **só** lê o dataset de serving. Não existe chave JSON:
a autenticação é ADC/impersonação.

## Por que não reutilizar `panorama-escola-runtime`

Essa SA é a identidade de CI/pipeline e é gerenciada pelo Terraform do repo
`panorama_escola` (`infra/envs/staging/main.tf`), com `bigquery.dataEditor` +
`jobUser` + `logging` + `monitoring`. Alterá-la na mão vira drift no próximo
`terraform apply` e mistura o blast radius da API com o do pipeline.

## Fonte única

| arquivo | conteúdo |
|---|---|
| `infra/gcp/api-runtime-sa.yaml` | projeto, conta, papéis (projeto e dataset), política de chave e sondas de permissão |
| `scripts/gcp_api_runtime_sa.py` | `plan` (read-only), `verify` (falha se divergir), `apply --yes` (idempotente) |
| `tests/unit/test_api_runtime_sa.py` | garante que o spec não afrouxa e que o diff acusa excesso |

```bash
.venv/bin/python scripts/gcp_api_runtime_sa.py plan     # o que falta/sobra
.venv/bin/python scripts/gcp_api_runtime_sa.py verify   # exit 1 se divergir
```

`apply` sem `--yes` é recusado (exit 2) antes de qualquer chamada ao GCP.

## Estado verificado (2026-11-19, read-only)

- `panorama-api-runtime` **não existe** ainda; nada foi alterado no GCP.
- Projeto `panorama-escola-staging`, dataset `panorama_serving` em `us-central1`
  — único dataset do projeto.
- Org policy `constraints/iam.disableServiceAccountKeyCreation` **enforced**
  (efetiva no projeto).
- Nenhuma chave `USER_MANAGED` em nenhuma SA do projeto.
- O dono tem `roles/iam.serviceAccountTokenCreator` no projeto: dá para provar
  o que a SA pode fazer por impersonação, sem gerar chave.
- Correção em relação ao card: `panorama-escola-build@` não existe mais; a SA de
  build hoje é `panorama-data-build@`.

## Checks negativos

Executar **depois** de `apply --yes` autorizado, com impersonação — o token é da
SA, não do dono:

```bash
SA=panorama-api-runtime@panorama-escola-staging.iam.gserviceaccount.com
```

| # | check | comando | esperado |
|---|---|---|---|
| 1 | criar tabela | `bq --impersonate_service_account=$SA query --use_legacy_sql=false "CREATE TABLE panorama_serving.teste_sa_negativa AS SELECT 1 AS x"` | 403 — falta `bigquery.tables.create` |
| 2 | ler dataset do pipeline | `bq --impersonate_service_account=$SA show <projeto>:<dataset-do-pipeline>` | 403 — sem papel fora de `panorama_serving` |
| 3 | criar dataset | `bq --impersonate_service_account=$SA mk --dataset panorama-escola-staging:teste_sa_negativa` | 403 — falta `bigquery.datasets.create` |
| 4 | criar chave | `gcloud iam service-accounts keys create /tmp/k.json --iam-account=$SA` | 403 — org policy `iam.disableServiceAccountKeyCreation` |
| 5 | extract | `bq --impersonate_service_account=$SA extract --destination_format=CSV panorama_serving.<tabela> gs://<bucket-sem-acesso>/x.csv` | 403 — `storage.objects.create` negado no destino |

Controle positivo (tem que passar, senão o IAM mínimo quebrou):

```bash
bq --impersonate_service_account=$SA query --use_legacy_sql=false \
  "SELECT 1" --dry_run
bq --impersonate_service_account=$SA ls panorama-escola-staging:panorama_serving
```

Notas:

- O check 5 não depende de `bigquery.tables.export`: o job de extract pode até
  ser aceito, mas a escrita no bucket é negada — a negativa observável é do
  Cloud Storage. Validar o 403 no job inteiro, não na criação.
- O check 2 precisa de um dataset de referência que **não** seja
  `panorama_serving`. Em staging hoje só existe `panorama_serving`, então o
  alvo tem de ser confirmado com o dono antes de rodar (pendência aberta).
- `bq ls` no projeto (sem dataset) também deve falhar: `jobUser` não lista
  datasets do projeto.

## Procedimento de execução (só com autorização do dono)

1. Dono autoriza explicitamente a alteração em `panorama-escola-staging`.
2. `.venv/bin/python scripts/gcp_api_runtime_sa.py plan` — conferir o diff.
3. `.venv/bin/python scripts/gcp_api_runtime_sa.py apply --yes`.
4. Rodar os cinco checks negativos e o controle positivo acima; registrar saída
   real no card.
5. `.venv/bin/python scripts/gcp_api_runtime_sa.py verify` — tem de sair em 0.

Reverter (se necessário, também com autorização): remover os bindings, apagar a
SA (`gcloud iam service-accounts delete`). Nenhuma chave existe para revogar.

## Uso pela API

O serviço Cloud Run da API deve rodar com esta SA
(`--service-account=panorama-api-runtime@…`), sem `--set-secrets` de chave e sem
`GOOGLE_APPLICATION_CREDENTIALS`. Ver `infra/cloud-run/service.yaml`.
