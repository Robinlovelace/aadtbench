# syntax=docker/dockerfile:1
# AequilibraE assignment tool image. Build from the repository root:
#   docker build -f containers/aequilibrae/Dockerfile -t aadtbench-aequilibrae .
# Shares the python:3.12-slim + requirements.txt layer with all other tool images.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="AADTBench aequilibrae" \
      org.opencontainers.image.description="AADTBench traffic flow estimation adapter for AequilibraE assignment" \
      org.opencontainers.image.source="https://github.com/Robinlovelace/aadtbench" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/workspace HOME=/tmp NUMBA_CACHE_DIR=/tmp/numba MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /workspace

COPY requirements.txt /tmp/requirements.txt
RUN mkdir -p /tmp/numba /tmp/matplotlib && chmod 1777 /tmp/numba /tmp/matplotlib \
    && pip install -r /tmp/requirements.txt

RUN pip install aequilibrae==1.7.2

COPY adapters ./adapters
COPY benchmark/__init__.py benchmark/system.py ./benchmark/
RUN python -m compileall -q /workspace

ENTRYPOINT ["python", "-m", "adapters.aequilibrae"]
