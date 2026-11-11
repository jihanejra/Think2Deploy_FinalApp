FROM python:3.12-slim

WORKDIR /opt/project
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EVAL_DATA_DIR=/opt/project/data

COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

# L'API n'utilise que pipeline/config.py et pipeline/db.py (bibliothèque standard)
COPY pipeline/__init__.py pipeline/config.py pipeline/db.py pipeline/
COPY app/ app/

RUN useradd --create-home --uid 1000 api
USER api

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
