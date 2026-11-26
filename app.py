import os
from flask import Flask
from config import Config
from extensions import db, migrate, login_manager, csrf, limiter, mail


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Upload-Ordner sicherstellen
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'products'), exist_ok=True)

    # Extensions initialisieren
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

    # Jinja-Filter
    from blueprints.shop.services import format_euro, cart_count
    from legal_format import legal_html, legal_text, berlin
    app.jinja_env.filters['euro'] = format_euro
    app.jinja_env.filters['legal_html'] = legal_html
    app.jinja_env.filters['legal_text'] = legal_text
    app.jinja_env.filters['berlin'] = berlin

    # Jinja-Globals
    from datetime import datetime
    from flask_login import current_user

    @app.context_processor
    def inject_globals():
        shop_public = app.config['SHOP_ENABLED']
        return {
            'now': datetime.utcnow(),
            'matomo_url': app.config.get('MATOMO_URL', ''),
            'matomo_site_id': app.config.get('MATOMO_SITE_ID', '1'),
            'site_url': app.config['SITE_URL'].rstrip('/'),
            'shop_public': shop_public,
            'shop_visible': shop_public or current_user.is_authenticated,
            'cart_count': cart_count(),
        }

    # Blueprints registrieren
    from blueprints.core.routes import core_bp
    from blueprints.contact.routes import contact_bp
    from blueprints.admin.routes import admin_bp
    from blueprints.shop.routes import shop_bp
    from blueprints.legal.routes import legal_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(contact_bp, url_prefix='/kontakt')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(shop_bp)
    app.register_blueprint(legal_bp)

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
