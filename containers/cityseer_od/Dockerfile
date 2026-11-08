# syntax=docker/dockerfile:1
# cityseer OD betweenness tool image. Build from the repository root:
#   docker build -f containers/cityseer_od/Dockerfile -t aadtbench-cityseer_od .
# Self-contained (no base image) so that CI can cache it with buildx.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="AADTBench cityseer_od" \
      org.opencontainers.image.description="AADTBench traffic flow estimation adapter for cityseer OD betweenness" \
      org.opencontainers.image.source="https://github.com/Robinlovelace/aadtbench" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/workspace HOME=/tmp NUMBA_CACHE_DIR=/tmp/numba MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /workspace

# cityseer imports a library that needs libexpat, which the slim image lacks.
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /tmp/numba /tmp/matplotlib && chmod 1777 /tmp/numba /tmp/matplotlib

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt cityseer==5.8.0 \
    && python -c "import cityseer.metrics.networks, cityseer.tools.io" \
    && chmod -R a+rwX /tmp/numba /tmp/matplotlib

COPY adapters ./adapters
COPY benchmark/__init__.py benchmark/system.py ./benchmark/
RUN python -m compileall -q /workspace

ENTRYPOINT ["python", "-m", "adapters.cityseer_od"]
