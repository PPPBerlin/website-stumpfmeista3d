import os

import stripe
from flask import (Blueprint, render_template, request, redirect, url_for, flash,
                   abort, current_app, session, send_from_directory, jsonify)
from flask_login import current_user

from extensions import db, csrf, limiter
from models import Product, ProductVariant, Order
from . import services as svc

shop_bp = Blueprint('shop', __name__)

PENDING_KEY = 'pending_order_id'


@shop_bp.before_request
def shop_visibility():
    """Solange SHOP_ENABLED aus ist, sehen nur eingeloggte Admins den Shop."""
    if request.endpoint in ('shop.stripe_webhook', 'shop.product_image'):
        return
    if not current_app.config['SHOP_ENABLED'] and not current_user.is_authenticated:
        abort(404)


def product_image_path():
    return os.path.join(current_app.config['UPLOAD_FOLDER'], 'products')


# ---------------------------------------------------------------------------
# Katalog
# ---------------------------------------------------------------------------
@shop_bp.route('/shop')
def index():
    products = (Product.query.filter_by(is_active=True)
                .order_by(Product.sort_order, Product.name).all())
    return render_template('shop/index.html', products=products)


@shop_bp.route('/shop/<slug>')
def product(slug):
    p = Product.query.filter_by(slug=slug).first_or_404()
    if not p.is_active and not current_user.is_authenticated:
        abort(404)
    variants = p.active_variants
    return render_template('shop/product.html', product=p, variants=variants)


@shop_bp.route('/shop/bild/<path:filename>')
def product_image(filename):
    resp = send_from_directory(product_image_path(), filename, max_age=60 * 60 * 24 * 30)
    return resp


# ---------------------------------------------------------------------------
# Warenkorb
# ---------------------------------------------------------------------------
@shop_bp.route('/warenkorb')
def cart():
    lines, subtotal, problems = svc.cart_lines()
    for p in problems:
        flash(p, 'error')
    shipping = svc.shipping_for(subtotal) if lines else 0
    free_from = current_app.config['SHOP_FREE_SHIPPING_FROM_CENTS']
    return render_template('shop/cart.html', lines=lines, subtotal=subtotal,
                           shipping=shipping, total=subtotal + shipping,
                           free_from=free_from,
                           stripe_ready=svc.stripe_configured())


@shop_bp.route('/warenkorb/hinzufuegen', methods=['POST'])
@limiter.limit('60 per hour')
def cart_add():
    variant = db.session.get(ProductVariant, request.form.get('variant_id', type=int) or 0)
    if not variant or not variant.is_active or not variant.product.is_active:
        flash('Dieser Artikel ist nicht verfügbar.', 'error')
        return redirect(request.referrer or url_for('shop.index'))

    qty = max(1, request.form.get('qty', 1, type=int))
    cart = svc.get_cart()
    key = str(variant.id)
    limit = min(variant.stock, current_app.config['SHOP_MAX_QTY_PER_ITEM'])
    new_qty = min(cart.get(key, 0) + qty, limit)
    if new_qty <= 0:
        flash('Leider ausverkauft.', 'error')
        return redirect(url_for('shop.product', slug=variant.product.slug))
    if new_qty < cart.get(key, 0) + qty:
        flash(f'Es sind nur {limit} Stück verfügbar — Menge angepasst.', 'info')
    else:
        flash('Zum Warenkorb hinzugefügt.', 'success')
    cart[key] = new_qty
    svc.save_cart(cart)
    return redirect(url_for('shop.cart'))


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
    return redirect(url_for('shop.cart'))


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------
def _abort_pending_order():
    """Bricht eine noch offene Bestellung aus dieser Browser-Session ab."""
    order_id = session.pop(PENDING_KEY, None)
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
        return redirect(url_for('shop.cart'))
    shipping = svc.shipping_for(subtotal)
    return render_template('shop/checkout.html', lines=lines, subtotal=subtotal,
                           shipping=shipping, total=subtotal + shipping,
                           stripe_ready=svc.stripe_configured())


@shop_bp.route('/kasse', methods=['POST'])
@limiter.limit('20 per hour')
def checkout():
    if not svc.stripe_configured():
        flash('Die Kasse ist gerade nicht verfügbar. Bitte versuch es später erneut.', 'error')
        return redirect(url_for('shop.cart'))

    _abort_pending_order()

    lines, subtotal, problems = svc.cart_lines()
    if problems or not lines:
        for p in problems:
            flash(p, 'error')
        return redirect(url_for('shop.cart'))

    try:
        order = svc.create_order_from_cart(lines, subtotal)
    except svc.OutOfStock as e:
        flash(f'„{e}" wurde gerade verkauft — bitte prüfe deinen Warenkorb.', 'error')
        return redirect(url_for('shop.cart'))

    base = current_app.config['SITE_URL'].rstrip('/')
    try:
        checkout_session = svc.create_checkout_session(
            order,
            success_url=base + url_for('shop.success') + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=base + url_for('shop.checkout_cancelled'),
            terms_url=base + url_for('legal.agb'),
            withdrawal_url=base + url_for('legal.widerruf'),
            image_url_for=lambda img: base + url_for('shop.product_image', filename=img.filename),
        )
    except stripe.StripeError as e:
        current_app.logger.error(f'Stripe-Checkout fehlgeschlagen ({order.number}): {e}')
        svc.abort_order(order, 'Abgebrochen')
        flash('Die Zahlung konnte nicht gestartet werden. Bitte versuch es später erneut.', 'error')
        return redirect(url_for('shop.cart'))

    session[PENDING_KEY] = order.id
    return redirect(checkout_session.url, code=303)


@shop_bp.route('/kasse/abgebrochen')
def checkout_cancelled():
    _abort_pending_order()
    flash('Bezahlung abgebrochen — dein Warenkorb ist noch da.', 'info')
    return redirect(url_for('shop.cart'))


@shop_bp.route('/kasse/danke')
def success():
    session_id = request.args.get('session_id', '')
    order = Order.query.filter_by(stripe_session_id=session_id).first() if session_id else None
    if not order:
        return redirect(url_for('shop.index'))
    try:
        svc.sync_order_with_session(order)
    except stripe.StripeError as e:
        current_app.logger.error(f'Session-Abgleich fehlgeschlagen ({order.number}): {e}')
    if order.status in ('Offen', 'Bezahlt'):
        svc.clear_cart()
        session.pop(PENDING_KEY, None)
    return render_template('shop/success.html', order=order)


# ---------------------------------------------------------------------------
# Stripe Webhook
# ---------------------------------------------------------------------------
@shop_bp.route('/shop/webhook/stripe', methods=['POST'])
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
