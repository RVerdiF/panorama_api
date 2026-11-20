# Identidade da API no GCP: SA dedicada, IAM mínimo, sem chave

Card `t_b44f8df1` (origem: plano `t_1a70ba25` §1–3).

A API roda com uma service account própria — `panorama-api-runtime` — que **só**
cria jobs no projeto e **só** lê o dataset de serving. Não existe chave JSON:
a autenticação é ADC/impersonação.

| escopo | papel | efeito |
|---|---|---|
| projeto | `roles/bigquery.jobUser` | cria jobs de consulta; não lê nem escreve dados |
| `panorama_serving` | `READER` (`roles/bigquery.dataViewer`) | lê as tabelas/views publicadas |
| — | nenhum outro papel, em nenhum outro dataset | — |

Sem `roles/bigquery.readSessionUser` nesta fase.

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
| `tests/unit/test_api_runtime_sa.py` | 22 testes herméticos: garante que o spec não afrouxa e que o diff acusa excesso |

O script não fixa projeto, SA nem dataset: tudo vem do YAML. Nenhum caminho
pessoal no código nem no spec (testado).

```bash
.venv/bin/python scripts/gcp_api_runtime_sa.py plan     # o que falta/sobra
.venv/bin/python scripts/gcp_api_runtime_sa.py verify   # exit 1 se divergir
.venv/bin/python scripts/gcp_api_runtime_sa.py apply --yes
```

`apply` sem `--yes` é recusado (exit 2) antes de qualquer chamada ao GCP.
`apply` é idempotente: cria só o que falta e termina rodando `verify`.

## Estado verificado (2026-11-19, após `apply` autorizado)

| item | estado |
|---|---|
| SA `panorama-api-runtime` | **existe** (`Panorama API runtime`), criada em 2026-11-19 |
| papéis no projeto para a SA | **só** `roles/bigquery.jobUser` |
| papéis em datasets para a SA | **só** `READER` em `panorama_serving` |
| chaves `USER_MANAGED` | nenhuma (só `SYSTEM_MANAGED`) |
| `constraints/iam.disableServiceAccountKeyCreation` | **enforced** (efetiva no projeto) |
| datasets no projeto | só `panorama_serving` (location `us-central1`) |
| `verify` | **exit 0** |

O dono tem `roles/iam.serviceAccountTokenCreator` no projeto: dá para provar o
que a SA pode fazer por impersonação, sem gerar chave.

Correção em relação ao card: `panorama-escola-build@` não existe mais; a SA de
build hoje é `panorama-data-build@`.

## Sondas e limitação real da API do Cloud Resource Manager

`cloudresourcemanager.googleapis.com` **não está habilitada** no projeto
`panorama-escola-staging`. Consequências medidas:

- com token de **usuário**, `getIamPolicy`/`testIamPermissions` funcionam;
- com token da **SA**, a mesma chamada devolve `403 SERVICE_DISABLED`, porque o
  projeto consumidor passa a ser o do próprio token.

Por isso a sonda de escopo projeto **não** usa `testIamPermissions` do CRM:

| escopo | prova | como |
|---|---|---|
| positivo `bigquery.jobs.create` | job `dryRun` real como a SA | HTTP 200 |
| negativo `resourcemanager.projects.*` | papel concedido | tentativa real de `getIamPolicy` → 403 |
| negativo de excesso de papel | lista exata de bindings | `compute_diff` acusa qualquer papel a mais |

Se a tentativa devolver `SERVICE_DISABLED`, o `verify` emite **aviso** — não
`ok`. API desabilitada nega a qualquer identidade e não distingue IAM; a
ausência continua provada pela lista exata de papéis, que é o que o
`compute_diff` garante.

`bigquery.datasets.create` também saiu da sonda de dataset: é permissão de
projeto e o `testIamPermissions` do dataset responde 400 (`not valid for this
resource`). A negativa dela é provada pela tentativa real (403, check 3).

```text
$ .venv/bin/python scripts/gcp_api_runtime_sa.py verify
aviso: projeto: sonda de resourcemanager.projects.getIamPolicy inconclusiva: API desabilitada no projeto (a ausência segue provada pela lista exata de papéis)
aviso: projeto: sonda de resourcemanager.projects.setIamPolicy inconclusiva: API desabilitada no projeto (a ausência segue provada pela lista exata de papéis)
ok: SA, IAM mínimo, ausência de chave e org policy conforme o spec.
```

## Checks negativos

Executados em **2026-11-19** com impersonação — o token é da SA, não do dono:

```bash
SA=panorama-api-runtime@panorama-escola-staging.iam.gserviceaccount.com
```

| # | check | esperado | medido |
|---|---|---|---|
| 1 | criar tabela (`CREATE TABLE`/`tables.insert`) | 403 | **403** — `Permission bigquery.tables.create denied on dataset panorama-escola-staging:panorama_serving` |
| 2 | ler dataset fora de `panorama_serving` | 403 | **N/A** — staging só tem `panorama_serving` (ver nota) |
| 3 | criar dataset (`bq mk`) | 403 | **403** — `User does not have bigquery.datasets.create permission in project` |
| 4 | criar chave JSON | 403 | **403** — `Permission 'iam.serviceAccountKeys.create' denied` |
| 5 | extract para GCS | 403 na escrita | **job aceito, escrita negada** — `does not have storage.objects.create access` |

