# Standalone CPU inference image. The Python base is pinned by digest; this
# task does not depend on a local EEG or maintainer image.
FROM python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b

RUN python3 -m pip install --no-cache-dir \
    numpy==2.2.6 \
    scipy==1.15.3 \
    scikit-learn==1.6.1 \
    torch==2.7.1 \
    safetensors==0.5.3

# Tested linux/arm64 output digest on 2026-10-12:
# sha256:e0bc28779515b7f9f6191d65d1fa5a36c6770ca134b9b076be00d7d71a3f2f21
