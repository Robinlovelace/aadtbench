# syntax=docker/dockerfile:1
# sDNA tool image (sdna-plus, AGPL v3). Build from the repository root:
#   docker build -f containers/sdna/Dockerfile -t aadtbench-sdna .
# Self-contained (no base image) so that CI can cache it with buildx.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="AADTBench sdna"
LABEL org.opencontainers.image.source="https://github.com/Robinlovelace/aadtbench"

ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/workspace HOME=/tmp
WORKDIR /workspace

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt sdna-plus==5.2.0

COPY adapters ./adapters
COPY benchmark/__init__.py benchmark/system.py ./benchmark/

ENTRYPOINT ["python", "-m", "adapters.sdna"]
