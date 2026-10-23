# Offline build only, from a locally prepared Python 3.12 + numpy 2.3.5 image.
# Require a content-addressed LOCAL_BASE from the maintainer; no default remote image.
ARG LOCAL_BASE
FROM ${LOCAL_BASE}
RUN python -c "import sys, numpy; assert sys.version_info[:2] == (3, 12); assert numpy.__version__ == '2.3.5'"
COPY tasks/alignment/_shared/worker.py /opt/alignment/worker.py
ENV PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
WORKDIR /tmp
ENTRYPOINT ["python", "/opt/alignment/worker.py"]
