# syntax=docker/dockerfile:1.7
# --- Stage 1: Tailwind-CSS kompilieren (Standalone-CLI, kein Node nötig) ---
FROM debian:bookworm-slim AS css
ADD --chmod=755 --checksum=sha256:7d24f7fa191d2193b78cd5f5a42a6093e14409521908529f42d80b11fde1f1d4 \
    https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-linux-x64 \
    /usr/local/bin/tailwindcss
WORKDIR /src
COPY tailwind.config.js ./
COPY static ./static
COPY templates ./templates
COPY blueprints ./blueprints
COPY *.py ./
RUN tailwindcss -i static/css/input.css -o static/css/site.css --minify

# --- Stage 2: App ---
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
COPY --from=css /src/static/css/site.css /app/static/css/site.css

# Upload-Ordner erstellen
RUN mkdir -p /app/uploads

# Gunicorn starten (Flask-Migrate läuft davor via docker-compose command)
EXPOSE 5000
