# syntax=docker/dockerfile:1
# Urban Network Analysis (UNA) flow tool image. Build from the repository root:
#   docker build -f containers/una/Dockerfile -t aadtbench-una .
# Self-contained (no base image) so that CI can cache it with buildx.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="AADTBench una"
LABEL org.opencontainers.image.source="https://github.com/Robinlovelace/aadtbench"

ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/workspace HOME=/tmp NUMBA_CACHE_DIR=/tmp/numba
WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt \
    "git+https://github.com/City-Form-Lab/urban_network_analysis.git@d270792"

COPY adapters ./adapters
COPY benchmark/__init__.py benchmark/system.py ./benchmark/

ENTRYPOINT ["python", "-m", "adapters.una"]
