"""
Shop-Routen. Der Blueprint `shop_bp` wird pro Schaufenster registriert
(siehe app.py / storefronts.py): einmal ohne Präfix (Stumpfmeista3D) und
einmal unter /boutique (Stumpfmeista3D Boutique). Gemeinsame Endpunkte, die
es nur einmal geben darf (Webhook, Produktbilder), liegen in `shop_common_bp`.
"""
import os

import stripe
from flask import (Blueprint, render_template, request, redirect, flash,
                   abort, current_app, session, send_from_directory, jsonify)
from flask_login import current_user

from extensions import db, csrf, limiter
from models import Product, ProductVariant, Order
from storefronts import current_sf, sf_url, sf_base
from . import services as svc

shop_bp = Blueprint('shop', __name__)
shop_common_bp = Blueprint('shop_common', __name__)
boutique_start_bp = Blueprint('boutique_start', __name__)


def _pending_key():
    return f'pending_order_{current_sf().key}'


def tpl(name):
    """Template des aktuellen Schaufensters, z. B. boutique/product.html."""
    return f'{current_sf().templates}/{name}'


def storefront_guard():
    """
    - Eigene Domain konfiguriert, aber Aufruf über /boutique/… der Hauptdomain → 301.
    - Schaufenster ausgeschaltet → nur eingeloggte Admins sehen es (Vorschau).
    """
    sf = current_sf()
    host = (request.host or '').split(':')[0].lower()
    if sf.domain and host != sf.domain:
        path = request.full_path.rstrip('?')
        if path.startswith(sf.prefix):
            path = path[len(sf.prefix):] or '/'
        return redirect(f'https://{sf.domain}{path}', code=301)
    if not sf.enabled and not current_user.is_authenticated:
        abort(404)


shop_bp.before_request(storefront_guard)
boutique_start_bp.before_request(storefront_guard)


def product_image_path():
    return os.path.join(current_app.config['UPLOAD_FOLDER'], 'products')


def _visible_products():
    sf = current_sf()
    return (Product.query.filter_by(is_active=True)
            .filter(getattr(Product, f'show_in_{sf.key}').is_(True))
            .order_by(Product.sort_order, Product.name).all())


# ---------------------------------------------------------------------------
# Katalog
# ---------------------------------------------------------------------------
@shop_bp.route('/shop')
def index():
    if current_sf().prefix:
        # Boutique: Startseite ist der Katalog
        return redirect(sf_url('shop.index'), code=301)
    return render_template(tpl('index.html'), products=_visible_products())


@boutique_start_bp.route('/')
def home():
    return render_template(tpl('index.html'), products=_visible_products())


@shop_bp.route('/shop/<slug>')
def product(slug):
    p = Product.query.filter_by(slug=slug).first_or_404()
    sf = current_sf()
    if (not p.is_active or not p.in_storefront(sf.key)) and not current_user.is_authenticated:
        abort(404)
    return render_template(tpl('product.html'), product=p, variants=p.active_variants)


@shop_common_bp.route('/shop/bild/<path:filename>')
def product_image(filename):
    return send_from_directory(product_image_path(), filename, max_age=60 * 60 * 24 * 30)


# ---------------------------------------------------------------------------
# Warenkorb (pro Schaufenster getrennt)
# ---------------------------------------------------------------------------
@shop_bp.route('/warenkorb')
def cart():
    lines, subtotal, problems = svc.cart_lines()
    for p in problems:
        flash(p, 'error')
    shipping = svc.shipping_for(subtotal) if lines else 0
    free_from = current_app.config['SHOP_FREE_SHIPPING_FROM_CENTS']
    return render_template(tpl('cart.html'), lines=lines, subtotal=subtotal,
                           shipping=shipping, total=subtotal + shipping,
                           free_from=free_from,
                           stripe_ready=svc.stripe_configured())


@shop_bp.route('/warenkorb/hinzufuegen', methods=['POST'])
@limiter.limit('60 per hour')
def cart_add():
    sf = current_sf()
    variant = db.session.get(ProductVariant, request.form.get('variant_id', type=int) or 0)
    if (not variant or not variant.is_active or not variant.product.is_active
            or not variant.product.in_storefront(sf.key)):
        flash('Dieser Artikel ist nicht verfügbar.', 'error')
        return redirect(sf_url('shop.index'))

    qty = max(1, request.form.get('qty', 1, type=int))
    cart = svc.get_cart()
    key = str(variant.id)
    limit = min(variant.stock, current_app.config['SHOP_MAX_QTY_PER_ITEM'])
    new_qty = min(cart.get(key, 0) + qty, limit)
    if new_qty <= 0:
        flash('Leider ausverkauft.', 'error')
        return redirect(sf_url('shop.product', slug=variant.product.slug))
    if new_qty < cart.get(key, 0) + qty:
        flash(f'Es sind nur {limit} Stück verfügbar — Menge angepasst.', 'info')
    else:
        flash('Zum Warenkorb hinzugefügt.', 'success')
    cart[key] = new_qty
    svc.save_cart(cart)
    return redirect(sf_url('shop.cart'))


