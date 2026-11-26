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
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 465))
    MAIL_USE_TLS = False
    MAIL_USE_SSL = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL')

    # --- Matomo Analytics ---
    MATOMO_URL = os.environ.get('MATOMO_URL', '')       # z.B. https://matomo.stumpfmeista3d.de
    MATOMO_SITE_ID = os.environ.get('MATOMO_SITE_ID', '1')

    # --- Shop ---
    # Solange False, ist der Shop nur für eingeloggte Admins sichtbar (Vorschau).
    SHOP_ENABLED = os.environ.get('SHOP_ENABLED', 'false').lower() in ('1', 'true', 'yes')
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
    # Versandpauschale in Cent (nur Deutschland)
    SHOP_SHIPPING_CENTS = int(os.environ.get('SHOP_SHIPPING_CENTS', 495))
    # Ab diesem Warenwert versandkostenfrei (Cent, 0 = nie)
    SHOP_FREE_SHIPPING_FROM_CENTS = int(os.environ.get('SHOP_FREE_SHIPPING_FROM_CENTS', 0))
    SHOP_SHIPPING_LABEL = os.environ.get('SHOP_SHIPPING_LABEL', 'Versand innerhalb Deutschlands')
    SHOP_MAX_QTY_PER_ITEM = 10
    # Wie lange der Bestand während des Bezahlvorgangs reserviert bleibt (Stripe: min. 30 Min.)
    SHOP_CHECKOUT_MINUTES = 30
    PRODUCT_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

    # --- SEO / Site-Metadaten ---
    SITE_NAME = 'Stumpfmeista3D'
    SITE_DESCRIPTION = ('3D-Druck & IT-Service aus Berlin. '
                        'Von der Beratung über die Konstruktion bis zum fertigen Ersatzteil.')
    SITE_URL = os.environ.get('SITE_URL', 'https://stumpfmeista3d.org')
