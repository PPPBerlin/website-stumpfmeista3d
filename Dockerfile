FROM python:3.12-slim

WORKDIR /app

# System-Abhängigkeiten
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python-Abhängigkeiten installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App-Code kopieren
COPY . .

# Upload-Ordner erstellen
RUN mkdir -p /app/uploads

# Gunicorn starten (Flask-Migrate läuft davor via docker-compose command)
EXPOSE 5000
