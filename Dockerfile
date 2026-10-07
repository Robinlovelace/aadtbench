# syntax=docker/dockerfile:1
# Cenbench — reproducible pedestrian flow benchmarks
# Multi-stage: (1) sDNA+ C++ lib with OpenMP, (2) Python pipeline
# Base: geocompx/python (Debian Bookworm, Python 3.12, full geo stack)

# Stage 1: Build sDNA+ with OpenMP
FROM ghcr.io/geocompx/python AS sdna-builder

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    g++ cmake git libboost1.74-dev libboost-system1.74-dev \
    libboost-chrono1.74-dev libboost-date-time1.74-dev \
    libboost-thread1.74-dev libboost-iostreams1.74-dev \
    libboost-random1.74-dev libboost-math-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN git clone --branch Cross_platform --depth=1 \
    https://github.com/Robinlovelace/sdna_plus.git /src/sdna-plus

WORKDIR /src/sdna-plus
RUN BOOST_INC=$(dpkg -L libboost1.74-dev | grep 'include/boost/version.hpp' | head -1 | sed 's|/boost/version.hpp||') && \
    echo '#define SDNA_VERSION "4.1.1"' > sDNA/sdna_vs2008/version_generated.h && \
    echo '#define VERSION_GENERATED "4.1.1 (Linux)"' >> sDNA/sdna_vs2008/version_generated.h && \
    SDNA_SRC="sDNA/sdna_vs2008" && MUPARSER_SRC="sDNA/muparser/drop/src" && \
    CXXFLAGS="-std=c++14 -O2 -fPIC -fopenmp -fpermissive -DNDEBUG -I${SDNA_SRC} -I${MUPARSER_SRC}/../include -I${BOOST_INC}" && \
    mkdir -p /build/objs /build/objs/mu && \
    for f in ${SDNA_SRC}/*.cpp; do g++ $CXXFLAGS -c "$f" -o "/build/objs/$(basename $f .cpp).o"; done && \
    for f in ${MUPARSER_SRC}/*.cpp; do g++ $CXXFLAGS -c "$f" -o "/build/objs/mu/$(basename $f .cpp).o"; done && \
    g++ -shared -fopenmp -ldl -lpthread /build/objs/*.o /build/objs/mu/*.o -o /build/sdna_vs2008.so && \
    echo "sDNA+ build complete"

# Stage 2: Pipeline environment
FROM ghcr.io/geocompx/python

LABEL org.opencontainers.image.title="Cenbench"
LABEL org.opencontainers.image.description="Reproducible pedestrian flow benchmark environment"
LABEL org.opencontainers.image.source="https://github.com/Robinlovelace/cenbench"
LABEL org.opencontainers.image.licenses="CC-BY-4.0"

# Quarto for report rendering
RUN wget -q https://github.com/quarto-dev/quarto-cli/releases/download/v1.8.27/quarto-1.8.27-linux-amd64.deb \
    && dpkg -i quarto-1.8.27-linux-amd64.deb && rm quarto-1.8.27-linux-amd64.deb

# pipx for sDNA+ CLI
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y pipx \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# sDNA+ .so and CLI from builder
COPY --from=sdna-builder /build/sdna_vs2008.so /opt/sdna/lib/sdna_vs2008.so
ENV SDNADLL=/opt/sdna/lib/sdna_vs2008.so
RUN pipx install sdna_plus --force
ENV PATH="${PATH}:/root/.local/bin"

WORKDIR /workspace
COPY . .

# Additional Python deps not in base image
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir dvc

ENV PYTHONPATH="/workspace"

CMD ["dvc", "repro"]
