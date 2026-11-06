# Image legere officielle Python
FROM python:3.13-slim

# Relie le package ghcr.io a ce depot GitHub
LABEL org.opencontainers.image.source="https://github.com/laitooma/New-Api"

# Pas de fichiers .pyc, logs affiches immediatement
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependances d'abord : Docker garde cette couche en cache
# tant que requirements.txt ne change pas.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code de l'application
COPY app/ ./app/

# Ne pas tourner en root dans le conteneur
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Docker verifie lui-meme que l'API repond (curl n'existe pas dans l'image slim)
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
