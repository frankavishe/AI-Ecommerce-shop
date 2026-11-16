FROM python:3.12-slim
# GPU=1 adds the CUDA 12 cuBLAS/cuDNN wheels that CTranslate2 needs (prod GPU box).
ARG GPU=0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/models \
    LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && if [ "$GPU" = "1" ]; then pip install --no-cache-dir nvidia-cublas-cu12==12.4.5.8 nvidia-cudnn-cu12==9.1.0.70; fi
COPY app.py .
# The model (small ~ 480 MB, large-v3 ~ 3 GB) downloads into the /models volume on first start.
VOLUME ["/models"]
EXPOSE 8091
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s \
  CMD python -c "import json,urllib.request,sys; sys.exit(json.load(urllib.request.urlopen('http://localhost:8091/health'))['status'] != 'ok')"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8091"]
