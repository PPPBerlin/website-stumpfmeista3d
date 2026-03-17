"""
Admin-User anlegen via Kommandozeilen-Argumente.
Verwendung: python create_admin.py <username> <passwort>
"""
import sys
from app import create_app
from extensions import db
from models import AdminUser

if len(sys.argv) != 3:
    print("Verwendung: python create_admin.py <username> <passwort>")
    sys.exit(1)

username = sys.argv[1]
password = sys.argv[2]

app = create_app()

with app.app_context():
    if AdminUser.query.filter_by(username=username).first():
        print(f'Fehler: Benutzer "{username}" existiert bereits.')
        sys.exit(1)

    user = AdminUser(username=username, is_superadmin=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    print(f'Admin-User "{username}" erfolgreich angelegt!')
