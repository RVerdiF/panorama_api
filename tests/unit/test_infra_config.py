"""IaC de custo/limites: Cloud Run e controles de cota/budget (card `t_817a670c`)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from panorama_api.config import Settings
from panorama_api.config import DEFAULT_MAX_BYTES_BILLED as SETTINGS_MAX_BYTES
from panorama_api.repositories.bigquery.config import (
    DEFAULT_MAX_BYTES_BILLED as BIGQUERY_MAX_BYTES,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_YAML = REPO_ROOT / "infra" / "cloud-run" / "service.yaml"
DEPLOY_SH = REPO_ROOT / "infra" / "cloud-run" / "deploy.sh"
COST_YAML = REPO_ROOT / "infra" / "gcp" / "cost-controls.yaml"


@pytest.fixture(scope="module")
def service() -> dict:
    return yaml.safe_load(SERVICE_YAML.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def annotations(service: dict) -> dict:
    return service["spec"]["template"]["metadata"]["annotations"]


@pytest.fixture(scope="module")
def template_spec(service: dict) -> dict:
    return service["spec"]["template"]["spec"]


@pytest.fixture(scope="module")
def costs() -> dict:
    return yaml.safe_load(COST_YAML.read_text(encoding="utf-8"))


# -- manifesto do Cloud Run ------------------------------------------------


def test_manifesto_e_um_servico_cloud_run_valido(service):
    assert service["apiVersion"] == "serving.knative.dev/v1"
    assert service["kind"] == "Service"
    assert service["metadata"]["name"] == "panorama-api"


def test_min_instances_e_zero(annotations):
    # Regra do dono: scale-to-zero, nunca manter instância quente.
    assert annotations["autoscaling.knative.dev/minScale"] == "0"


def test_max_instances_nao_passa_de_tres(annotations):
    max_scale = int(annotations["autoscaling.knative.dev/maxScale"])

    assert 1 <= max_scale <= 3
    assert max_scale == 3


def test_concurrency_e_timeout_do_manifesto(template_spec):
    assert template_spec["containerConcurrency"] == 20
    assert template_spec["timeoutSeconds"] == 15


def test_cpu_desligada_fora_da_requisicao(annotations):
    assert annotations["run.googleapis.com/cpu-throttling"] == "true"


def test_containers_usam_uma_vcpu_e_512_mib(template_spec):
    (container,) = template_spec["containers"]
    assert container["resources"]["limits"] == {"cpu": "1", "memory": "512Mi"}
    assert container["ports"] == [{"name": "http1", "containerPort": 8080}]


def test_imagem_vem_do_artifact_registry_de_us_central1(template_spec):
    (container,) = template_spec["containers"]
    assert container["image"].startswith("${IMAGE}") or "us-central1-docker.pkg.dev" in (
        container["image"]
    )


def _manifest_env(template_spec) -> dict[str, str]:
    (container,) = template_spec["containers"]
    return {item["name"]: item["value"] for item in container["env"]}


def test_env_do_manifesto_usa_os_aliases_do_settings(template_spec):
    env = _manifest_env(template_spec)
    aliases = {field.alias for field in Settings.model_fields.values() if field.alias}

    # Um `env` que não é alias do `Settings` é descartado por `extra="ignore"`,
    # calado: o valor do manifesto deixaria de valer (revisão 1 do card).
    assert set(env) <= aliases


def test_settings_carrega_os_valores_do_manifesto(template_spec, monkeypatch):
    env = _manifest_env(template_spec)
    padroes = {"${DATA_VERSION}": "2026.11.17", "${APP_BUILD}": "31b900f"}
    for name, value in env.items():
        monkeypatch.setenv(name, padroes.get(value, value))

    settings = Settings()

    assert settings.bq_project == "panorama-escola-staging"
    assert settings.bq_dataset == "panorama_serving"
    assert settings.bq_location == "us-central1"
    assert settings.max_bytes_billed == 268435456
    # DATA_VERSION do deploy é o que invalida ETag/LRU a cada publicação.
    assert settings.data_version == "2026.11.17"
    # APP_BUILD é o que invalida ETag/LRU a cada deploy de código (card F8).
    assert settings.app_build == "31b900f"


# -- seletor de ano do front (card F5) --------------------------------------


def test_manifesto_declara_app_anos_disponiveis(template_spec):
    """O seletor de ano do front depende desta env no mesmo manifesto."""
    env = _manifest_env(template_spec)

    assert "APP_ANOS_DISPONIVEIS" in env
    anos = [int(item) for item in env["APP_ANOS_DISPONIVEIS"].split(",")]
    assert anos == sorted(anos)
    assert len(set(anos)) == len(anos)


def test_manifesto_sem_app_anos_disponiveis_falha_no_boot(template_spec, monkeypatch):
    """Falha fechada: ausente → `Settings` não constrói (o app não sobe)."""
    env = _manifest_env(template_spec)
    monkeypatch.delenv("APP_ANOS_DISPONIVEIS", raising=False)
    for nome, valor in env.items():
        if nome != "APP_ANOS_DISPONIVEIS":
            monkeypatch.setenv(nome, "2026.11.17" if valor == "${DATA_VERSION}" else valor)

    with pytest.raises(ValidationError) as excinfo:
        Settings()

    assert "APP_ANOS_DISPONIVEIS" in str(excinfo.value)


@pytest.mark.parametrize(
    "valor",
    [
        "",
        " ",
        "2021,,2022",
        "abc",
        "2021, 20x2",
        "1999",
        "2101",
        "2021,2021",
        "2021;2022",
        "0000",
    ],
)
def test_settings_recusa_anos_disponiveis_invalidos(valor):
    """Mesma política de `DATA_VERSION`: valor inválido não vira default."""
    with pytest.raises(ValidationError):
        Settings(app_anos_disponiveis=valor)


def test_settings_guarda_anos_disponiveis_canonicamente():
    settings = Settings(app_anos_disponiveis="2025, 2021 ,2023")

    assert settings.anos_disponiveis == (2021, 2023, 2025)
    assert settings.app_anos_disponiveis == "2021,2023,2025"


# -- script de deploy ------------------------------------------------------


def test_deploy_fixa_a_regiao_us_central1():
    script = DEPLOY_SH.read_text(encoding="utf-8")

    assert 'REGION="us-central1"' in script
    assert '--region "$REGION"' in script


def test_deploy_falha_fechado_se_min_scale_nao_for_zero():
    script = DEPLOY_SH.read_text(encoding="utf-8")

    assert 'autoscaling.knative.dev/minScale: "0"' in script
    assert "minScale != 0" in script


def test_deploy_falha_fechado_se_max_scale_passar_de_tres():
    script = DEPLOY_SH.read_text(encoding="utf-8")

    assert "maxScale" in script
    assert "-gt 3" in script


def test_deploy_nao_deixa_placeholder_sem_substituir():
    script = DEPLOY_SH.read_text(encoding="utf-8")

    assert "grep -q '\\${' \"$MANIFEST\"" in script


# -- APP_BUILD no manifesto e no deploy (card F8) ---------------------------


def test_manifesto_declara_app_build(template_spec):
    """Sem `APP_BUILD` o deploy roda com o default `dev` e não invalida cache.

    Critério do card F8: a variável existe no manifesto e é substituída pelo
    deploy, como `DATA_VERSION`.
    """
    env = _manifest_env(template_spec)

    assert env.get("APP_BUILD") == "${APP_BUILD}"


def test_settings_carrega_app_build_do_manifesto(template_spec, monkeypatch):
    env = _manifest_env(template_spec)
    padroes = {"${DATA_VERSION}": "2026.11.17", "${APP_BUILD}": "31b900f"}
    for name, value in env.items():
        monkeypatch.setenv(name, padroes.get(value, value))

    settings = Settings()

    assert settings.app_build == "31b900f"


def test_deploy_substitui_app_build_no_manifesto():
    script = DEPLOY_SH.read_text(encoding="utf-8")

    assert "s|\\${APP_BUILD}|${APP_BUILD}|g" in script


def _rodar_deploy(
    tmp_path: Path, manifesto: str, dry_run: bool = True, com_app_build: bool = True
) -> tuple[subprocess.CompletedProcess, Path, Path]:
    """Roda `deploy.sh` sobre um manifesto temporário.

    Copia o script para `tmp_path` (o checkout não muda) e põe um `gcloud`
    falso no PATH: ele marca o arquivo `marcador` e copia o manifesto recebido
    (4º argumento) para `capturado`.
    """
    destino = tmp_path / "cloud-run"
    destino.mkdir()
    (destino / "deploy.sh").write_text(DEPLOY_SH.read_text(encoding="utf-8"), encoding="utf-8")
    (destino / "service.yaml").write_text(manifesto, encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marcador = tmp_path / "gcloud-invocado"
    capturado = tmp_path / "manifesto-enviado.yaml"
    falso = bin_dir / "gcloud"
    falso.write_text(
        "#!/bin/sh\n"
        f'touch "{marcador}"\n'
        f'if [ -n "$4" ] && [ -f "$4" ]; then cp "$4" "{capturado}"; fi\n'
        "exit 99\n",
        encoding="utf-8",
    )
    falso.chmod(0o755)

    env = {
        "PATH": os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"]),
        "IMAGE": "us-central1-docker.pkg.dev/p/ar/api@sha256:" + "0" * 64,
        "DATA_VERSION": "2026.11.18",
        "DRY_RUN": "1" if dry_run else "0",
    }
    if com_app_build:
        env["APP_BUILD"] = "31b900f"

    resultado = subprocess.run(
        ["bash", str(destino / "deploy.sh")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
    )
    return resultado, marcador, capturado


def test_deploy_em_dry_run_passa_com_manifesto_completo(tmp_path):
    resultado, marcador, _ = _rodar_deploy(tmp_path, SERVICE_YAML.read_text(encoding="utf-8"))

    assert resultado.returncode == 0, resultado.stderr
    assert "dry-run" in resultado.stdout
    # Critério de aceite: guarda exercitada sem invocar o CLI do GCP.
    assert not marcador.exists(), "deploy.sh chamou gcloud com DRY_RUN=1"


def test_deploy_falha_fechado_sem_app_build(tmp_path):
    """Sem `APP_BUILD` o app subiria com `dev`: o deploy recusa, como com DATA_VERSION."""
    resultado, marcador, _ = _rodar_deploy(
        tmp_path, SERVICE_YAML.read_text(encoding="utf-8"), com_app_build=False
    )

    assert resultado.returncode != 0
    assert "APP_BUILD" in resultado.stderr
    assert not marcador.exists(), "deploy.sh chamou gcloud sem APP_BUILD"


def test_deploy_entrega_app_build_no_manifesto(tmp_path):
    """Plumbing fim a fim: o gcloud recebe o manifesto já com `APP_BUILD`."""
    resultado, marcador, capturado = _rodar_deploy(
        tmp_path, SERVICE_YAML.read_text(encoding="utf-8"), dry_run=False
    )

    assert marcador.exists()
    # O `gcloud` falso sai com 99: prova de que o script chegou ao replace.
    assert resultado.returncode == 99
    enviado = capturado.read_text(encoding="utf-8")
    assert "${" not in enviado
    assert 'name: APP_BUILD\n              value: "31b900f"' in enviado


# -- staging sem IAP: privado por IAM (card F8, D2 revisada) ---------------


def test_manifesto_nao_declara_iap_no_staging(service):
    """D2 revisada pelo dono (2026-11-23): login só na fase de publicação.

    Com `iap.googleapis.com` desabilitada, a anotação de IAP deixaria o serviço
    inacessível. O gate do staging é a policy de IAM do serviço.
    """
    assert "run.googleapis.com/iap-enabled" not in service["metadata"].get("annotations", {})
    template = service["spec"]["template"]["metadata"].get("annotations", {})
    assert "run.googleapis.com/iap-enabled" not in template


def test_deploy_nao_tem_guarda_de_iap():
    script = DEPLOY_SH.read_text(encoding="utf-8")

    assert "iap-enabled" not in script


# -- cota, budget e alertas ------------------------------------------------


def test_cost_controls_espelham_o_manifesto(costs, annotations, template_spec):
    cloud_run = costs["cloud_run"]

    assert cloud_run["region"] == "us-central1"
    assert cloud_run["min_instances"] == int(
        annotations["autoscaling.knative.dev/minScale"]
    )
    assert cloud_run["max_instances"] == int(
        annotations["autoscaling.knative.dev/maxScale"]
    )
    assert cloud_run["concurrency"] == template_spec["containerConcurrency"]
    assert cloud_run["request_timeout_s"] == template_spec["timeoutSeconds"]


def test_cota_diaria_do_bigquery_e_50_gb(costs):
    bigquery = costs["bigquery"]

    assert bigquery["daily_query_limit_gb"] == 50
    assert bigquery["maximum_bytes_billed_per_query"] == 268435456


def test_teto_de_bytes_declarado_e_canonico_e_unico(costs, template_spec):
    """O teto por consulta é único: 256 MB nas três fontes de verdade.

    Decisão D2 do `t_ec4d1b26`: 100 MB do plano 2d está superado pelo pior caso
    medido, e 10 MB é o mínimo faturado por tabela, não um teto. Um valor
    divergente em qualquer fonte reabre a ambiguidade que o card eliminou.
    """
    manifestado = int(_manifest_env(template_spec)["API_BQ_MAX_BYTES_BILLED"])

    assert SETTINGS_MAX_BYTES == 268_435_456
    assert BIGQUERY_MAX_BYTES == 268_435_456
    assert manifestado == 268_435_456
    assert costs["bigquery"]["maximum_bytes_billed_per_query"] == 268_435_456


def test_budget_de_vinte_dolares_com_alertas_50_90_100(costs):
    budget = costs["budget"]

    assert budget["amount_usd"] == 20
    assert budget["period"] == "monthly"
    assert budget["alerts_percent"] == [50, 90, 100]


def test_alertas_descrevem_as_cinco_condicoes_do_card(costs):
    alertas = {item["name"]: item for item in costs["alerts"]}

    assert set(alertas) == {
        "bigquery_bytes_acima_10gb_dia",
        "bigquery_bytes_billed_limit_exceeded",
        "latencia_p95_acima_2s",
        "erros_5xx_acima_1pct",
        "instancias_no_teto_por_10min",
        "http_503_acima_de_5_em_15min",
    }
    assert "10 GB" in alertas["bigquery_bytes_acima_10gb_dia"]["condition"]
    assert "bytesBilledLimitExceeded" in alertas["bigquery_bytes_billed_limit_exceeded"]["condition"]
    assert "p95" in alertas["latencia_p95_acima_2s"]["condition"]
    assert "5xx" in alertas["erros_5xx_acima_1pct"]["condition"]
    assert "max_instances" in alertas["instancias_no_teto_por_10min"]["condition"]


def test_alerta_de_503_do_front_e_de_15_min_com_limite_5(costs):
    """Card F6 (plano §7.2): 503 em `/app` **ou** `/v1` ≥ 5 em 15 min."""
    alerta = {item["name"]: item for item in costs["alerts"]}["http_503_acima_de_5_em_15min"]

    assert "/app" in alerta["condition"] and "/v1" in alerta["condition"]
    assert "503" in alerta["condition"]
    assert alerta["threshold"] == ">= 5 ocorrências"
    assert alerta["window"] == "15 min"
    assert alerta["source"] == "log"


def test_metricas_de_log_declaradas_tem_filtro_e_alertas_existentes(costs):
    """Fonte única: alerta de log aponta para métrica, métrica para alerta."""
    alertas = {item["name"] for item in costs["alerts"]}
    metricas = {item["name"]: item for item in costs["log_metrics"]}

    assert set(metricas) == {"page_view_por_rota", "http_503_por_rota"}
    for metrica in metricas.values():
        assert metrica["filter"].startswith("jsonPayload.message=")
        assert metrica["fields"]

    assert metricas["http_503_por_rota"]["alerts"] == ["http_503_acima_de_5_em_15min"]
    for nome in metricas["http_503_por_rota"]["alerts"]:
        assert nome in alertas
    # A base do `page_view` é a linha de mesmo nome emitida pelo front, com os
    # sete campos do plano §7.1.
    campo = metricas["page_view_por_rota"]
    assert campo["filter"] == 'jsonPayload.message="page_view"'
    assert set(campo["fields"]) == {
        "route",
        "status",
        "cache",
        "ms",
        "data_version",
        "app_build",
        "user_hash",
    }
    assert campo["group_by"] == ["route", "data_version", "app_build"]


def test_alertas_sao_aviso_e_nao_corte(costs):
    # Nenhum alerta declara ação destrutiva: o corte é a cota do BigQuery.
    for alerta in costs["alerts"]:
        assert "corta" not in alerta["condition"]
        assert "desliga" not in alerta["condition"]
