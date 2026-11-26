from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()


def client_ip():
    """
    Echte Besucher-IP hinter Cloudflare Tunnel → Nginx Proxy Manager.
    Ohne das sähe der Limiter für alle Besucher dieselbe Proxy-IP.
    """
    from flask import request
    return (request.headers.get('CF-Connecting-IP')
            or request.headers.get('X-Real-IP')
            or (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
            or get_remote_address())


limiter = Limiter(key_func=client_ip)
mail = Mail()

login_manager.login_view = 'admin.login'
login_manager.login_message = 'Bitte einloggen.'
