# IAP no Cloud Run: declaração, guarda e setup

> **Status (2026-11-23, card F8):** este runbook está **suspenso no staging**. O
> dono revisou a decisão D2 — não há login por enquanto — e o staging é privado
> por **IAM** (`roles/run.invoker` por pessoa, sem `allUsers`). O manifesto
> `infra/cloud-run/service.yaml` **não** declara `run.googleapis.com/iap-enabled`
> e `deploy.sh` não tem guarda de IAP. Este documento volta a valer na fase de
> publicação, com público externo.

Card `t_3c7efbc0` (F7 do plano `/home/rafael/hermes/docs/panorama-frontend/plano.md`, decisão D2).

O front é servido pelo **mesmo** serviço `panorama-api` (card F1, D1=A). O IAP é
habilitado **direto no Cloud Run**, sem load balancer. Motivo (D2): os dados são
públicos (INEP), então o IAP não é sigilo — ele controla **piloto** e **custo**
(cota diária do BigQuery e instâncias).

Este card **declara** IAP no manifesto e **guarda** o deploy. **Aplicar** de
verdade (OAuth client, allowlist, remoção de `allUsers`) é o card **F8**,
gated: exige autorização explícita do dono.

## 1. O que está declarado, e onde

| item | arquivo | o que faz |
|---|---|---|
| anotação de IAP | `infra/cloud-run/service.yaml` → `metadata.annotations` | declara `run.googleapis.com/iap-enabled: "true"` no nível do **serviço** |
| guarda de deploy | `infra/cloud-run/deploy.sh` | aborta o `replace` se a anotação sumir, estiver no template ou valer `"false"` |
| teste | `tests/unit/test_infra_config.py` | falha se a anotação sair do manifesto; roda a guarda em dry-run |

A anotação é a **mesma** que `gcloud run deploy --iap` grava: `IAP_ANNOTATION =
'run.googleapis.com/iap-enabled'` com valor `'true'`
(`googlecloudsdk/api_lib/run/service.py`; `SetAnnotationChange` em
`command_lib/run/flags.py::_GetIapChanges`). O valor é **string** — anotação é
mapa de strings.

**O nível importa.** Em `spec.template.metadata.annotations` (onde ficam
`minScale`/`maxScale`/`cpu-throttling`) a anotação é **ignorada**: o serviço
subiria aberto e nada falharia. Por isso a guarda distingue os dois casos e há
teste para o caso do template.

Habilitar via manifesto **não** dispensa o binding de IAM do service agent do
IAP no serviço — `deploy.sh` não mexe em IAM (política do card: nenhum recurso
GCP alterado aqui). Ver §4.

## 2. Verificar sem tocar no GCP

Guarda do deploy, só as validações (não invoca `gcloud`):

```bash
IMAGE=us-central1-docker.pkg.dev/panorama-escola-staging/panorama-api/api@sha256:$(printf '0%.0s' {1..64}) \
DATA_VERSION=dry-run \
DRY_RUN=1 \
bash infra/cloud-run/deploy.sh
# dry-run: guardas OK, gcloud não invocado
```

Provocar a falha (remover a anotação numa cópia):

```bash
TMP=$(mktemp -d)
cp -r infra/cloud-run "$TMP/"
sed -i '/run.googleapis.com\/iap-enabled/d' "$TMP/cloud-run/service.yaml"
IMAGE=dry DATA_VERSION=dry DRY_RUN=1 bash "$TMP/cloud-run/deploy.sh"; echo "exit=$?"
# IAP ausente no manifesto (...)  → exit=1
```

Teste automatizado correspondente:

```bash
.venv/bin/python -m pytest tests/unit/test_infra_config.py -q -k "iap or iap_declarado or deploy_em_dry"
```

## 3. Runbook: habilitar IAP de verdade (F8, com autorização)

Projeto `panorama-escola-staging` **não tem organização**. Isso muda o setup:
o OAuth client gerido pelo Google só libera identidades da mesma organização,
então é preciso um client **próprio com público "External"**.

### 3.1 Pré-requisitos de IAM (uma vez por projeto)

Papéis necessários para quem executa (`roles/run.admin`, `roles/iap.admin`,
`roles/iap.settingsAdmin`, `roles/oauthconfig.editor`,
`roles/artifactregistry.reader`, `roles/iam.serviceAccountUser`).

Habilitar a API do IAP:

```bash
gcloud services enable iap.googleapis.com --project panorama-escola-staging
```

### 3.2 OAuth client com público "External"

O console é obrigatório aqui: **não é possível criar OAuth client por CLI**.
Pela doc oficial, numa tentativa por `gcloud` em projeto sem organização sai o
aviso:

```text
Deploying services with IAP enabled in a project without an organization
    may require initial setup via the Cloud Console. Please use the Cloud Run
    UI to enable IAP for the first time in the project.
```

Caminho (Console):

