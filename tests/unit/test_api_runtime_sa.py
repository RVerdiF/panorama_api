"""Identidade da API no GCP: spec de IAM mínimo e lógica de verificação.

Testes herméticos: não falam com o GCP. Exercitam o spec versionado e as
funções puras que decidem `ok`/`divergência` (card `t_b44f8df1`).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "infra" / "gcp" / "api-runtime-sa.yaml"
SCRIPT_PATH = REPO_ROOT / "scripts" / "gcp_api_runtime_sa.py"


def _load_script():
    module_spec = importlib.util.spec_from_file_location("gcp_api_runtime_sa", SCRIPT_PATH)
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


gcp_sa = _load_script()


@pytest.fixture(scope="module")
def spec() -> dict:
    return gcp_sa.load_spec(SPEC_PATH)


# -- spec versionado -------------------------------------------------------


def test_spec_aponta_para_a_sa_dedicada_da_api(spec):
    assert spec["project"] == "panorama-escola-staging"
    assert spec["service_account"]["account_id"] == "panorama-api-runtime"
    # A SA do pipeline é gerenciada por Terraform; reutilizá-la viraria drift.
    assert spec["service_account"]["account_id"] != "panorama-escola-runtime"


def test_projeto_concede_apenas_job_user(spec):
    assert spec["project_roles"] == ["roles/bigquery.jobUser"]


def test_dataset_de_serving_concede_apenas_leitura(spec):
    assert spec["dataset_roles"] == [{"dataset_id": "panorama_serving", "role": "READER"}]


def test_nenhuma_chave_de_usuario_permitida(spec):
    assert spec["key_policy"]["allow_user_managed_keys"] is False
    assert spec["key_policy"]["org_policy"] == "constraints/iam.disableServiceAccountKeyCreation"


def test_spec_nao_carrega_caminho_pessoal_nem_projeto_errado():
    texto = SPEC_PATH.read_text(encoding="utf-8")
    for proibido in ("/home/", "rafaelverdifreitas", "hotmail.com"):
        assert proibido not in texto


def test_script_nao_fixa_caminho_pessoal():
    texto = SCRIPT_PATH.read_text(encoding="utf-8")
    for proibido in ("/home/", "hotmail.com"):
        assert proibido not in texto


def test_email_da_sa_e_derivado_do_spec(spec):
    assert gcp_sa.sa_email(spec) == (
        "panorama-api-runtime@panorama-escola-staging.iam.gserviceaccount.com"
    )
    assert gcp_sa.member(spec) == (
        "serviceAccount:panorama-api-runtime@panorama-escola-staging.iam.gserviceaccount.com"
    )


# -- funções puras ---------------------------------------------------------


def test_roles_for_member_ignora_bindings_de_outros_membros():
    bindings = [
        {"role": "roles/bigquery.jobUser", "members": ["serviceAccount:api@x.iam.gserviceaccount.com"]},
        {"role": "roles/bigquery.dataEditor", "members": ["serviceAccount:pipeline@x.iam.gserviceaccount.com"]},
    ]
    assert gcp_sa.roles_for_member(bindings, "serviceAccount:api@x.iam.gserviceaccount.com") == {
        "roles/bigquery.jobUser"
    }


def test_roles_for_member_trata_binding_condicional_como_concedido():
    bindings = [
        {
            "role": "roles/bigquery.admin",
            "members": ["serviceAccount:api@x.iam.gserviceaccount.com"],
            "condition": {"expression": "request.time < timestamp('2030-01-01')"},
        }
    ]
    assert "roles/bigquery.admin" in gcp_sa.roles_for_member(
        bindings, "serviceAccount:api@x.iam.gserviceaccount.com"
    )


def test_access_roles_for_member_le_apenas_user_by_email():
    access = [
        {"role": "READER", "specialGroup": "projectReaders"},
        {"role": "OWNER", "userByEmail": "outra@x.iam.gserviceaccount.com"},
        {"role": "READER", "userByEmail": "api@x.iam.gserviceaccount.com"},
    ]
    assert gcp_sa.access_roles_for_member(access, "api@x.iam.gserviceaccount.com") == {"READER"}


def test_user_managed_keys_ignora_chave_gerenciada_pelo_google():
    keys = [
        {"name": ".../keys/1", "keyType": "SYSTEM_MANAGED"},
        {"name": ".../keys/2", "keyType": "USER_MANAGED"},
    ]
    assert [k["name"] for k in gcp_sa.user_managed_keys(keys)] == [".../keys/2"]


def test_boolean_policy_state_aceita_v1_e_v2():
    assert gcp_sa.boolean_policy_state({"booleanPolicy": {"enforced": True}}) == "enforced"
    assert gcp_sa.boolean_policy_state({"spec": {"rules": [{"enforce": True}]}}) == "enforced"
    assert gcp_sa.boolean_policy_state({"spec": {"rules": [{"enforce": False}]}}) == "not_enforced"
    assert gcp_sa.boolean_policy_state({}) == "unknown"


# -- diff entre spec e estado real ----------------------------------------


def _estado_conforme(spec):
    return {
        "project_roles": {"roles/bigquery.jobUser"},
        "dataset_roles": {"panorama_serving": {"READER"}},
        "keys": [{"keyType": "SYSTEM_MANAGED"}],
        "policy_state": "enforced",
    }


def test_estado_conforme_nao_gera_acao(spec):
    diff = gcp_sa.compute_diff(spec, **_estado_conforme(spec))

    assert diff == {"missing": [], "extra": []}


def test_sa_sem_bindings_aparece_como_faltando(spec):
    estado = _estado_conforme(spec)
    estado["project_roles"] = set()
    estado["dataset_roles"] = {}

    diff = gcp_sa.compute_diff(spec, **estado)

    assert "projeto: falta roles/bigquery.jobUser" in diff["missing"]
    assert "dataset panorama_serving: falta READER" in diff["missing"]


def test_papel_a_mais_no_projeto_e_denunciado(spec):
    estado = _estado_conforme(spec)
    estado["project_roles"] = {"roles/bigquery.jobUser", "roles/bigquery.dataEditor"}

    diff = gcp_sa.compute_diff(spec, **estado)

    assert "projeto: papel a mais roles/bigquery.dataEditor" in diff["extra"]


def test_papel_em_dataset_nao_previsto_e_denunciado(spec):
    estado = _estado_conforme(spec)
    estado["dataset_roles"] = {
        "panorama_serving": {"READER"},
        "outro_dataset": {"WRITER"},
    }

    diff = gcp_sa.compute_diff(spec, **estado)

    assert "dataset outro_dataset: papel não previsto ['WRITER']" in diff["extra"]


def test_chave_de_usuario_e_denunciada(spec):
    estado = _estado_conforme(spec)
    estado["keys"] = [{"keyType": "USER_MANAGED"}]

    diff = gcp_sa.compute_diff(spec, **estado)

    assert any("chave USER_MANAGED" in item for item in diff["extra"])


def test_org_policy_nao_enforced_e_denunciada(spec):
    estado = _estado_conforme(spec)
    estado["policy_state"] = "not_enforced"

    diff = gcp_sa.compute_diff(spec, **estado)

    assert any("não está enforced" in item for item in diff["extra"])


# -- sondas de testIamPermissions -----------------------------------------


def test_probe_findings_aprova_o_esperado(spec):
    probe = spec["iam_probe"]["dataset"]

    assert gcp_sa.probe_findings(probe, probe["positive"]) == []


def test_probe_findings_acusa_permissao_positiva_ausente(spec):
    probe = spec["iam_probe"]["dataset"]

    achados = gcp_sa.probe_findings(probe, probe["positive"][1:])

    assert any("falta permissão" in item for item in achados)


def test_probe_findings_acusa_permissao_negativa_concedida(spec):
    probe = spec["iam_probe"]["project"]

    achados = gcp_sa.probe_findings(probe, probe["positive"] + ["resourcemanager.projects.setIamPolicy"])

    assert "permissão a mais: resourcemanager.projects.setIamPolicy" in achados


# -- guardas de execução ---------------------------------------------------


def test_apply_sem_yes_e_recusado_sem_tocar_no_gcp(capsys):
    # `cmd_apply` checa a confirmação antes de qualquer leitura/chamada.
    assert gcp_sa.main(["apply"]) == 2
    assert "exige `--yes`" in capsys.readouterr().err
