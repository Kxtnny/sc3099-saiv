FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake \
    libgl1 libglib2.0-0 \
    libsm6 libxext6 libxrender-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-nodeps.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps -r requirements-nodeps.txt

# Bake the ArcFace model pack into the image so the service never downloads
# it at runtime. Only detection (det_10g) and recognition (w600k_r50) are
# used; the other models in the pack are removed to keep the image smaller.
ENV INSIGHTFACE_ROOT=/opt/insightface
RUN python -c "from insightface.app import FaceAnalysis; FaceAnalysis(name='buffalo_l', root='/opt/insightface', allowed_modules=['detection', 'recognition'], providers=['CPUExecutionProvider'])" \
    && rm -f /opt/insightface/models/buffalo_l.zip \
             /opt/insightface/models/buffalo_l/1k3d68.onnx \
             /opt/insightface/models/buffalo_l/2d106det.onnx \
             /opt/insightface/models/buffalo_l/genderage.onnx

COPY app/ ./app/

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]