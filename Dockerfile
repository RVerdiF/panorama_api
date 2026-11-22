# syntax=docker/dockerfile:1
# Imagem da API do Panorama Escola (decisão D1, card `t_cab24513`).
#
# Regras que não vêm do Dockerfile e sim do card:
#   * multi-stage, base python slim, usuário não-root;
#   * **nenhuma credencial na imagem**: a autenticação no BigQuery é ADC da
#     service account do Cloud Run (`panorama-api-runtime`, sem chave JSON);
#   * a aplicação escuta em `$PORT` (o Cloud Run injeta a porta).
#
# Build e publicação: `cloudbuild.yaml` (`gcloud builds submit`).

# -- estágio 1: dependências -------------------------------------------------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# venv isolado: o estágio final copia só ele, sem pip, wheel nem cache.
RUN python -m venv /opt/venv

WORKDIR /build

# Licença/metadados primeiro: declarar a few. `pyproject.toml` é a fonte das
# dependências (não há requirements.txt neste repo).
COPY pyproject.toml README.md ./
COPY src ./src

RUN /opt/venv/bin/pip install .

# -- estágio 2: runtime ------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

# Usuário sem privilégio, UID fixo e sem shell de login.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

USER app:app

EXPOSE 8080

# Forma exec + `sh -c` de propósito: `$PORT` só existe em runtime (o Cloud Run
# o define) e o `exec` mantém o uvicorn como PID 1 (sinais chegam nele).
CMD ["sh", "-c", "exec uvicorn panorama_api.main:app --host 0.0.0.0 --port \"${PORT}\""]
