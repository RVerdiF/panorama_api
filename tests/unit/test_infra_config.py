"""IaC de custo/limites: Cloud Run e controles de cota/budget (card `t_817a670c`)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

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
    for name, value in env.items():
        monkeypatch.setenv(name, "2026.11.17" if value == "${DATA_VERSION}" else value)

    settings = Settings()

    assert settings.bq_project == "panorama-escola-staging"
    assert settings.bq_dataset == "panorama_serving"
    assert settings.bq_location == "us-central1"
    assert settings.max_bytes_billed == 268435456
    # DATA_VERSION do deploy é o que invalida ETag/LRU.
    assert settings.data_version == "2026.11.17"


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


# -- IAP declarado no manifesto (card `t_3c7efbc0`) -------------------------

IAP_ANOTACAO = "run.googleapis.com/iap-enabled"


def test_iap_esta_declarado_no_nivel_do_servico(service):
    """IAP é anotação do Service, não do template: no template ela é ignorada.

    É a mesma anotação que `gcloud run deploy --iap` grava (`IAP_ANNOTATION`
    = `'run.googleapis.com/iap-enabled'`, valor `'true'`) em
    `googlecloudsdk/api_lib/run/service.py`.
    """
    anotacoes_do_servico = service["metadata"]["annotations"]
    anotacoes_do_template = service["spec"]["template"]["metadata"].get("annotations", {})

    assert anotacoes_do_servico.get(IAP_ANOTACAO) == "true"
    # Anotação é mapa de strings: `true` booleano é outro tipo de erro.
    assert isinstance(anotacoes_do_servico[IAP_ANOTACAO], str)
    # Declarar IAP no template não habilita nada — o erro silencioso a evitar.
    assert IAP_ANOTACAO not in anotacoes_do_template


def _rodar_deploy(tmp_path: Path, manifesto: str) -> tuple[subprocess.CompletedProcess, Path]:
    """Roda `deploy.sh` em dry-run sobre um manifesto temporário.

    Copia o script para `tmp_path` (o checkout não muda) e põe um `gcloud`
    falso no PATH: se o script invocar o CLI, aparece o arquivo marcador.
    """
    destino = tmp_path / "cloud-run"
    destino.mkdir()
    (destino / "deploy.sh").write_text(DEPLOY_SH.read_text(encoding="utf-8"), encoding="utf-8")
    (destino / "service.yaml").write_text(manifesto, encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marcador = tmp_path / "gcloud-invocado"
    falso = bin_dir / "gcloud"
    falso.write_text(f'#!/bin/sh\ntouch "{marcador}"\nexit 99\n', encoding="utf-8")
    falso.chmod(0o755)

    resultado = subprocess.run(
        ["bash", str(destino / "deploy.sh")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={
            "PATH": os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"]),
            "IMAGE": "us-central1-docker.pkg.dev/p/ar/api@sha256:" + "0" * 64,
            "DATA_VERSION": "2026.11.18",
            "DRY_RUN": "1",
        },
    )
    return resultado, marcador


def test_deploy_em_dry_run_passa_com_iap_declarado(tmp_path):
    resultado, marcador = _rodar_deploy(
        tmp_path, SERVICE_YAML.read_text(encoding="utf-8")
    )

    assert resultado.returncode == 0, resultado.stderr
    assert "dry-run" in resultado.stdout
    # Critério de aceite: guarda exercitada sem invocar o CLI do GCP.
    assert not marcador.exists(), "deploy.sh chamou gcloud com DRY_RUN=1"


def test_deploy_falha_fechado_quando_anotacao_de_iap_some(tmp_path):
    """A guarda impede publicar um serviço aberto sem ninguém notar."""
    manifesto = SERVICE_YAML.read_text(encoding="utf-8")
    sem_iap = "".join(
        linha
        for linha in manifesto.splitlines(keepends=True)
        if IAP_ANOTACAO not in linha
    )
    assert IAP_ANOTACAO not in sem_iap, "sanidade: mutação não removida"

    resultado, marcador = _rodar_deploy(tmp_path, sem_iap)

    assert resultado.returncode == 1
    assert "IAP ausente no manifesto" in resultado.stderr
    assert not marcador.exists()


def test_deploy_falha_fechado_com_iap_no_template(tmp_path):
    """Anotação no lugar errado é o falso positivo mais provável do IAP."""
    manifesto = SERVICE_YAML.read_text(encoding="utf-8")
    fora_do_servico = manifesto.replace(f"    {IAP_ANOTACAO}: \"true\"\n", "", 1).replace(
        '        run.googleapis.com/cpu-throttling: "true"\n',
        '        run.googleapis.com/cpu-throttling: "true"\n'
        f'        {IAP_ANOTACAO}: "true"\n',
        1,
    )
    assert fora_do_servico != manifesto, "sanidade: mutação não aplicada"

    resultado, _ = _rodar_deploy(tmp_path, fora_do_servico)

    assert resultado.returncode == 1
    assert "IAP ausente no manifesto" in resultado.stderr


def test_deploy_falha_fechado_com_iap_desligado(tmp_path):
    manifesto = SERVICE_YAML.read_text(encoding="utf-8").replace(
        f'{IAP_ANOTACAO}: "true"', f'{IAP_ANOTACAO}: "false"', 1
    )

    resultado, _ = _rodar_deploy(tmp_path, manifesto)

    assert resultado.returncode == 1
    assert "IAP ausente no manifesto" in resultado.stderr


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
