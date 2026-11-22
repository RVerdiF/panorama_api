"""IaC de build/publicação da imagem da API (card `t_cab24513`, decisão D1).

Testes herméticos: só leem arquivos do repo. Nenhum acesso a GCP, Docker ou rede.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
CLOUDBUILD = REPO_ROOT / "cloudbuild.yaml"
SERVICE_YAML = REPO_ROOT / "infra" / "cloud-run" / "service.yaml"
CLEANUP_POLICY = REPO_ROOT / "infra" / "artifact-registry" / "cleanup-policy.json"
ENSURE_SH = REPO_ROOT / "infra" / "artifact-registry" / "ensure.sh"
BUILD_SH = REPO_ROOT / "infra" / "cloud-run" / "build.sh"

SA_EMAIL = "panorama-api-runtime@panorama-escola-staging.iam.gserviceaccount.com"


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def cloudbuild() -> dict:
    return yaml.safe_load(CLOUDBUILD.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def service() -> dict:
    return yaml.safe_load(SERVICE_YAML.read_text(encoding="utf-8"))


# -- Dockerfile -------------------------------------------------------------


def test_dockerfile_e_multi_stage_com_base_slim(dockerfile):
    stages = [
        line.split()[1]
        for line in dockerfile.splitlines()
        if line.upper().startswith("FROM ")
    ]

    assert len(stages) >= 2, "esperado multi-stage (builder + runtime)"
    assert all("python" in stage and "slim" in stage for stage in stages)


def test_imagem_roda_como_usuario_nao_root(dockerfile):
    assert "USER root" not in dockerfile
    user_lines = [l.strip() for l in dockerfile.splitlines() if l.strip().upper().startswith("USER ")]

    assert user_lines, "Dockerfile sem diretiva USER: rodaria como root"
    assert all("root" not in line.lower() for line in user_lines)


def test_nao_ha_credencial_embutida(dockerfile):
    """ADC da SA do Cloud Run: nenhuma chave, token ou secret na imagem."""
    lowered = dockerfile.lower()

    for marker in ("google_application_credentials", "credential", "secret", "json_key"):
        assert marker not in lowered


def test_aplicacao_escuta_a_porta_do_ambiente(dockerfile):
    cmd = [l for l in dockerfile.splitlines() if l.strip().upper().startswith("CMD")]

    assert cmd, "Dockerfile sem CMD"
    assert "${PORT}" in cmd[-1]
    assert "uvicorn panorama_api.main:app" in cmd[-1]


def test_dockerignore_exclui_ambiente_dataset_e_historico():
    patterns = {
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }

    for obrigatorio in (".venv", "tests", "data", "evidence", ".git"):
        assert obrigatorio in patterns, f".dockerignore sem '{obrigatorio}'"


# -- cloudbuild.yaml --------------------------------------------------------


def test_cloudbuild_publica_no_artifact_registry_decidido(cloudbuild):
    substitutions = cloudbuild["substitutions"]

    assert substitutions["_AR_HOST"] == "us-central1-docker.pkg.dev"
    assert substitutions["_AR_PROJECT"] == "panorama-escola-staging"
    assert substitutions["_AR_REPOSITORY"] == "panorama-api"
    assert substitutions["_IMAGE"] == "api"


def test_cloudbuild_publica_tag_explicita_e_latest(cloudbuild):
    images = cloudbuild["images"]
    literal = (
        "${_AR_HOST}/${_AR_PROJECT}/${_AR_REPOSITORY}/${_IMAGE}"
    )

    assert f"{literal}:${{_TAG}}" in images
    assert f"{literal}:latest" in images

    # O caminho montado pelas substituições é o repositório decidido (D1).
    subs = cloudbuild["substitutions"]
    prefix = (
        f"{subs['_AR_HOST']}/{subs['_AR_PROJECT']}"
        f"/{subs['_AR_REPOSITORY']}/{subs['_IMAGE']}"
    )
    assert prefix == "us-central1-docker.pkg.dev/panorama-escola-staging/panorama-api/api"


def test_cloudbuild_falha_fechado_sem_tag(cloudbuild):
    """Tag implícita tornaria a imagem não rastreável até o commit."""
    defs = [step for step in cloudbuild["steps"] if step["id"] == "valida-tag"]

    assert defs, "falta o passo que recusa _TAG vazia"
    script = "\n".join(defs[0]["args"])
    assert "[ -z" in script and "exit 1" in script
    assert cloudbuild["substitutions"]["_TAG"] == ""


def test_cloudbuild_builda_a_partir_da_raiz(cloudbuild):
    build = [step for step in cloudbuild["steps"] if step["id"] == "build"]

    assert build
    assert "." in build[0]["args"], "contexto de build deve ser a raiz do repo"


# -- Artifact Registry: política de limpeza ---------------------------------


def test_politica_de_limpeza_mantem_so_tres_tags():
    policy = json.loads(CLEANUP_POLICY.read_text(encoding="utf-8"))

    (rule,) = policy
    assert rule["action"] == "KEEP"
    assert rule["mostRecentVersions"]["keepCount"] == 3


def test_ensure_do_artifact_registry_exige_confirmacao():
    script = ENSURE_SH.read_text(encoding="utf-8")

    assert "--yes" in script
    assert "dry-run" in script
    assert 'REPOSITORY="panorama-api"' in script
    assert 'LOCATION="us-central1"' in script
    # Ação em GCP nunca roda sem o --yes explícito.
    assert "CONFIRMED" in script


# -- build.sh ---------------------------------------------------------------


def test_build_sh_usa_o_cloudbuild_do_repo():
    script = BUILD_SH.read_text(encoding="utf-8")

    assert "gcloud builds submit" in script
    assert "cloudbuild.yaml" in script
    assert "--substitutions=" in script


# -- manifesto do Cloud Run: identidade ------------------------------


def test_servico_usa_a_sa_da_api(service):
    spec = service["spec"]["template"]["spec"]

    assert spec["serviceAccountName"] == SA_EMAIL
    # Sem a SA a API herdaria a compute default, com privilégio demais.
    assert "1033890592060-compute" not in SERVICE_YAML.read_text(encoding="utf-8")
