# Deploy da API: imagem, Artifact Registry e Cloud Run

Card `t_cab24513` (origem: decisões D1/D2 do `t_ec4d1b26`).

Este documento é o runbook do caminho **código → imagem → serviço**. Nenhum
passo daqui roda sozinho: os comandos que tocam GCP são manuais e exigem
autorização do dono.

| etapa | arquivo | onde executa |
|---|---|---|
| imagem | `Dockerfile`, `.dockerignore` | local (`docker build`) ou Cloud Build |
| build/publicação | `cloudbuild.yaml`, `infra/cloud-run/build.sh` | Cloud Build (manual) |
| repositório de imagens | `infra/artifact-registry/ensure.sh`, `cleanup-policy.json` | `gcloud` (manual) |
| serviço | `infra/cloud-run/service.yaml`, `deploy.sh` | `gcloud run services replace` |

## Imagem

Multi-stage (`builder` → `runtime`), base `python:3.11-slim`, usuário
`app` (UID 10001), sem shell de login. O estágio final copia apenas o venv, sem
`pip`, wheel ou cache.

- **Nenhuma credencial na imagem.** O BigQuery é acessado por ADC; no Cloud Run
  o ADC resolve para a SA `panorama-api-runtime` (sem chave JSON, ver
  [`gcp-api-runtime-sa.md`](gcp-api-runtime-sa.md)).
- A aplicação escuta em `$PORT` (`sh -c 'exec uvicorn … --port ${PORT}'`), com
  `PORT=8080` como default local.
- `.dockerignore` exclui `.venv`, `tests`, `data`, `evidence` e `.git`: o
  contexto de build é só `pyproject.toml`, `README.md` e `src/`.

```bash
docker build -t panorama-api:local .
docker run --rm -p 8080:8080 -e API_VALIDATE_SCHEMA_ON_STARTUP=false panorama-api:local
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/health   # 200
```

`API_VALIDATE_SCHEMA_ON_STARTUP=false` só serve para provar o container sem
credencial; em produção o valor default (`true`) falha fechado se o schema do
serving divergir do contrato.

## Artifact Registry

| item | valor |
|---|---|
| repositório | `panorama-api` (DOCKER) |
| região | `us-central1` |
| imagem | `us-central1-docker.pkg.dev/panorama-escola-staging/panorama-api/api` |
| tag | SHA curto do commit (`git rev-parse --short=7 HEAD`) + `latest` |
| política de limpeza | manter as **3** tags mais recentes (`KEEP`, `keepCount: 3`) |

```bash
bash infra/artifact-registry/ensure.sh        # dry-run: mostra o estado
bash infra/artifact-registry/ensure.sh --yes  # cria o repo e aplica a política
```

A política vem de `infra/artifact-registry/cleanup-policy.json` — fonte única do
número 3. O limite de 0,5 GB de storage da franquia é o motivo do teto.

## Build (Cloud Build, disparo manual)

`cloudbuild.yaml` é um pipeline **próprio**, separado do pipeline de dados do
repo `panorama_escola`. Sem trigger automático nesta fase; máquina default
(franquia de 120 min/dia).

```bash
bash infra/cloud-run/build.sh              # tag = SHA curto do HEAD
TAG=manual-1 bash infra/cloud-run/build.sh # tag explícita
```

Equivalente direto:

```bash
gcloud builds submit . \
  --config cloudbuild.yaml \
  --project panorama-escola-staging \
  --substitutions="_TAG=$(git rev-parse --short=7 HEAD)"
```

O primeiro passo (`valida-tag`) **falha fechado** com `_TAG` vazia: build sem
tag explícita produziria uma imagem não rastreável até o commit.

### Pré-requisito de IAM (verificado em 2026-11-22)

`gcloud builds submit` falha antes de compilar se a service account do build não
puder ler o bucket de staging do Cloud Build
(`gs://<projeto>_cloudbuild`). Estado encontrado no projeto de staging:

| item | estado |
|---|---|
| `gcloud builds get-default-service-account` | `1033890592060-compute@developer.gserviceaccount.com` |
| papel `roles/cloudbuild.builds.builder` no projeto | só em `1033890592060@cloudbuild.gserviceaccount.com` |
| SA `panorama-escola-build` (declarada no Terraform do repo `panorama_escola`) | **não existe** no projeto |
| resultado | `403 storage.objects.get` em `..._cloudbuild/source/*.tgz` |

Correção (ação de IAM — exige autorização do dono, não é feita por este
runbook): conceder `roles/cloudbuild.builds.builder` à SA que executa o build
**ou** criar a SA dedicada `panorama-escola-build` prevista no Terraform com esse
papel. Até lá o caminho alternativo é publicar a imagem de uma máquina
autenticada (`docker push <imagem>:<tag>`), que também exige autorização.

Evidência de publicação:

```bash
gcloud artifacts docker images list \
  us-central1-docker.pkg.dev/panorama-escola-staging/panorama-api/api \
  --include-tags --format="table(version,tags,create_time)"
```

## Serviço Cloud Run

Parâmetros em `infra/cloud-run/service.yaml` (fonte única, guardado por
`tests/unit/test_infra_config.py` e `tests/unit/test_deploy_iac.py`):

| parâmetro | valor | regra |
|---|---|---|
| região | `us-central1` | mesma do dataset e do AR |
| `minScale` | `0` | scale-to-zero obrigatório (franquia) |
| `maxScale` | `3` | teto de instâncias |
| `containerConcurrency` | `20` | — |
| `timeoutSeconds` | `15` | — |
| CPU / memória | `1` / `512Mi` | CPU só durante a requisição |
| service account | `panorama-api-runtime@…` | IAM mínimo, sem chave |
| porta | `8080` (via `$PORT`) | — |

`env` do manifesto: `BQ_PROJECT`, `BQ_DATASET`, `BQ_LOCATION`,
`API_BQ_MAX_BYTES_BILLED` (256 MB, decisão D2), `DATA_VERSION`.

**Autenticação:** o serviço sobe **sem** acesso público. Não há binding
`allUsers`/`roles/run.invoker` para `allUsers` e o deploy não usa
`--allow-unauthenticated`. Abrir ao público é decisão do dono, não default.

```bash
IMAGE=us-central1-docker.pkg.dev/panorama-escola-staging/panorama-api/api:<sha> \
DATA_VERSION=<run de publicação> \
bash infra/cloud-run/deploy.sh
```

`deploy.sh` valida o manifesto antes de aplicar: placeholder não substituído,
`minScale != 0` e `maxScale > 3` abortam o deploy.

Chamada ao endpoint com autenticação exigida:

```bash
TOKEN=$(gcloud auth print-identity-token)
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $TOKEN" "$SERVICE_URL/health"   # 200
```
