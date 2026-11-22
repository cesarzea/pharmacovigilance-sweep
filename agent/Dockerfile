# Foundry hosted agents require linux/amd64 images (built with --platform linux/amd64) and serve on port 8088.
FROM python:3.13-slim

ENV PYTHONNOUSERSITE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8088

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

EXPOSE 8088
CMD ["python", "app.py"]
