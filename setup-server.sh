#!/bin/bash
# ---------------------------------------------------------------------------
# Einmaliges Server-Setup Script
# Auf dem Home-Server ausführen, BEVOR docker compose up gestartet wird.
# ---------------------------------------------------------------------------
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
echo "=== Arbeitsverzeichnis: $SCRIPT_DIR ==="
echo "=== Stumpfmeista3D Server Setup ==="

# 1. .env prüfen
if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠  .env angelegt — bitte ausfüllen und das Script erneut starten!"
    exit 1
fi

# 2. ghcr.io Login
echo ""
echo "--- ghcr.io Login ---"
echo "GitHub Username eingeben:"
read GITHUB_USER
echo "GitHub Personal Access Token (Scope: read:packages):"
read -s GITHUB_TOKEN
echo ""

echo "$GITHUB_TOKEN" | docker login ghcr.io -u "$GITHUB_USER" --password-stdin
echo "✓ ghcr.io Login erfolgreich"

# 3. Upload-Ordner anlegen
mkdir -p uploads
echo "✓ uploads/ Ordner angelegt"

# 4. Stack starten
echo ""
echo "--- Docker Compose starten ---"
docker compose pull
docker compose up -d

echo ""
echo "✓ Stack läuft. Warte auf Datenbankmigrationen..."
sleep 8

# 5. Prüfen ob web-Container läuft
if ! docker compose ps web | grep -q "running"; then
    echo "⚠  web-Container läuft nicht. Logs:"
    docker compose logs web --tail=30
    exit 1
fi

# 6. Admin-User anlegen
echo ""
echo "--- Admin-User anlegen ---"
echo "Gewünschter Benutzername:"
read ADMIN_USER
echo "Gewünschtes Passwort:"
read -s ADMIN_PASS
echo ""

docker compose exec web python create_admin.py "$ADMIN_USER" "$ADMIN_PASS"

echo ""
echo "=== Setup abgeschlossen ==="
echo ""
echo "Nächster Schritt: Nginx Proxy Manager konfigurieren"
echo "  stumpfmeista3d.org       → 127.0.0.1:5004"
echo "  matomo.stumpfmeista3d.org → 127.0.0.1:8083"
echo ""
echo "Danach Matomo einrichten unter: https://matomo.stumpfmeista3d.org"
