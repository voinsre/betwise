FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY ml/models/ ./ml/models/
COPY start.sh .
RUN sed -i 's/\r$//' start.sh && chmod +x start.sh

RUN adduser --disabled-password --no-create-home appuser \
    && chown -R appuser:appuser /app/ml/models
USER appuser

EXPOSE 2323
ENV PYTHONPATH=/app
ENV MODEL_DIR=/app/ml/models

CMD ["./start.sh"]
