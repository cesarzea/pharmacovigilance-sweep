# Foundry hosted agents require linux/amd64 images (built with --platform linux/amd64) and serve on port 8088.
# Build context is the repository root: az acr build -f agent/Dockerfile .
FROM python:3.13-slim

ENV PYTHONNOUSERSITE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8088

WORKDIR /app
COPY agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY runner/pvsweep_agent ./pvsweep_agent
# The Databricks backend shares its connection helper with the runner's store module (standard library only at import).
COPY runner/pvsweep_runner/__init__.py runner/pvsweep_runner/databricks_store.py ./pvsweep_runner/
COPY prompts ./prompts
COPY agent/app.py .

EXPOSE 8088
CMD ["python", "app.py"]
