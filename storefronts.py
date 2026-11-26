"""
Schaufenster („Storefronts“): ein Shop-System, mehrere Auftritte.

  main      → Stumpfmeista3D (dunkel, /shop …)
  boutique  → Stumpfmeista3D Boutique (hell, /boutique/ …)

Datenbank, Bestand, Bestellungen, Admin, Stripe und Mails sind gemeinsam.
Pro Schaufenster eigen: Templates, Produktauswahl, Warenkorb, Branding.

Eigene Domain für die Boutique: BOUTIQUE_DOMAIN=boutique.example.de setzen.
  - Anfragen an diese Domain werden intern auf /boutique/… umgeschrieben
    (DomainRouter), Links werden ohne /boutique erzeugt (sf_url).
  - /boutique/… auf der Hauptdomain leitet dann per 301 auf die Domain um.
"""
from dataclasses import dataclass

from flask import current_app, g, has_request_context, request, url_for


@dataclass(frozen=True)
class Storefront:
    key: str
    name: str
    prefix: str            # URL-Präfix ('' = Hauptseite)
    templates: str         # Template-Ordner für Shop-Seiten
    enabled_flag: str      # Config-Schalter
    domain_flag: str = ''  # Config-Key für eine eigene Domain
    bp_prefix: str = ''    # Präfix der Blueprint-Namen

    @property
    def domain(self):
        return (current_app.config.get(self.domain_flag) or '').strip().lower() if self.domain_flag else ''

    @property
    def enabled(self):
        return bool(current_app.config.get(self.enabled_flag))


MAIN = Storefront('main', 'Stumpfmeista3D', '', 'shop', 'SHOP_ENABLED')
BOUTIQUE = Storefront('boutique', 'Stumpfmeista3D Boutique', '/boutique', 'boutique',
                      'BOUTIQUE_ENABLED', 'BOUTIQUE_DOMAIN', 'boutique_')
STOREFRONTS = {sf.key: sf for sf in (MAIN, BOUTIQUE)}


def get_storefront(key):
    return STOREFRONTS.get(key or 'main', MAIN)


def current_sf():
    """Schaufenster der aktuellen Anfrage (anhand des Blueprints)."""
    if not has_request_context():
        return MAIN
    if 'sf' not in g:
        bp = request.blueprint or ''
        g.sf = BOUTIQUE if bp.startswith('boutique_') else MAIN
    return g.sf


def _request_host():
    return (request.host or '').split(':')[0].lower() if has_request_context() else ''


def sf_url(endpoint, sf=None, _external=False, **values):
    """
    url_for für Shop-/Rechtsseiten im richtigen Schaufenster.
    endpoint wie 'shop.cart' oder 'legal.agb' (immer in der Haupt-Schreibweise).
    """
    sf = sf or current_sf()
    if sf.bp_prefix:
        endpoint = 'boutique_start.home' if endpoint == 'shop.index' else sf.bp_prefix + endpoint
    path = url_for(endpoint, **values)
    domain = sf.domain
    if domain and path.startswith(sf.prefix):
        path = path[len(sf.prefix):] or '/'
        if _external or _request_host() != domain:
            return f'https://{domain}{path}'
        return path
    if _external:
        return current_app.config['SITE_URL'].rstrip('/') + path
    return path


def sf_base(sf=None):
    """Externe Basis-URL eines Schaufensters (ohne abschließenden Slash)."""
    sf = sf or current_sf()
    if sf.domain:
        return f'https://{sf.domain}'
    return current_app.config['SITE_URL'].rstrip('/') + sf.prefix


def sf_context(sf=None):
    """Variablen für Rechtstexte und Mails eines Schaufensters."""
    sf = sf or current_sf()
    return {
        'sf': sf,
        'sf_base': sf_base(sf),
        'shop_url': sf_url('shop.index', sf=sf, _external=True),
    }


class DomainRouter:
    """WSGI-Middleware: eigene Domain → interne /boutique/-Routen."""
    PASSTHROUGH = ('/static/', '/shop/bild/')

    def __init__(self, wsgi_app, app):
        self.wsgi_app = wsgi_app
        self.app = app

    def __call__(self, environ, start_response):
        domain = (self.app.config.get(BOUTIQUE.domain_flag) or '').strip().lower()
        if domain:
            host = (environ.get('HTTP_X_FORWARDED_HOST') or environ.get('HTTP_HOST') or '')
            host = host.split(',')[0].strip().split(':')[0].lower()
            path = environ.get('PATH_INFO', '') or '/'
            if host == domain and not path.startswith(self.PASSTHROUGH) \
                    and not path.startswith(BOUTIQUE.prefix + '/') and path != BOUTIQUE.prefix:
                environ['PATH_INFO'] = BOUTIQUE.prefix + path
        return self.wsgi_app(environ, start_response)