@shop_bp.route('/warenkorb/aktualisieren', methods=['POST'])
def cart_update():
    cart = svc.get_cart()
    key = str(request.form.get('variant_id', type=int))
    if key in cart:
        qty = request.form.get('qty', 0, type=int)
        if request.form.get('action') == 'remove':
            qty = 0
        cart[key] = max(0, qty)
        svc.save_cart(cart)
    return redirect(sf_url('shop.cart'))


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------
def _abort_pending_order():
    """Bricht eine noch offene Bestellung aus dieser Browser-Session ab."""
    order_id = session.pop(_pending_key(), None)
    if not order_id:
        return
    order = db.session.get(Order, order_id)
    if order and order.status == 'Offen':
        try:
            svc.abort_order(order, 'Abgebrochen', expire_stripe=True)
        except stripe.StripeError as e:
            current_app.logger.error(f'Abbruch {order.number} fehlgeschlagen: {e}')


@shop_bp.route('/kasse')
def checkout_review():
    """Bestellübersicht mit Button „Zahlungspflichtig bestellen" (§ 312j Abs. 3 BGB)."""
    lines, subtotal, problems = svc.cart_lines()
    for p in problems:
        flash(p, 'error')
    if not lines or problems:
        return redirect(sf_url('shop.cart'))
    shipping = svc.shipping_for(subtotal)
    return render_template(tpl('checkout.html'), lines=lines, subtotal=subtotal,
                           shipping=shipping, total=subtotal + shipping,
                           stripe_ready=svc.stripe_configured())


@shop_bp.route('/kasse', methods=['POST'])
@limiter.limit('20 per hour')
def checkout():
    if not svc.stripe_configured():
        flash('Die Kasse ist gerade nicht verfügbar. Bitte versuch es später erneut.', 'error')
        return redirect(sf_url('shop.cart'))

    _abort_pending_order()

    lines, subtotal, problems = svc.cart_lines()
    if problems or not lines:
        for p in problems:
            flash(p, 'error')
        return redirect(sf_url('shop.cart'))

    try:
        order = svc.create_order_from_cart(lines, subtotal)
    except svc.OutOfStock as e:
        flash(f'„{e}" wurde gerade verkauft — bitte prüfe deinen Warenkorb.', 'error')
        return redirect(sf_url('shop.cart'))

    site = current_app.config['SITE_URL'].rstrip('/')
    try:
        checkout_session = svc.create_checkout_session(
            order,
            success_url=sf_url('shop.success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=sf_url('shop.checkout_cancelled', _external=True),
            terms_url=sf_url('legal.agb', _external=True),
            withdrawal_url=sf_url('legal.widerruf', _external=True),
            image_url_for=lambda img: site + '/shop/bild/' + img.filename,
        )
    except stripe.StripeError as e:
        current_app.logger.error(f'Stripe-Checkout fehlgeschlagen ({order.number}): {e}')
        svc.abort_order(order, 'Abgebrochen')
        flash('Die Zahlung konnte nicht gestartet werden. Bitte versuch es später erneut.', 'error')
        return redirect(sf_url('shop.cart'))

    session[_pending_key()] = order.id
    return redirect(checkout_session.url, code=303)


@shop_bp.route('/kasse/abgebrochen')
def checkout_cancelled():
    _abort_pending_order()
    flash('Bezahlung abgebrochen — dein Warenkorb ist noch da.', 'info')
    return redirect(sf_url('shop.cart'))


@shop_bp.route('/kasse/danke')
def success():
    session_id = request.args.get('session_id', '')
    order = Order.query.filter_by(stripe_session_id=session_id).first() if session_id else None
    if not order:
        return redirect(sf_url('shop.index'))
    try:
        svc.sync_order_with_session(order)
    except stripe.StripeError as e:
        current_app.logger.error(f'Session-Abgleich fehlgeschlagen ({order.number}): {e}')
    if order.status in ('Offen', 'Bezahlt'):
        svc.clear_cart()
        session.pop(_pending_key(), None)
    return render_template(tpl('success.html'), order=order)


# ---------------------------------------------------------------------------
# Stripe Webhook (einmalig, gilt für alle Schaufenster)
# ---------------------------------------------------------------------------
@shop_common_bp.route('/shop/webhook/stripe', methods=['POST'])
@csrf.exempt
@limiter.exempt
def stripe_webhook():
    secret = current_app.config['STRIPE_WEBHOOK_SECRET']
    if not secret:
        abort(404)
    try:
        event = stripe.Webhook.construct_event(
            request.get_data(), request.headers.get('Stripe-Signature', ''), secret)
    except (ValueError, stripe.SignatureVerificationError):
        return jsonify({'error': 'invalid'}), 400

    obj = event['data']['object']
    order = None
    if event['type'].startswith('checkout.session.'):
        order = Order.query.filter_by(stripe_session_id=obj['id']).first()
    if not order:
        return jsonify({'ignored': True})

    etype = event['type']
    try:
        if etype in ('checkout.session.completed',
                     'checkout.session.async_payment_succeeded',
                     'checkout.session.expired'):
            svc.sync_order_with_session(order, obj['id'])
        elif etype == 'checkout.session.async_payment_failed':
            svc.sync_order_with_session(order, obj['id'])  # Kundendaten für die Mail
            if order.status == 'Offen':
                svc.abort_order(order, 'Abgebrochen')
                svc.send_payment_failed(order)
    except stripe.StripeError as e:
        current_app.logger.error(f'Webhook-Verarbeitung fehlgeschlagen ({order.number}): {e}')
        return jsonify({'error': 'retry'}), 500

    return jsonify({'ok': True})
