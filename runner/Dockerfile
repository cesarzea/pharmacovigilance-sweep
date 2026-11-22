# Runner image for the Container Apps jobs (load, sweep). Build context: repository root.
#   az acr build -r <registry> -t pvsweep-runner:<tag> --platform linux/amd64 -f runner/Dockerfile .
FROM python:3.13-slim

ENV PYTHONNOUSERSITE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY runner/pyproject.toml ./runner/
COPY runner/pvsweep_load ./runner/pvsweep_load
COPY runner/pvsweep_synth ./runner/pvsweep_synth
COPY runner/pvsweep_runner ./runner/pvsweep_runner
COPY runner/pvsweep_agent ./runner/pvsweep_agent
COPY prompts ./prompts
COPY config ./config
COPY data/synthetic ./data/synthetic
RUN pip install --no-cache-dir ./runner snowflake-connector-python==5.2.0 cryptography==50.0.2

WORKDIR /app
CMD ["python", "-I", "-m", "pvsweep_runner", "--help"]
