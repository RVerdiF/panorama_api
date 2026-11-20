#!/usr/bin/env python3
"""Identidade da API no GCP — IAM mínimo, sem chave (card `t_b44f8df1`).

Fonte única: `infra/gcp/api-runtime-sa.yaml`. Este script não decide nenhum
valor: ele lê o spec, compara com o estado real e aplica só a diferença.

Subcomandos:

    plan     lê o estado real (read-only) e mostra o que falta/sobra;
    verify   falha (exit 1) se o estado real divergir do spec;
    apply    cria a SA e os bindings que faltam. Exige `--yes`: é ação em
             staging e só roda com autorização explícita do dono.

Sem chave JSON: para provar o que a SA pode fazer usamos impersonação —
`gcloud auth print-access-token --impersonate-service-account=<sa>` — que o
dono já tem via `roles/iam.serviceAccountTokenCreator` no projeto.

Uso (do repo, com o venv):

    .venv/bin/python scripts/gcp_api_runtime_sa.py plan
    .venv/bin/python scripts/gcp_api_runtime_sa.py verify
    .venv/bin/python scripts/gcp_api_runtime_sa.py apply --yes

Nenhum caminho pessoal é fixado aqui: projeto, SA e datasets vêm do YAML.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "infra" / "gcp" / "api-runtime-sa.yaml"

CRM_BASE = "https://cloudresourcemanager.googleapis.com/v1/projects"
BQ_BASE = "https://bigquery.googleapis.com/bigquery/v2/projects"


class GcloudError(RuntimeError):
    """`gcloud` falhou; a mensagem é o stderr real do comando."""


class ApiError(RuntimeError):
    """A API REST respondeu erro."""


# -- leitura do spec -------------------------------------------------------


def load_spec(path: Path = SPEC_PATH) -> dict:
    import yaml

    spec = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for field in ("project", "service_account", "project_roles", "dataset_roles", "key_policy"):
        if field not in spec:
            raise ValueError(f"spec sem campo obrigatório: {field}")
    return spec


def sa_email(spec: dict) -> str:
    return f"{spec['service_account']['account_id']}@{spec['project']}.iam.gserviceaccount.com"


def member(spec: dict) -> str:
    return f"serviceAccount:{sa_email(spec)}"


# -- funções puras (testadas hermeticamente) -------------------------------


def roles_for_member(bindings: list[dict], member_id: str) -> set[str]:
    """Papéis concedidos ao `member_id` na policy. Bindings condicionais contam
    como papel concedido — condição não reduz privilégio por si só."""
    roles: set[str] = set()
    for binding in bindings or []:
        if member_id in (binding.get("members") or []):
            roles.add(binding.get("role", ""))
    return roles


def access_roles_for_member(access: list[dict], email: str) -> set[str]:
    """Papéis do dataset em que `email` aparece como `userByEmail`."""
    roles: set[str] = set()
    for entry in access or []:
        if entry.get("userByEmail") == email:
            roles.add(entry.get("role", ""))
    return roles


def user_managed_keys(keys: list[dict]) -> list[dict]:
    """Só chaves criadas por humano/service account contam: SYSTEM_MANAGED é
    gerenciada pelo Google e não é credencial exportável."""
    return [k for k in keys or [] if k.get("keyType") == "USER_MANAGED"]


def boolean_policy_state(payload: dict) -> str:
    """Normaliza org policy v1 (`booleanPolicy.enforced`) e v2 (`spec.rules`)."""
    if not payload:
        return "unknown"
    boolean = payload.get("booleanPolicy") or {}
    if boolean.get("enforced") is True:
        return "enforced"
    spec = payload.get("spec") or {}
    for rule in spec.get("rules") or []:
        if rule.get("enforce") is True:
            return "enforced"
    return "not_enforced"


def expected_project_roles(spec: dict) -> set[str]:
    return set(spec["project_roles"])


def expected_dataset_roles(spec: dict) -> dict[str, set[str]]:
    expected: dict[str, set[str]] = {}
    for grant in spec["dataset_roles"]:
        expected.setdefault(grant["dataset_id"], set()).add(grant["role"])
    return expected


def compute_diff(
    spec: dict,
    project_roles: set[str],
    dataset_roles: dict[str, set[str]],
    keys: list[dict],
    policy_state: str,
) -> dict[str, list[str]]:
    """Diferença entre o spec e o estado real, em termos acionáveis."""
    missing: list[str] = []
    extra: list[str] = []

    for role in sorted(expected_project_roles(spec) - project_roles):
        missing.append(f"projeto: falta {role}")
    for role in sorted(project_roles - expected_project_roles(spec)):
        extra.append(f"projeto: papel a mais {role}")

    expected_ds = expected_dataset_roles(spec)
    for dataset_id, roles in expected_ds.items():
        real = dataset_roles.get(dataset_id, set())
        for role in sorted(roles - real):
            missing.append(f"dataset {dataset_id}: falta {role}")
        for role in sorted(real - roles):
            extra.append(f"dataset {dataset_id}: papel a mais {role}")
    # Papel em dataset que o spec não prevê é privilégio a mais.
    for dataset_id, roles in dataset_roles.items():
        if dataset_id not in expected_ds and roles:
            extra.append(f"dataset {dataset_id}: papel não previsto {sorted(roles)}")

    if user_managed_keys(keys):
        extra.append("chaves: existe chave USER_MANAGED (a API não usa chave)")
    if policy_state != "enforced":
        extra.append(
            "org policy: "
            f"{spec['key_policy']['org_policy']} não está enforced (estado: {policy_state})"
        )
    return {"missing": missing, "extra": extra}


def probe_findings(expected: dict, granted: list[str]) -> list[str]:
    """`testIamPermissions` devolve só o que foi concedido. Compara com o spec:
    permissão positiva ausente = IAM quebrado; negativa concedida = excesso."""
    granted_set = set(granted or [])
    findings: list[str] = []
    for permission in expected.get("positive", []):
        if permission not in granted_set:
            findings.append(f"falta permissão {permission}")
    for permission in expected.get("negative", []):
        if permission in granted_set:
            findings.append(f"permissão a mais: {permission}")
    return findings


# -- transporte ------------------------------------------------------------


def gcloud(*args: str) -> str:
    proc = subprocess.run(
        ["gcloud", *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise GcloudError(
            " ".join(["gcloud", *args]) + "\n" + (proc.stderr.strip() or proc.stdout.strip())
        )
    return proc.stdout


def access_token(impersonate: str | None = None) -> str:
    args = ["auth", "print-access-token", "--quiet"]
    if impersonate:
        args.append(f"--impersonate-service-account={impersonate}")
    return gcloud(*args).strip()


def http(method: str, url: str, token: str, body: dict | None = None) -> dict:
    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8") or "{}"
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ApiError(f"{method} {url} -> HTTP {exc.code}: {detail}") from exc


def http_status(method: str, url: str, token: str, body: dict | None = None) -> tuple[int, str]:
    """Como `http`, mas devolve (status, corpo) em vez de levantar em erro.

    Sondas que esperam negação precisam do código HTTP: 403 é o resultado
    desejado, não uma falha do script.
    """
    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


# -- leitura do estado real ------------------------------------------------


def service_account_exists(spec: dict) -> bool:
    try:
        gcloud(
            "iam",
            "service-accounts",
            "describe",
            sa_email(spec),
            f"--project={spec['project']}",
        )
        return True
    except GcloudError as exc:
        if "NOT_FOUND" in str(exc) or "Unknown service account" in str(exc):
            return False
        raise


def project_policy_roles(spec: dict, token: str) -> set[str]:
    policy = http("POST", f"{CRM_BASE}/{spec['project']}:getIamPolicy", token, {})
    return roles_for_member(policy.get("bindings", []), member(spec))


def dataset_access(spec: dict, token: str, dataset_id: str) -> list[dict]:
    dataset = http("GET", f"{BQ_BASE}/{spec['project']}/datasets/{dataset_id}", token)
    return dataset.get("access", [])


def all_dataset_roles(spec: dict, token: str) -> dict[str, set[str]]:
    """Papéis da SA em TODOS os datasets do projeto.

    Olhar só `panorama_serving` esconderia privilégio esquecido em outro
    dataset — exatamente o que o card quer impedir.
    """
    listing = http("GET", f"{BQ_BASE}/{spec['project']}/datasets", token)
    roles: dict[str, set[str]] = {}
    for item in listing.get("datasets", []):
        dataset_id = item["datasetReference"]["datasetId"]
        access = dataset_access(spec, token, dataset_id)
        found = access_roles_for_member(access, sa_email(spec))
        if found:
            roles[dataset_id] = found
    return roles


def sa_keys(spec: dict) -> list[dict]:
    if not service_account_exists(spec):
        return []
    raw = gcloud(
        "iam",
        "service-accounts",
        "keys",
        "list",
        f"--iam-account={sa_email(spec)}",
        f"--project={spec['project']}",
        "--format=json",
    )
    return json.loads(raw or "[]")


def org_policy_state(spec: dict) -> str:
    raw = gcloud(
        "resource-manager",
        "org-policies",
        "describe",
        spec["key_policy"]["org_policy"],
        f"--project={spec['project']}",
        "--effective",
        "--format=json",
    )
    return boolean_policy_state(json.loads(raw or "{}"))


def classify_denial(permission: str, status: int, detail: str) -> tuple[str, str]:
    """Classifica uma tentativa que DEVE ser negada.

    Devolve `("ok", "")` quando a negação prova a ausência da permissão,
    `("problem", ...)` quando a permissão foi concedida (privilégio a mais) e
    `("warning", ...)` quando a sonda não decide nada — caso da API desabilitada
    no projeto, que nega a qualquer identidade e portanto não distingue IAM.
    """
    if 200 <= status < 300:
        return ("problem", f"permissão a mais: {permission}")
    if "SERVICE_DISABLED" in detail or "has not been used in project" in detail:
        return (
            "warning",
            f"sonda de {permission} inconclusiva: API desabilitada no projeto "
            "(a ausência segue provada pela lista exata de papéis)",
        )
    if status == 403:
        return ("ok", "")
    return ("warning", f"sonda de {permission} inconclusiva (HTTP {status})")


def probe_project(spec: dict) -> tuple[list[str], list[str]]:
    """Sondas de escopo projeto, como a SA: job `dryRun` e `getIamPolicy` real."""
    probe = spec.get("iam_probe", {}).get("project", {})
    token = access_token(impersonate=sa_email(spec))
    problems: list[str] = []
    warnings: list[str] = []

    if probe.get("positive"):
        body = {
            "configuration": {
                "query": {"query": "SELECT 1", "useLegacySql": False, "dryRun": True}
            }
        }
        status, detail = http_status(
            "POST", f"{BQ_BASE}/{spec['project']}/jobs", token, body
        )
        if not 200 <= status < 300:
            problems.append(
                "projeto: falta permissão bigquery.jobs.create (job dryRun negado)"
            )

    if probe.get("negative"):
        status, detail = http_status(
            "POST", f"{CRM_BASE}/{spec['project']}:getIamPolicy", token, {}
        )
        for permission in probe["negative"]:
            kind, message = classify_denial(permission, status, detail)
            if kind == "problem":
                problems.append(f"projeto: {message}")
            elif kind == "warning":
                warnings.append(f"projeto: {message}")
    return problems, warnings


def probe_dataset(spec: dict, dataset_id: str) -> list[str]:
    """`testIamPermissions` do BigQuery, COMO a SA (impersonação, sem chave)."""
    probe = spec.get("iam_probe", {}).get("dataset", {})
    permissions = list(probe.get("positive", [])) + list(probe.get("negative", []))
    if not permissions:
        return []
    token = access_token(impersonate=sa_email(spec))
    result = http(
        "POST",
        f"{BQ_BASE}/{spec['project']}/datasets/{dataset_id}:testIamPermissions",
        token,
        {"permissions": permissions},
    )
    return [
        f"dataset {dataset_id}: {item}"
        for item in probe_findings(probe, result.get("permissions", []))
    ]


# -- comandos --------------------------------------------------------------


def inspect(spec: dict) -> dict:
    token = access_token()
    keys = sa_keys(spec)
    return {
        "sa_exists": service_account_exists(spec),
        "project_roles": project_policy_roles(spec, token),
        "dataset_roles": all_dataset_roles(spec, token),
        "keys": keys,
        "policy_state": org_policy_state(spec),
    }


def cmd_plan(spec: dict) -> int:
    state = inspect(spec)
    diff = compute_diff(
        spec, state["project_roles"], state["dataset_roles"], state["keys"], state["policy_state"]
    )
    print(f"SA: {sa_email(spec)}")
    print(f"existe: {'sim' if state['sa_exists'] else 'não'}")
    print(f"papéis no projeto: {sorted(state['project_roles']) or 'nenhum'}")
    print(f"papéis em datasets: {state['dataset_roles'] or 'nenhum'}")
    print(f"chaves de usuário: {len(user_managed_keys(state['keys']))}")
    print(f"org policy: {state['policy_state']}")
    print()
    if not diff["missing"] and not diff["extra"]:
        print("estado conforme o spec; nada a aplicar.")
        return 0
    for item in diff["missing"]:
        print(f"  aplicar: {item}")
    for item in diff["extra"]:
        print(f"  corrigir: {item}")
    return 0


def cmd_verify(spec: dict) -> int:
    state = inspect(spec)
    problems: list[str] = []
    warnings: list[str] = []

    if not state["sa_exists"]:
        problems.append(f"SA {sa_email(spec)} não existe")

    diff = compute_diff(
        spec, state["project_roles"], state["dataset_roles"], state["keys"], state["policy_state"]
    )
    problems += diff["missing"] + diff["extra"]

    if state["sa_exists"] and "iam_probe" in spec:
        project_problems, project_warnings = probe_project(spec)
        problems += project_problems
        warnings += project_warnings
        for dataset_id in expected_dataset_roles(spec):
            problems += probe_dataset(spec, dataset_id)

    for item in warnings:
        print(f"aviso: {item}")

    if problems:
        print("DIVERGÊNCIA:")
        for item in problems:
            print(f"  - {item}")
        return 1
    print("ok: SA, IAM mínimo, ausência de chave e org policy conforme o spec.")
    return 0


def cmd_apply(spec: dict, confirmed: bool) -> int:
    if not confirmed:
        print(
            "recusado: `apply` altera IAM em staging e exige `--yes` depois da "
            "autorização explícita do dono.",
            file=sys.stderr,
        )
        return 2

    state = inspect(spec)

    if not state["sa_exists"]:
        print(f"criando SA {sa_email(spec)}")
        gcloud(
            "iam",
            "service-accounts",
            "create",
            spec["service_account"]["account_id"],
            f"--display-name={spec['service_account']['display_name']}",
            f"--project={spec['project']}",
        )

    for role in spec["project_roles"]:
        if role not in state["project_roles"]:
            print(f"concedendo {role} no projeto")
            gcloud(
                "projects",
                "add-iam-policy-binding",
                spec["project"],
                f"--member={member(spec)}",
                f"--role={role}",
                "--condition=None",
                "--quiet",
            )

    token = access_token()
    for grant in spec["dataset_roles"]:
        dataset_id = grant["dataset_id"]
        access = dataset_access(spec, token, dataset_id)
        if grant["role"] in access_roles_for_member(access, sa_email(spec)):
            continue
        print(f"concedendo {grant['role']} no dataset {dataset_id}")
        updated = list(access) + [{"role": grant["role"], "userByEmail": sa_email(spec)}]
        http(
            "PATCH",
            f"{BQ_BASE}/{spec['project']}/datasets/{dataset_id}?fields=access",
            token,
            {"datasetReference": {"projectId": spec["project"], "datasetId": dataset_id}, "access": updated},
        )

    # Nenhuma chave é criada em nenhum caminho: é o ponto do card.
    return cmd_verify(spec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Identidade da API no GCP: IAM mínimo, sem chave")
    parser.add_argument("--spec", default=str(SPEC_PATH), help="caminho do YAML (default: infra/gcp/api-runtime-sa.yaml)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="mostra a diferença entre spec e estado real (read-only)")
    sub.add_parser("verify", help="falha se o estado real divergir do spec")
    apply_parser = sub.add_parser("apply", help="aplica o que falta (exige --yes)")
    apply_parser.add_argument("--yes", action="store_true", help="confirma a alteração em staging")

    args = parser.parse_args(argv)
    spec = load_spec(Path(args.spec))

    try:
        if args.command == "plan":
            return cmd_plan(spec)
        if args.command == "verify":
            return cmd_verify(spec)
        return cmd_apply(spec, args.yes)
    except (GcloudError, ApiError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
