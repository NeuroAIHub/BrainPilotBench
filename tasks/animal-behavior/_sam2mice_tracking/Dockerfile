FROM python:3.12-slim
COPY requirements.txt /opt/tracking-requirements.txt
RUN pip install --no-cache-dir -r /opt/tracking-requirements.txt
ENV OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
WORKDIR /work
ENTRYPOINT ["python", "/worker/worker.py"]
