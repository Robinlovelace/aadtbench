# syntax=docker/dockerfile:1
# AequilibraE assignment tool image. Build from the repository root:
#   docker build -f containers/aequilibrae/Dockerfile -t aadtbench-aequilibrae .
# Self-contained (no base image) so that CI can cache it with buildx.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="AADTBench aequilibrae"
LABEL org.opencontainers.image.source="https://github.com/Robinlovelace/cenbench"

ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/workspace HOME=/tmp NUMBA_CACHE_DIR=/tmp/numba
WORKDIR /workspace

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt aequilibrae==1.7.0

COPY adapters ./adapters
COPY benchmark/__init__.py benchmark/system.py ./benchmark/

ENTRYPOINT ["python", "-m", "adapters.aequilibrae"]
