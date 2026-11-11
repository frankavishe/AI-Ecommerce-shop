FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/models
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
# The model (~375 MB) downloads into the /models volume on first start.
VOLUME ["/models"]
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s \
  CMD python -c "import json,urllib.request,sys; sys.exit(json.load(urllib.request.urlopen('http://localhost:8090/health'))['status'] != 'ok')"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