1. Cloud Run → serviço `panorama-api` → **Security** → **IAP** → **Edit policy**
   → **Configure in IAP**.
2. **Configure consent screen** → **User type: External**.
   (Se já existir brand, o erro a corrigir é *"Brand is currently set to
   internal"* — Google Auth Platform → **Audience** → **Make external**.)
3. **Auto generate credentials** (ou **Custom OAuth**, informando client ID e
   secret próprios).
4. **Save**.

Alternativa por CLI **depois** de existir o client (mesmo efeito, projeto sem
organização):

```bash
cat > iap_settings.yaml <<'YAML'
access_settings:
  oauth_settings:
    client_id: CLIENT_ID
    client_secret: CLIENT_SECRET
YAML
gcloud iap settings set iap_settings.yaml --project panorama-escola-staging
rm -f iap_settings.yaml   # é segredo: não versionar, não deixar no checkout
```

### 3.3 Habilitar IAP no serviço

O manifesto já declara a anotação; o `replace` aplica:

```bash
IMAGE=us-central1-docker.pkg.dev/panorama-escola-staging/panorama-api/api@sha256:<digest> \
DATA_VERSION=<run de publicação> \
bash infra/cloud-run/deploy.sh
```

Sem deploy de imagem nova, o equivalente para um serviço existente é:

```bash
gcloud run services update panorama-api --region us-central1 --iap
```

### 3.4 Bindings de IAM

O service agent do IAP precisa poder invocar o serviço:

```bash
PROJECT_NUMBER=$(gcloud projects describe panorama-escola-staging --format='value(projectNumber)')

gcloud run services add-iam-policy-binding panorama-api \
  --region us-central1 \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com" \
  --role=roles/run.invoker
```

**Remover `allUsers`** (a policy de invoker não pode ficar pública — o IAP é o
gate):

```bash
gcloud run services remove-iam-policy-binding panorama-api \
  --region us-central1 \
  --member=allUsers \
  --role=roles/run.invoker
```

Conferir que não sobrou nada público:

```bash
gcloud run services get-iam-policy panorama-api --region us-central1 \
  --format='table(bindings.role,bindings.members)'
# só deve aparecer service-<PROJECT_NUMBER>@gcp-sa-iap.iam.gserviceaccount.com
```

### 3.5 Allowlist de pilotos (por e-mail ou grupo)

```bash
# conceder
gcloud iap web add-iam-policy-binding \
  --member=user:piloto@exemplo.com \
  --role=roles/iap.httpsResourceAccessor \
  --region=us-central1 --resource-type=cloud-run --service=panorama-api

# grupo
gcloud iap web add-iam-policy-binding \
  --member=group:pilotos@exemplo.com \
  --role=roles/iap.httpsResourceAccessor \
  --region=us-central1 --resource-type=cloud-run --service=panorama-api

# remover
gcloud iap web remove-iam-policy-binding \
  --member=user:piloto@exemplo.com \
  --role=roles/iap.httpsResourceAccessor \
  --region=us-central1 --resource-type=cloud-run --service=panorama-api

# auditar a allowlist atual
gcloud iap web get-iam-policy \
  --region=us-central1 --resource-type=cloud-run --service=panorama-api
```

Para conceder uma lista **autoritativa** (remove quem não está na lista),
`google_iap_web_cloud_run_service_iam_binding` no Terraform — fora do escopo
deste repo (aqui o IaC é YAML + script).

## 4. Verificar no GCP (F8)

```bash
gcloud run services describe panorama-api --region us-central1 \
  --project panorama-escola-staging --format='value(metadata.annotations)'
# deve conter: run.googleapis.com/iap-enabled=true

gcloud run services describe panorama-api --region us-central1 \
  --project panorama-escola-staging | grep -i "Iap Enabled"
# Iap Enabled: true

curl -s -o /dev/null -w '%{http_code}\n' \
  https://panorama-api-juskqqhdya-uc.a.run.app/app/metodologia
# anônimo → 302 (redirect de login do IAP), nunca 200
```

Smoke com sessão de piloto (checklist das 4 telas) e o log `page_view` com
`user_hash` pertencem ao card F6/F8, não a este.

## 5. Limitações conhecidas

- **IAP cobre todas as rotas**, inclusive `/health` e `/v1`. Consumidor
  programático de `/v1` precisa de token IAP; fora do MVP (plano §4).
- Não se configura IAP **ao mesmo tempo** no load balancer e no serviço.
- Cloud Run aplica a policy do IAP **antes** do IAM check do service agent;
  serviços que dependem da identidade original do chamador (ex.: Pub/Sub) podem
  falhar.
- Em projeto sem organização, o primeiro IAP pode falhar com *"Setting IAM
  permissions failed"* (service agent do Cloud Run ainda não provisionado) —
  repetir a habilitação ou aplicar a policy manualmente resolve.
- E-mail de piloto nunca vai em log em claro: só `user_hash`
  (`sha256(salt + email)[:16]`, card F6).
