FROM python:3.12-slim-bookworm@sha256:a5d9a95a366e9cb09c32e2623ae98320433f169b2974b451969459ca585e009a

ARG NUMPY_VERSION=2.2.6
RUN python3 -m pip install --no-cache-dir "numpy==${NUMPY_VERSION}"

LABEL org.opencontainers.image.title="BrainPilotBench submission inference"
LABEL org.opencontainers.image.description="Minimal numpy runtime for isolated benchmark submission inference"

WORKDIR /work
