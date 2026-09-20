FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

# HOME muss dem Host-HOME entsprechen: das hermes-venv referenziert seinen
# uv-CPython-3.11 über absolute Pfade (siehe docker-compose.yml + README).
ENV HOME=/home/bennetgriese \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    HF_HOME=/hf-cache \
    HERMES_CWD=/workspace
RUN mkdir -p /home/bennetgriese /app/data /workspace /hf-cache \
 && chmod 777 /home/bennetgriese /app/data /workspace /hf-cache

EXPOSE 8020
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020"]
