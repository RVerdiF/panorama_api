# Identidade da API no GCP: IAM mínimo e chaves (card `t_b44f8df1`)

A API roda no Cloud Run com uma service account **exclusiva**, sem chave JSON e
com o menor IAM que permite responder consultas. Nada neste documento autoriza
executar em `panorama-escola-staging`: o passo de escrita (`apply`) só roda com
autorização explícita do dono para este card.

## Arquivos versionados (fonte única)

| arquivo | conteúdo |
|---|---|
| `infra/gcp/api-runtime-sa.yaml` | projeto, SA, papéis por escopo, política de chave e sondas de permissão |
| `scripts/gcp_api_runtime_sa.py` | `plan` / `verify` / `apply`: compara o spec com o estado real e aplica só a diferença |
| `tests/unit/test_api_runtime_sa.py` | testes herméticos do spec e das funções puras (22 testes) |

O script não fixa projeto, SA nem dataset: tudo vem do YAML. Não há caminho
pessoal em nenhum dos dois arquivos (testado).

## Por que uma SA nova

`panorama-escola-runtime` **já existe**, mas é a identidade de CI/pipeline e é
gerenciada por Terraform no repo `panorama_escola`
(`infra/envs/staging/main.tf`, módulo `service-accounts-iam`) com
`bigquery.dataEditor` + `jobUser` + `logging` + `monitoring`.

- binding manual nela seria revertido no próximo `terraform apply` (drift);
- ela escreve dados: se a API a usasse, um bug de código da API poderia
  publicar/apagar no dataset de serving;
- o blast radius da API precisa ser disjunto do blast radius do pipeline.

Por isso: `panorama-api-runtime@panorama-escola-staging.iam.gserviceaccount.com`.

## O que a SA pode e o que ela não pode

| escopo | papel | efeito |
|---|---|---|
| projeto | `roles/bigquery.jobUser` | cria jobs de consulta; não lê nem escreve dados por si |
| `panorama_serving` | `READER` (`roles/bigquery.dataViewer`) | lê tabelas/views publicadas |
| — | nenhum outro papel, em nenhum outro dataset | — |

Sem `roles/bigquery.readSessionUser` nesta fase. Autenticação: ADC por
impersonação (o serviço no Cloud Run usa a própria SA; local, o dono usa
`--impersonate-service-account` com `roles/iam.serviceAccountTokenCreator`), sem
chave JSON em nenhum caminho.

Chaves: `iam.disableServiceAccountKeyCreation` está **enforced** no projeto
(verificado em 2026-11-19), e `verify` falha se aparecer qualquer chave
`USER_MANAGED`.

## Uso

```bash
.venv/bin/python scripts/gcp_api_runtime_sa.py plan     # read-only: mostra a diferença
.venv/bin/python scripts/gcp_api_runtime_sa.py verify   # exit 1 se divergir do spec
.venv/bin/python scripts/gcp_api_runtime_sa.py apply --yes
```

`apply` sem `--yes` é recusado antes de qualquer chamada ao GCP (exit 2,
coberto por teste). `apply` é idempotente: cria só o que falta e termina
rodando `verify`.

`verify` faz três coisas: compara papéis/keys/org policy com o spec, roda
`testIamPermissions` **como a SA** (impersonação, sem chave) no projeto e no
dataset, e falha se uma permissão positiva estiver ausente ou uma negativa
estiver concedida.

## Estado verificado (leitura, 2026-11-19)

| item | estado |
|---|---|
| SA `panorama-api-runtime` | não existe ainda |
| papéis no projeto para a SA | nenhum |
| papéis em datasets para a SA | nenhum |
| chaves `USER_MANAGED` | nenhuma |
| `iam.disableServiceAccountKeyCreation` | enforced |
| datasets no projeto | só `panorama_serving` (location `us-central1`) |
| acesso do dataset | `projectOwners`/`projectWriters`/`projectReaders` + `rafaelverdifreitas@hotmail.com` (OWNER) |

