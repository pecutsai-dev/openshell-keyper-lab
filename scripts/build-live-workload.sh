#!/usr/bin/env bash
# Run inside the disposable Linux VM. Adds curl to the official default image.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
build_root="$repo_root/.approval-lab/live-workload-build"
mkdir -p "$build_root"
cp -- "${LAB_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}" "$build_root/lab-ca.crt"
cat > "$build_root/Dockerfile" <<'DOCKERFILE'
FROM nvcr.io/nvidia/base/ubuntu:24.04
COPY lab-ca.crt /etc/ssl/certs/ca-certificates.crt
RUN sed -i s,http://,https://,g /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
DOCKERFILE
docker build --network host -t approval-lab-workload:0.1.6 "$build_root"
cat > "$build_root/Dockerfile.supervisor" <<'DOCKERFILE'
FROM ghcr.io/nvidia/openshell/supervisor:0.1.6
COPY lab-ca.crt /etc/ssl/certs/ca-certificates.crt
DOCKERFILE
docker build -f "$build_root/Dockerfile.supervisor" -t approval-lab-supervisor:0.1.6 "$build_root"
