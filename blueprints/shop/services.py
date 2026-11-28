"""
Shop-Logik: Warenkorb, Bestandsreservierung, Stripe-Abgleich und Mails.

Bestandsmodell:
  - Artikel „auf Bestellung gefertigt“ haben keinen Bestand und werden nie reserviert.
  - Beim Start des Checkouts wird der Bestand atomar abgezogen (reserviert).
  - Wird bezahlt → Reservierung wird endgültig.
  - Bricht der Kunde ab / läuft die Stripe-Session ab / schlägt die Zahlung
    fehl → Bestand wird zurückgebucht.
"""
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import stripe
from flask import current_app, session, render_template
from flask_mail import Message
from sqlalchemy import update

from extensions import db, mail
from models import DiscountCode, Order, OrderItem, Product, ProductVariant
from storefronts import current_sf, get_storefront, sf_context


def _cart_key():
    # Jedes Schaufenster hat seinen eigenen Warenkorb
    return f'cart_{current_sf().key}'


# ---------------------------------------------------------------------------
# Formatierung
# ---------------------------------------------------------------------------
def format_euro(cents):
    """1290 → '12,90 €'"""
    cents = int(cents or 0)
    euros, rest = divmod(abs(cents), 100)
    euros_str = f'{euros:,}'.replace(',', '.')
    sign = '-' if cents < 0 else ''
    return f'{sign}{euros_str},{rest:02d} €'


# ---------------------------------------------------------------------------
# Warenkorb (in der signierten Flask-Session: {variant_id: menge})
# ---------------------------------------------------------------------------
def get_cart():
    return dict(session.get(_cart_key(), {}))


def save_cart(cart):
    session[_cart_key()] = {k: v for k, v in cart.items() if v > 0}
    session.modified = True


def clear_cart():
    session.pop(_cart_key(), None)


def cart_count():
    return sum(session.get(_cart_key(), {}).values())


def cart_lines():
    """
    Liefert (lines, subtotal_cents, problems).
    Bereinigt den Warenkorb um nicht mehr verfügbare Varianten und
    begrenzt Mengen auf das Verfügbare (ohne Kunden den Bestand zu verraten).
    """
    cart = get_cart()
    sf = current_sf()
    lines, problems = [], []
    changed = False

    for vid, qty in list(cart.items()):
        variant = db.session.get(ProductVariant, int(vid))
        if (not variant or not variant.is_active or not variant.product.is_active
                or not variant.product.in_storefront(sf.key)):
            problems.append('Ein Artikel ist nicht mehr verfügbar und wurde entfernt.')
            cart.pop(vid)
            changed = True
            continue
        allowed = variant.max_qty
        if allowed <= 0:
            problems.append(f'„{_variant_title(variant)}" ist ausverkauft und wurde entfernt.')
            cart.pop(vid)
            changed = True
            continue
        if qty > allowed:
            problems.append(f'„{_variant_title(variant)}" ist leider nicht in dieser Menge '
                            f'verfügbar — wir haben die Menge angepasst.')
            qty = cart[vid] = allowed
            changed = True
        lines.append({
            'variant': variant,
            'product': variant.product,
            'title': _variant_title(variant),
            'qty': qty,
            'unit_cents': variant.effective_price_cents,
            'total_cents': variant.effective_price_cents * qty,
        })

    if changed:
        save_cart(cart)

    # Lieferzeit: Fertigungszuschlag zählt pro Produkt über alle Varianten
    per_product = {}
    for l in lines:
        per_product[l['product'].id] = per_product.get(l['product'].id, 0) + l['qty']
    for l in lines:
        l['delivery'] = l['product'].delivery_text(per_product[l['product'].id])
        l['extra_days'] = l['product'].extra_days_for(per_product[l['product'].id])

    subtotal = sum(l['total_cents'] for l in lines)
    return lines, subtotal, problems


# ---------------------------------------------------------------------------
# Rabattcodes (eingegebener Code liegt pro Schaufenster in der Session)
# ---------------------------------------------------------------------------
STRIPE_MIN_CHARGE_CENTS = 50
_INVALID = 'Dieser Rabattcode ist leider nicht gültig.'


def _discount_key():
    return f'discount_{current_sf().key}'


def normalize_code(code):
    return (code or '').strip().upper().replace(' ', '')


def set_discount_input(code):
    session[_discount_key()] = normalize_code(code)


def clear_discount_input():
    session.pop(_discount_key(), None)


def berlin_today():
    return datetime.now(ZoneInfo('Europe/Berlin')).date()


