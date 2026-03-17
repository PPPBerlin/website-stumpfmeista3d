import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # --- Sicherheit ---
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-bitte-aendern')

    # --- Datenbank ---
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///stumpfmeista3d.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Datei-Uploads ---
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB max pro Request
    ALLOWED_EXTENSIONS = {'stl', '3mf', 'pdf', 'jpg', 'jpeg', 'png'}

    # --- Mail ---
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL')

    # --- Matomo Analytics ---
    MATOMO_URL = os.environ.get('MATOMO_URL', '')       # z.B. https://matomo.stumpfmeista3d.de
    MATOMO_SITE_ID = os.environ.get('MATOMO_SITE_ID', '1')

    # --- SEO / Site-Metadaten ---
    SITE_NAME = 'Stumpfmeista3D'
    SITE_DESCRIPTION = ('3D-Druck & IT-Service aus Berlin. '
                        'Von der Beratung über die Konstruktion bis zum fertigen Ersatzteil.')
    SITE_URL = os.environ.get('SITE_URL', 'https://stumpfmeista3d.org')
