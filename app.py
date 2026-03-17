import os
from flask import Flask
from config import Config
from extensions import db, migrate, login_manager, csrf, limiter, mail


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Upload-Ordner sicherstellen
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Extensions initialisieren
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

    # Jinja-Globals
    from datetime import datetime
    @app.context_processor
    def inject_globals():
        return {
            'now': datetime.utcnow(),
            'matomo_url': app.config.get('MATOMO_URL', ''),
            'matomo_site_id': app.config.get('MATOMO_SITE_ID', '1'),
        }

    # Blueprints registrieren
    from blueprints.core.routes import core_bp
    from blueprints.contact.routes import contact_bp
    from blueprints.admin.routes import admin_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(contact_bp, url_prefix='/kontakt')
    app.register_blueprint(admin_bp, url_prefix='/admin')

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