Saída de `plan` nesse estado:

```text
SA: panorama-api-runtime@panorama-escola-staging.iam.gserviceaccount.com
existe: não
papéis no projeto: nenhum
papéis em datasets: nenhum
chaves de usuário: 0
org policy: enforced

  aplicar: projeto: falta roles/bigquery.jobUser
  aplicar: dataset panorama_serving: falta READER
```

## Checks negativos

Cada linha é uma operação que **precisa falhar** com a SA. Os `testIamPermissions`
marcados com ✓ já são executados por `verify`; os demais são comandos manuais,
executados na mesma janela do `apply` e copiados (mensagem real, não esperada)
para a seção de evidência.

| # | operação | comando | por que falha | automático |
|---|---|---|---|---|
| 1 | CREATE TABLE no serving | `bq mk --table --impersonate_service_account=<sa> panorama-escola-staging:panorama_serving.probe_t_b44f8df1 "(id INT64)"` | sem `bigquery.tables.create` (só `dataViewer`) | ✓ permissão |
| 2 | CREATE DATASET | `bq mk --dataset --impersonate_service_account=<sa> panorama-escola-staging:probe_t_b44f8df1` | sem `bigquery.datasets.create` | ✓ permissão |
| 3 | ler dataset fora do serving | `bq show --impersonate_service_account=<sa> panorama-escola-staging:panorama_serving` deve **funcionar** (controle positivo); qualquer outro dataset do projeto não existe em 2026-11-19, então a negativa equivalente é `bigquery.datasets.get`/`bigquery.tables.getData` negados fora do serving (probe) | `dataViewer` só no dataset de serving | ✓ permissão |
| 4 | alterar dados | `bq query --impersonate_service_account=<sa> "DELETE FROM ..."` / `INSERT` | sem `bigquery.tables.updateData` | ✓ permissão |
| 5 | criar chave JSON | `gcloud iam service-accounts keys create /tmp/k.json --iam-account=<sa>` | org policy `iam.disableServiceAccountKeyCreation` enforced | ✓ org policy + keys list vazio |
| 6 | ler IAM do projeto | `gcloud projects get-iam-policy panorama-escola-staging --impersonate-service-account=<sa>` | sem `resourcemanager.projects.getIamPolicy` | ✓ permissão |
| 7 | exportar dados (extract) | `bq extract --impersonate_service_account=<sa> panorama-escola-staging:panorama_serving.dim_escola gs://<bucket>/probe.csv` | SA sem escrita em GCS e sem caminho de export previsto | manual |

O check 5 é o único que **cria** algo se a policy estiver desligada. Por isso a
prova automática é "org policy enforced + nenhuma chave `USER_MANAGED`", e o
`keys create` só é executado na janela autorizada, registrando a mensagem de
recusa.

## Rollback

```bash
gcloud iam service-accounts keys list \
  --iam-account=panorama-api-runtime@panorama-escola-staging.iam.gserviceaccount.com \
  --project=panorama-escola-staging            # deve mostrar só SYSTEM_MANAGED
gcloud projects remove-iam-policy-binding panorama-escola-staging \
  --member=serviceAccount:panorama-api-runtime@panorama-escola-staging.iam.gserviceaccount.com \
  --role=roles/bigquery.jobUser --quiet
# dataset: remover a entrada userByEmail do access de panorama_serving
gcloud iam service-accounts delete \
  panorama-api-runtime@panorama-escola-staging.iam.gserviceaccount.com \
  --project=panorama-escola-staging --quiet
```

Nenhum dado é movido ou apagado por este card: o rollback só remove IAM e a SA.

## Evidência

Preenchida na janela autorizada de execução (não antes): saída de
`apply --yes`, de `verify`, de `plan` pós-aplicação e a mensagem real de cada
check negativo da tabela acima.
