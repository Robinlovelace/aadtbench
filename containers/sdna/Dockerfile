# syntax=docker/dockerfile:1
# sDNA tool image (sdna-plus, AGPL v3). Build from the repository root:
#   docker build -f containers/sdna/Dockerfile -t aadtbench-sdna .
# Shares the python:3.12-slim + requirements.txt layer with all other tool images.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="AADTBench sdna" \
      org.opencontainers.image.description="AADTBench traffic flow estimation adapter for sDNA (sdna-plus)" \
      org.opencontainers.image.source="https://github.com/Robinlovelace/aadtbench" \
      org.opencontainers.image.licenses="GPL-3.0-or-later"

ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/workspace HOME=/tmp NUMBA_CACHE_DIR=/tmp/numba MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /workspace

COPY requirements.txt /tmp/requirements.txt
RUN mkdir -p /tmp/numba /tmp/matplotlib && chmod 1777 /tmp/numba /tmp/matplotlib \
    && pip install -r /tmp/requirements.txt

# 5.2.0 is the first PyPI release with the OpenMP Linux build (sdna_plus PR 122, merged 29 June 2026).
RUN pip install sdna-plus==5.2.0

COPY adapters ./adapters
COPY benchmark/__init__.py benchmark/system.py ./benchmark/
RUN python -m compileall -q /workspace

ENTRYPOINT ["python", "-m", "adapters.sdna"]
