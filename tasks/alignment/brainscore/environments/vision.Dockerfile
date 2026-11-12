FROM sha256:14d8fd6c25a24acc3eb72a7e45986ac8bab4699d831d6257997b290f9a814eaa
USER root
RUN rm -rf /opt/alignment && mkdir -p /opt/alignment
COPY overlay/ /opt/alignment/site-packages/
COPY worker.py /opt/alignment/worker.py
ENV PYTHONPATH=/opt/alignment/site-packages PYTHONDONTWRITEBYTECODE=1 BS_INSTALL_DEPENDENCIES=no HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RESULTCACHING_DISABLE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 CUDA_VISIBLE_DEVICES=""
WORKDIR /tmp
ENTRYPOINT ["python", "/opt/alignment/worker.py"]
