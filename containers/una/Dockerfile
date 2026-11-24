# syntax=docker/dockerfile:1
# Urban Network Analysis (UNA) flow tool image. Build from the repository root:
#   docker build -f containers/una/Dockerfile -t aadtbench-una .
# Shares the python:3.12-slim + requirements.txt layer with all other tool images.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="AADTBench una" \
      org.opencontainers.image.description="AADTBench traffic flow estimation adapter for Urban Network Analysis (UNA)" \
      org.opencontainers.image.source="https://github.com/Robinlovelace/aadtbench" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/workspace HOME=/tmp NUMBA_CACHE_DIR=/tmp/numba MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /workspace

COPY requirements.txt /tmp/requirements.txt
RUN mkdir -p /tmp/numba /tmp/matplotlib && chmod 1777 /tmp/numba /tmp/matplotlib \
    && pip install -r /tmp/requirements.txt

# Install UNA from pinned GitHub commit and purge git afterwards to keep the image small.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && pip install "git+https://github.com/City-Form-Lab/urban_network_analysis.git@d270792" \
    && apt-get purge -y --auto-remove git \
    && rm -rf /var/lib/apt/lists/*

COPY adapters ./adapters
COPY benchmark/__init__.py benchmark/system.py ./benchmark/
RUN python -m compileall -q /workspace

ENTRYPOINT ["python", "-m", "adapters.una"]