Controles positivos (têm de passar, senão o IAM mínimo quebrou):

| controle | medido |
|---|---|
| job `dryRun` `SELECT 1` como a SA | **200** |
| `tables.list` em `panorama_serving` | **200** |
| `testIamPermissions` do dataset | concedidas: `datasets.get`, `tables.getData`, `tables.list`; ausentes: `datasets.update`, `tables.create`, `tables.updateData` |

Notas de correção (o que a observação real desmentiu):

- **Check 2**: `bq ls`/`datasets.list` no projeto **não** falha. O BigQuery
  devolve 200 com a lista **filtrada por acesso** — no caso, um único dataset,
  `panorama_serving`. Não é privilégio a mais. A negativa que importa (não ler
  outro dataset) não tem alvo em staging; fica registrada como pendência se
  surgir um dataset de pipeline no projeto.
- **Check 5**: o extract **não** é recusado na criação do job — `jobUser` +
  `dataViewer` bastam para montar o job. A negativa observável é a do Cloud
  Storage, no destino: `storage.objects.create` negado. Validar o 403 no
  **status final do job**, não na inserção.
- **Check 1**: a sonda de dataset não pode incluir `bigquery.datasets.create`
  (400 `not valid for this resource`).
- Registro de evidência: mensagem **real** de cada check está na seção
  "Evidência de execução".

## Procedimento de execução (só com autorização do dono)

1. Dono autoriza explicitamente a alteração em `panorama-escola-staging`.
2. `.venv/bin/python scripts/gcp_api_runtime_sa.py plan` — conferir o diff.
3. `.venv/bin/python scripts/gcp_api_runtime_sa.py apply --yes`.
4. Rodar os cinco checks negativos e o controle positivo acima; registrar saída
   real no card.
5. `.venv/bin/python scripts/gcp_api_runtime_sa.py verify` — tem de sair em 0.

## Rollback

```bash
gcloud iam service-accounts keys list \
  --iam-account=panorama-api-runtime@panorama-escola-staging.iam.gserviceaccount.com \
  --project=panorama-escola-staging            # só SYSTEM_MANAGED
gcloud projects remove-iam-policy-binding panorama-escola-staging \
  --member=serviceAccount:panorama-api-runtime@panorama-escola-staging.iam.gserviceaccount.com \
  --role=roles/bigquery.jobUser --quiet
# dataset: remover a entrada userByEmail do access de panorama_serving
gcloud iam service-accounts delete \
  panorama-api-runtime@panorama-escola-staging.iam.gserviceaccount.com \
  --project=panorama-escola-staging --quiet
```

Nenhum dado é movido ou apagado por este card: o rollback só remove IAM e a SA.

## Uso pela API

O serviço Cloud Run da API deve rodar com esta SA
(`--service-account=panorama-api-runtime@…`), sem `--set-secrets` de chave e sem
`GOOGLE_APPLICATION_CREDENTIALS`. Ver `infra/cloud-run/service.yaml`.

## Evidência de execução

Execução autorizada pelo dono em 2026-11-19 (`"autorizo"`), projeto
`panorama-escola-staging`.

`apply --yes`:

```text
criando SA panorama-api-runtime@panorama-escola-staging.iam.gserviceaccount.com
concedendo roles/bigquery.jobUser no projeto
concedendo READER no dataset panorama_serving
```

IAM resultante (leitura independente, `gcloud projects get-iam-policy`):

```text
roles/bigquery.jobUser  serviceAccount:panorama-api-runtime@panorama-escola-staging.iam.gserviceaccount.com
```

Único binding da SA; nenhuma outra SA do pipeline foi tocada.

Dataset `panorama_serving` (`access`, inalterado fora da nova entrada):

```text
READER  userByEmail  panorama-api-runtime@panorama-escola-staging.iam.gserviceaccount.com
```

Chaves da SA:

```text
e06cbfc1...  SYSTEM_MANAGED      # nenhuma USER_MANAGED
```

Mensagens reais dos checks (token impersonado da SA):

```text
P1  jobs.create dryRun ................ 200
P2  tables.list panorama_serving ...... 200
N1  datasets.list ..................... 200, lista filtrada = ["panorama_serving"]
N2  datasets.create ................... 403  User does not have bigquery.datasets.create permission in project panorama-escola-staging.
N3  tables.create ..................... 403  Permission bigquery.tables.create denied on dataset panorama-escola-staging:panorama_serving
N4  keys.create ....................... 403  Permission 'iam.serviceAccountKeys.create' denied
N5  extract (job aceito, destino negado)
      Access Denied: does not have storage.objects.create access to the Google Cloud Storage object.
      Permission 'storage.objects.create' denied on '//storage.googleapis.com/projects/_/buckets/panorama-escola-staging-admin/objects/neg-check.csv'
N6  projects.getIamPolicy como a SA ... 403 SERVICE_DISABLED (API do CRM desabilitada no projeto)
```

Nenhum recurso foi criado pelos checks: `datasets.create` e `tables.create`
retornaram 403, e o job de extract falhou na escrita do destino.