def check_discount(dc, subtotal_cents, sf_key):
    """Fehlermeldung für den Kunden oder None, wenn der Code anwendbar ist."""
    if not dc or not dc.is_active or dc.storefront not in ('all', sf_key):
        return _INVALID
    today = berlin_today()
    if dc.valid_from and today < dc.valid_from:
        return f'Dieser Rabattcode gilt erst ab dem {dc.valid_from:%d.%m.%Y}.'
    if dc.valid_until and today > dc.valid_until:
        return 'Dieser Rabattcode ist leider abgelaufen.'
    if dc.max_uses is not None and dc.uses >= dc.max_uses:
        return 'Dieser Rabattcode wurde bereits eingelöst.'
    if subtotal_cents < dc.min_order_cents:
        return (f'Dieser Rabattcode gilt ab einem Bestellwert von '
                f'{format_euro(dc.min_order_cents)}.')
    return None


def cart_totals(subtotal_cents):
    """
    Zwischensumme, Rabatt, Versand, Gesamt — eine Quelle für Warenkorb,
    Bestellübersicht und Bestellung.
    """
    sf = current_sf()
    code = session.get(_discount_key())
    dc = DiscountCode.query.filter_by(code=code).first() if code else None
    error = check_discount(dc, subtotal_cents, sf.key) if code else None
    if code and error == _INVALID:
        clear_discount_input()   # unbekannte/inaktive Codes nicht mitschleppen
    applied = dc if code and not error else None

    discount = applied.amount_for(subtotal_cents) if applied else 0
    if applied and applied.free_shipping:
        shipping = 0
    else:
        shipping = shipping_for(subtotal_cents - discount)
    total = subtotal_cents - discount + shipping
    # Stripe kann keine Zahlungen unter 0,50 € abwickeln
    if discount and total < STRIPE_MIN_CHARGE_CENTS:
        discount = max(0, subtotal_cents + shipping - STRIPE_MIN_CHARGE_CENTS)
        total = subtotal_cents - discount + shipping
    return {
        'subtotal': subtotal_cents,
        'discount_code': applied,
        'discount_input': code if code and error != _INVALID else '',
        'discount_error': error,
        'discount_cents': discount,
        'shipping': shipping,
        'total': total,
    }


def shipping_for(subtotal_cents):
    cfg = current_app.config
    free_from = cfg['SHOP_FREE_SHIPPING_FROM_CENTS']
    if free_from and subtotal_cents >= free_from:
        return 0
    return cfg['SHOP_SHIPPING_CENTS']


def _variant_title(variant):
    if len(variant.product.variants) > 1 or variant.name != 'Standard':
        return f'{variant.product.name} – {variant.name}'
    return variant.product.name


# ---------------------------------------------------------------------------
# Bestellung anlegen + Bestand reservieren
# ---------------------------------------------------------------------------
class OutOfStock(Exception):
    pass


def create_order_from_cart(lines, totals):
    """
    Legt eine Bestellung im Status 'Offen' an und zieht den Bestand atomar ab
    (außer bei Artikeln, die auf Bestellung gefertigt werden).
    """
    dc = totals['discount_code']
    order = Order(status='Offen', storefront=current_sf().key,
                  subtotal_cents=totals['subtotal'], discount_cents=totals['discount_cents'],
                  shipping_cents=totals['shipping'], total_cents=totals['total'])
    if dc:
        order.discount_code_id = dc.id
        order.discount_code = dc.code

    try:
        for line in lines:
            v = line['variant']
            mto = v.product.made_to_order
            if not mto:
                # Bedingtes UPDATE: nur abziehen, wenn genug da ist (race-sicher)
                result = db.session.execute(
                    update(ProductVariant)
                    .where(ProductVariant.id == v.id, ProductVariant.stock >= line['qty'])
                    .values(stock=ProductVariant.stock - line['qty'])
                )
                if result.rowcount != 1:
                    raise OutOfStock(line['title'])
            order.items.append(OrderItem(
                variant_id=v.id,
                product_name=v.product.name,
                variant_name=v.name,
                unit_price_cents=line['unit_cents'],
                quantity=line['qty'],
                made_to_order=mto,
                delivery_time=line.get('delivery') or v.product.delivery_time,
            ))
        order.stock_reserved = True
        db.session.add(order)
        db.session.flush()
        order.number = f'{datetime.utcnow():%Y}-{order.id:04d}'
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return order


def release_stock(order):
    """Bucht reservierten Bestand zurück (idempotent)."""
    if not order.stock_reserved:
        return
    for item in order.items:
        if item.variant_id and not item.made_to_order:
            db.session.execute(
                update(ProductVariant)
                .where(ProductVariant.id == item.variant_id)
                .values(stock=ProductVariant.stock + item.quantity)
            )
    order.stock_reserved = False


