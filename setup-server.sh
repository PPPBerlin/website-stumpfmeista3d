#!/bin/bash
# ---------------------------------------------------------------------------
# Einmaliges Server-Setup Script
# Auf dem Home-Server ausführen, BEVOR docker compose up gestartet wird.
# ---------------------------------------------------------------------------
set -e

echo "=== Stumpfmeista3D Server Setup ==="

# 1. .env prüfen
if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠  .env angelegt — bitte ausfüllen vor dem nächsten Schritt!"
    exit 1
fi

# 2. ghcr.io Login (damit Watchtower das Image ziehen kann)
echo ""
echo "--- ghcr.io Login ---"
echo "GitHub Username eingeben:"
read GITHUB_USER
echo "GitHub Personal Access Token (Scope: read:packages):"
read -s GITHUB_TOKEN

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
echo "✓ Stack läuft. Warte kurz auf Datenbankmigrationen..."
sleep 5

# 5. Admin-User anlegen
echo ""
echo "--- Admin-User anlegen ---"
echo "Gewünschter Benutzername:"
read ADMIN_USER
echo "Gewünschtes Passwort:"
read -s ADMIN_PASS

docker compose exec web python create_admin.py "$ADMIN_USER" "$ADMIN_PASS"

echo ""
echo "=== Setup abgeschlossen ==="
echo "Matomo einrichten unter: https://matomo.stumpfmeista3d.org"
echo "Admin-Bereich:           https://stumpfmeista3d.org/admin"
