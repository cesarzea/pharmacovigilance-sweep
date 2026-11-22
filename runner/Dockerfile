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
# Editable install: the code resolves prompts/ relative to its source files (parents[2] = /app), which
# a site-packages install would break. PVSWEEP_PROMPTS_DIR covers the matcher as well.
ENV PVSWEEP_PROMPTS_DIR=/app/prompts
RUN pip install --no-cache-dir -e ./runner snowflake-connector-python==5.2.0 cryptography==50.0.2
# Fail the build, not the job, if the prompts are not where the code looks for them.
RUN python -I -c "import pvsweep_runner.steps as s, pvsweep_runner.__main__ as m; \
assert (s.PROMPTS / 'screening.md').is_file(), s.PROMPTS; \
assert (s.PROMPTS / 'extraction.schema.json').is_file(), s.PROMPTS; \
assert m.MATCH_PROMPT.is_file(), m.MATCH_PROMPT; \
import pvsweep_agent.matcher, pvsweep_runner.snowflake_store, pvsweep_agent.backend, pvsweep_agent.clients; \
print('prompts at', s.PROMPTS)"

WORKDIR /app
CMD ["python", "-I", "-m", "pvsweep_runner", "--help"]