def abort_order(order, reason='Abgebrochen', expire_stripe=False):
    """Offene Bestellung abbrechen und Bestand freigeben (idempotent)."""
    if order.status != 'Offen':
        return
    if expire_stripe and order.stripe_session_id:
        try:
            _stripe().checkout.Session.expire(order.stripe_session_id)
        except stripe.StripeError as e:
            # z.B. Session bereits abgeschlossen → dann NICHT abbrechen
            current_app.logger.warning(f'Session-Expire fehlgeschlagen ({order.number}): {e}')
            sess = _stripe().checkout.Session.retrieve(order.stripe_session_id)
            if sess.status == 'complete':
                return
    release_stock(order)
    order.status = reason
    db.session.commit()


# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------
def _stripe():
    stripe.api_key = current_app.config['STRIPE_SECRET_KEY']
    return stripe


def stripe_configured():
    return bool(current_app.config.get('STRIPE_SECRET_KEY'))


def create_checkout_session(order, success_url, cancel_url, terms_url, withdrawal_url,
                            image_url_for):
    s = _stripe()
    base = current_app.config['SITE_URL'].rstrip('/')
    line_items = []
    for item in order.items:
        product_data = {'name': item.display_name}
        variant = item.variant
        if variant and variant.product.cover_image and base.startswith('https://'):
            product_data['images'] = [image_url_for(variant.product.cover_image)]
        line_items.append({
            'quantity': item.quantity,
            'price_data': {
                'currency': 'eur',
                'unit_amount': item.unit_price_cents,
                'product_data': product_data,
            },
        })

    expires_at = int(datetime.utcnow().timestamp()) + \
        current_app.config['SHOP_CHECKOUT_MINUTES'] * 60 + 30

    extra = {}
    if order.discount_cents:
        # Einmal-Gutschein über genau den bei uns berechneten Betrag
        coupon = s.Coupon.create(
            amount_off=order.discount_cents, currency='eur', duration='once',
            max_redemptions=1, name=f'Rabattcode {order.discount_code}'[:40],
            metadata={'order_number': order.number},
        )
        extra['discounts'] = [{'coupon': coupon.id}]
    shipping_label = current_app.config['SHOP_SHIPPING_LABEL']
    if order.shipping_cents == 0 and order.discount_code:
        shipping_label += f' (kostenlos mit {order.discount_code})'

    checkout = s.checkout.Session.create(
        **extra,
        mode='payment',
        locale='de',
        submit_type='pay',
        line_items=line_items,
        shipping_address_collection={'allowed_countries': ['DE']},
        shipping_options=[{
            'shipping_rate_data': {
                'type': 'fixed_amount',
                'display_name': shipping_label,
                'fixed_amount': {'amount': order.shipping_cents, 'currency': 'eur'},
            },
        }],
        client_reference_id=order.number,
        metadata={'order_id': str(order.id), 'order_number': order.number},
        payment_intent_data={
            'description': f'{get_storefront(order.storefront).name} – Bestellung {order.number}',
            'metadata': {'order_id': str(order.id), 'order_number': order.number},
        },
        expires_at=expires_at,
        success_url=success_url,
        cancel_url=cancel_url,
        custom_text={
            'submit': {
                'message': (
                    f'Bestellung {order.number}: Mit Abschluss der Zahlung kommt der '
                    f'Kaufvertrag zustande (AGB: {terms_url}, Widerrufsbelehrung: '
                    f'{withdrawal_url}). Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.'
                ),
            },
        },
    )
    order.stripe_session_id = checkout.id
    db.session.commit()
    return checkout


def _get(obj, *path):
    """Sicherer Zugriff auf verschachtelte Stripe-Objekte/Dicts."""
    for key in path:
        if obj is None:
            return None
        try:
            obj = obj[key]
        except (KeyError, TypeError, AttributeError):
            return None
    return obj


