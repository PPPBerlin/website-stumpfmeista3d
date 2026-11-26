from flask import Blueprint, render_template, current_app, Response, make_response
from datetime import datetime

core_bp = Blueprint('core', __name__)


@core_bp.route('/')
def index():
    """Haupt-Onepager."""
    return render_template(
        'index.html',
        site_name=current_app.config['SITE_NAME'],
        site_description=current_app.config['SITE_DESCRIPTION'],
    )


@core_bp.route('/impressum')
def impressum():
    return render_template('impressum.html')


@core_bp.route('/datenschutz')
def datenschutz():
    return render_template('datenschutz.html')


@core_bp.route('/sitemap.xml')
def sitemap():
    """Dynamische XML-Sitemap für Google & Co."""
    base = current_app.config['SITE_URL'].rstrip('/')
    today = datetime.utcnow().strftime('%Y-%m-%d')
    pages = [
        {'loc': f'{base}/',           'priority': '1.0', 'changefreq': 'monthly'},
        {'loc': f'{base}/#services',  'priority': '0.8', 'changefreq': 'monthly'},
        {'loc': f'{base}/#about',     'priority': '0.7', 'changefreq': 'yearly'},
        {'loc': f'{base}/#contact',   'priority': '0.9', 'changefreq': 'monthly'},
        {'loc': f'{base}/impressum',  'priority': '0.3', 'changefreq': 'yearly'},
        {'loc': f'{base}/datenschutz','priority': '0.3', 'changefreq': 'yearly'},
    ]
    if current_app.config['SHOP_ENABLED']:
        from models import Product
        pages.append({'loc': f'{base}/shop', 'priority': '0.9', 'changefreq': 'weekly'})
        for p in Product.query.filter_by(is_active=True).all():
            pages.append({'loc': f'{base}/shop/{p.slug}', 'priority': '0.8', 'changefreq': 'weekly'})
        for path in ('agb', 'widerruf', 'versand'):
            pages.append({'loc': f'{base}/{path}', 'priority': '0.3', 'changefreq': 'yearly'})
    xml = render_template('sitemap.xml', pages=pages, today=today)
    resp = make_response(xml)
    resp.headers['Content-Type'] = 'application/xml'
    return resp


@core_bp.route('/robots.txt')
def robots():
    """robots.txt — Admin-Bereich von Indexierung ausschließen."""
    base = current_app.config['SITE_URL'].rstrip('/')
    content = (
        'User-agent: *\n'
        'Allow: /\n'
        'Disallow: /admin/\n'
        'Disallow: /kontakt/\n'
        'Disallow: /warenkorb\n'
        'Disallow: /kasse\n'
        'Disallow: /vertrag-widerrufen\n'
        f'Sitemap: {base}/sitemap.xml\n'
    )
    resp = make_response(content)
    resp.headers['Content-Type'] = 'text/plain'
    return resp