def sync_order_with_session(order, session_id=None):
    """
    Holt die Checkout-Session frisch von Stripe und gleicht die Bestellung ab.
    Wird vom Webhook UND von der Danke-Seite aufgerufen — idempotent.
    """
    sess = _stripe().checkout.Session.retrieve(session_id or order.stripe_session_id)

    if sess.status == 'expired':
        abort_order(order, 'Abgebrochen')
        return order

    if sess.status != 'complete':
        return order

    # Kundendaten übernehmen (einmalig)
    if not order.email:
        details = _get(sess, 'customer_details') or {}
        shipping = (_get(sess, 'collected_information', 'shipping_details')
                    or _get(sess, 'shipping_details') or {})
        addr = _get(shipping, 'address') or _get(details, 'address') or {}
        order.email = _get(details, 'email')
        order.phone = _get(details, 'phone')
        order.name = _get(shipping, 'name') or _get(details, 'name')
        order.address_line1 = _get(addr, 'line1')
        order.address_line2 = _get(addr, 'line2')
        order.postal_code = _get(addr, 'postal_code')
        order.city = _get(addr, 'city')
        order.country = _get(addr, 'country')
        pi = _get(sess, 'payment_intent')
        order.stripe_payment_intent = pi if isinstance(pi, str) else _get(pi, 'id')
        db.session.commit()

    amount = _get(sess, 'amount_total')
    if isinstance(amount, int) and amount != order.total_cents and not order.notes:
        current_app.logger.error(f'Betrag weicht ab ({order.number}): Stripe {amount}, '
                                 f'Shop {order.total_cents}')
        order.notes = (f'ACHTUNG: Stripe hat {format_euro(amount)} abgerechnet, '
                       f'Shop erwartet {format_euro(order.total_cents)}.')
        db.session.commit()

    if sess.payment_status == 'paid' and order.status == 'Offen':
        order.status = 'Bezahlt'
        order.paid_at = datetime.utcnow()
        order.stock_reserved = False  # Bestand ist jetzt endgültig verkauft
        db.session.commit()
        send_order_confirmation(order)
        send_admin_order_notification(order)

    return order


# ---------------------------------------------------------------------------
# Mails (asynchron, damit Gunicorn-Worker nicht blockieren)
# ---------------------------------------------------------------------------
def _send_async(msg):
    app = current_app._get_current_object()

    def run():
        with app.app_context():
            try:
                mail.send(msg)
            except Exception as e:
                app.logger.error(f'Mailversand fehlgeschlagen: {e}')

    threading.Thread(target=run, daemon=True).start()


def _order_mail(order, subject, template, to_customer=True, **extra):
    """Rendert eine Bestell-Mail im Branding des Schaufensters der Bestellung."""
    sf = get_storefront(order.storefront)
    body = render_template(template, order=order, **sf_context(sf), **extra)
    admin = current_app.config.get('ADMIN_EMAIL')
    if to_customer:
        msg = Message(subject=subject.format(shop=sf.name), recipients=[order.email], body=body)
        if admin:
            msg.reply_to = admin
    else:
        msg = Message(subject=subject.format(shop=sf.name), recipients=[admin], body=body)
    return msg


def send_order_confirmation(order):
    if not order.email:
        return
    _send_async(_order_mail(order, f'Deine Bestellung {order.number} bei {{shop}}',
                            'emails/order_confirmation.txt'))


def send_admin_order_notification(order):
    if not current_app.config.get('ADMIN_EMAIL'):
        return
    _send_async(_order_mail(
        order, f'[{{shop}}] Neue Bestellung {order.number} — {format_euro(order.total_cents)}',
        'emails/admin_new_order.txt', to_customer=False))


def send_payment_failed(order):
    if not order.email:
        return
    msg = _order_mail(order, f'Zahlung für Bestellung {order.number} fehlgeschlagen',
                      'emails/payment_failed.txt')
    if current_app.config.get('ADMIN_EMAIL'):
        msg.bcc = [current_app.config['ADMIN_EMAIL']]
    _send_async(msg)


def send_shipping_notification(order):
    if not order.email:
        return
    _send_async(_order_mail(order, f'Deine Bestellung {order.number} ist unterwegs',
                            'emails/order_shipped.txt', tracking_url=tracking_url(order)))


def tracking_url(order):
    """Link zur Sendungsverfolgung für bekannte Versanddienstleister."""
    if not order.tracking_number:
        return None
    n = order.tracking_number.strip()
    return {
        'DHL': f'https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html?piececode={n}',
        'Deutsche Post': f'https://www.deutschepost.de/de/s/sendungsverfolgung.html?piececode={n}',
        'Hermes': f'https://www.myhermes.de/empfangen/sendungsverfolgung/sendungsinformation#{n}',
        'DPD': f'https://tracking.dpd.de/status/de_DE/parcel/{n}',
        'GLS': f'https://gls-group.com/DE/de/paketverfolgung?match={n}',
    }.get(order.carrier)


CARRIERS = ['DHL', 'Deutsche Post', 'Hermes', 'DPD', 'GLS', 'Andere']
