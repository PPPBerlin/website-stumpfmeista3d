"""
End-to-End-Test des Shops mit gemocktem Stripe (kein Netzwerk nötig).
Ausführen:  python tests/shop_e2e.py
"""
import io
import os
import re
import sys
import tempfile
from types import SimpleNamespace as NS
from unittest import mock

tmp = tempfile.mkdtemp()
os.environ.update(
    SECRET_KEY='t', DATABASE_URL=f'sqlite:///{tmp}/t.db', SHOP_ENABLED='true',
    STRIPE_SECRET_KEY='sk_test_x', STRIPE_WEBHOOK_SECRET='whsec_x',
    SITE_URL='https://stumpfmeista3d.org', ADMIN_EMAIL='admin@example.org',
    MAIL_DEFAULT_SENDER='shop@example.org', SHOP_FREE_SHIPPING_FROM_CENTS='5000',
    BOUTIQUE_ENABLED='true',
)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stripe  # noqa: E402
from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from models import (AdminUser, DiscountCode, Order, Product, ProductVariant, Withdrawal)  # noqa: E402
import blueprints.shop.services as svc  # noqa: E402
import blueprints.legal.routes as legal_routes  # noqa: E402

app = create_app()
app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False, TESTING=True,
                  UPLOAD_FOLDER=tmp)
os.makedirs(f'{tmp}/products', exist_ok=True)

sent = []
svc._send_async = sent.append
legal_routes._send_async = sent.append


class Obj(dict):
    __getattr__ = dict.__getitem__


def ok(resp, code=200):
    assert resp.status_code == code, (resp.status_code, resp.get_data(as_text=True)[:1500])
    return resp.get_data(as_text=True)


def stocks():
    with app.app_context():
        return [v.stock for v in ProductVariant.query.order_by(ProductVariant.id)]


def paid_session(sid, status='complete', payment_status='paid'):
    return Obj({
        'id': sid, 'status': status, 'payment_status': payment_status, 'payment_intent': 'pi_123',
        'customer_details': {'email': 'kunde@example.org', 'name': 'Max Muster', 'phone': None},
        'collected_information': {'shipping_details': {'name': 'Max Muster', 'address': {
            'line1': 'Hauptstr. 1', 'line2': None, 'postal_code': '10115',
            'city': 'Berlin', 'country': 'DE'}}},
    })


def webhook(client, etype, sid, session_obj):
    event = {'type': etype, 'data': {'object': {'id': sid}}}
    with mock.patch('stripe.Webhook.construct_event', return_value=event), \
         mock.patch('stripe.checkout.Session.retrieve', return_value=session_obj):
        return ok(client.post('/shop/webhook/stripe', data='{}',
                              headers={'Stripe-Signature': 'x'}))


def main():
    c = app.test_client()
    with app.app_context():
        db.create_all()
        u = AdminUser(username='a')
        u.set_password('p')
        db.session.add(u)
        db.session.commit()

    for p in ['/', '/impressum', '/datenschutz', '/agb', '/widerruf', '/versand',
              '/vertrag-widerrufen', '/shop', '/warenkorb', '/sitemap.xml', '/robots.txt']:
        ok(c.get(p))
    html = ok(c.get('/impressum'))
    assert '§ 5 DDG' in html and 'ec.europa.eu' not in html
    print('OK öffentliche Seiten')

    # --- Admin: Produkt anlegen -------------------------------------------
    ok(c.post('/admin/login', data={'username': 'a', 'password': 'p'}), 302)
    png = b'\x89PNG\r\n\x1a\n' + b'0' * 100
    ok(c.post('/admin/produkte/neu', data={
        'name': 'Kabelhalter Öko', 'short_description': 'Hält Kabel', 'price': '12,90',
        'is_active': '1', 'show_in_main': '1', 'variant_label': 'Farbe', 'material': 'PETG',
        'safety_info': 'Kein Spielzeug.',
        'variants-0-name': 'Schwarz', 'variants-0-stock': '2', 'variants-0-active': '1',
        'variants-0-sku': 'KH-SW',
        'variants-1-name': 'Neongrün', 'variants-1-price': '14,50', 'variants-1-stock': '1',
        'variants-1-active': '1',
        'images': (io.BytesIO(png), 'a.png')}, content_type='multipart/form-data'), 302)
    assert 'Ungültiger Preis' in ok(c.post('/admin/produkte/neu', data={
        'name': 'X', 'price': 'abc', 'variants-0-name': 'S'}, follow_redirects=True))
    html = ok(c.post('/admin/produkte/1/bearbeiten', data={
        'name': 'Kabelhalter Öko', 'price': '12,90', 'is_active': '1', 'show_in_main': '1',
        'material': 'PETG',
        'safety_info': 'Kein Spielzeug.',
        'variants-0-id': '1', 'variants-0-name': 'Schwarz', 'variants-0-stock': '2',
        'variants-0-active': '1', 'variants-0-sku': 'KH-SW',
        'variants-1-id': '2', 'variants-1-name': 'Neongrün', 'variants-1-price': '14,50',
        'variants-1-stock': '1', 'variants-1-active': '1',
        'images': (io.BytesIO(b'<?php'), 'evil.jpg')},
        content_type='multipart/form-data', follow_redirects=True))
    assert 'Keine gültige Bilddatei' in html
    for p in ['/admin/', '/admin/produkte', '/admin/produkte/1/bearbeiten',
              '/admin/bestellungen', '/admin/produkte/neu']:
        ok(c.get(p))
    with app.app_context():
        p = Product.query.one()
        assert p.slug == 'kabelhalter-oeko' and p.price_cents == 1290 and len(p.images) == 1
        assert [v.effective_price_cents for v in p.variants] == [1290, 1450]
    c.get('/admin/logout')
    print('OK Admin Produktpflege + Validierung')

    # --- Produktseite (PAngV + GPSR) ----------------------------------------
    html = ok(c.get('/shop/kabelhalter-oeko'))
    assert '12,90 €' in html and 'Neongrün' in html and 'AggregateOffer' in html
    assert 'Versandkosten' in html and '§ 19 UStG' in html
    assert 'Wolfsgartenstraße 6' in html and 'data-sku="KH-SW"' in html and 'Kein Spielzeug.' in html
    assert 'data-stock' not in html and 'Nur noch' not in html and 'max="10"' in html
    print('OK Produktseite: Preisangabe, JSON-LD, GPSR, kein Bestand sichtbar')

    # --- Warenkorb + Bestellübersicht ---------------------------------------
    ok(c.post('/warenkorb/hinzufuegen', data={'variant_id': 1, 'qty': 5}), 302)
    ok(c.post('/warenkorb/hinzufuegen', data={'variant_id': 2, 'qty': 1}), 302)
    html = ok(c.get('/warenkorb'))
    assert '40,30 €' in html and '4,95 €' in html and '45,25 €' in html, re.findall(r'[\d.,]+ €', html)
    html = ok(c.get('/kasse'))
    assert 'Zahlungspflichtig bestellen' in html and '45,25 €' in html and 'Lieferzeit' in html
    print('OK Warenkorb (Mengen gedeckelt) + Bestellübersicht mit Bestell-Button')

    # --- Checkout reserviert Bestand -----------------------------------------
    created = {}

    def fake_create(**kw):
        created.update(kw)
        return NS(id='cs_test_1', url='https://checkout.stripe.com/c/pay/cs_test_1')

    with mock.patch('stripe.checkout.Session.create', side_effect=fake_create):
        r = c.post('/kasse')
        ok(r, 303)
    assert r.headers['Location'].startswith('https://checkout.stripe.com')
    assert created['line_items'][0]['price_data']['unit_amount'] == 1290
    assert created['shipping_options'][0]['shipping_rate_data']['fixed_amount']['amount'] == 495
    assert created['shipping_address_collection'] == {'allowed_countries': ['DE']}
    assert stocks() == [0, 0]
    c2 = app.test_client()
    ok(c2.post('/warenkorb/hinzufuegen', data={'variant_id': 1, 'qty': 1}), 302)
    assert 'Warenkorb ist leer' in ok(c2.get('/warenkorb'))
    print('OK Checkout reserviert Bestand, andere Kunden sehen ausverkauft')

    with mock.patch('stripe.checkout.Session.expire') as exp:
        ok(c.get('/kasse/abgebrochen'), 302)
        exp.assert_called_once()
    assert stocks() == [2, 1]
    print('OK Abbruch gibt Bestand frei')

    # --- Bezahlen via Webhook --------------------------------------------------
    with mock.patch('stripe.checkout.Session.create', return_value=NS(id='cs_test_2', url='https://x')):
        ok(c.post('/kasse'), 303)
    webhook(c, 'checkout.session.completed', 'cs_test_2', paid_session('cs_test_2'))
    webhook(c, 'checkout.session.completed', 'cs_test_2', paid_session('cs_test_2'))  # doppelt
    with mock.patch('stripe.checkout.Session.retrieve', return_value=paid_session('cs_test_2')):
        assert 'Danke für deine Bestellung' in ok(c.get('/kasse/danke?session_id=cs_test_2'))
    with app.app_context():
        o = Order.query.filter_by(stripe_session_id='cs_test_2').one()
        assert o.status == 'Bezahlt' and o.city == 'Berlin' and not o.stock_reserved
        num, oid = o.number, o.id
    assert stocks() == [0, 0]
    assert len(sent) == 2, [m.subject for m in sent]
    conf = sent[0].body
    for needle in ('WIDERRUFSBELEHRUNG', 'MUSTER-WIDERRUFSFORMULAR', 'ALLGEMEINE GESCHÄFTSBEDINGUNGEN',
                   'Hauptstr. 1', '45,25 €', 'Kaufvertrag ist damit geschlossen',
                   'Zahlungspflichtig bestellen'):
        assert needle in conf, needle
    assert 'leer' in ok(c.get('/warenkorb'))
    print('OK Webhook bezahlt genau einmal, Bestätigung mit AGB + Widerruf')

    with mock.patch('stripe.Webhook.construct_event',
                    side_effect=stripe.SignatureVerificationError('x', 'y')):
        ok(c.post('/shop/webhook/stripe', data='{}'), 400)
    print('OK falsche Webhook-Signatur → 400')

    # --- SEPA: Zahlung scheitert nachträglich -------------------------------------
    c3 = app.test_client()
    with app.app_context():
        ProductVariant.query.get(2).stock = 1
        db.session.commit()
    ok(c3.post('/warenkorb/hinzufuegen', data={'variant_id': 2, 'qty': 1}), 302)
    with mock.patch('stripe.checkout.Session.create', return_value=NS(id='cs_test_3', url='https://x')):
        ok(c3.post('/kasse'), 303)
    pending = paid_session('cs_test_3', payment_status='unpaid')
    webhook(c3, 'checkout.session.completed', 'cs_test_3', pending)
    with app.app_context():
        assert Order.query.filter_by(stripe_session_id='cs_test_3').one().status == 'Offen'
    n_before = len(sent)
    webhook(c3, 'checkout.session.async_payment_failed', 'cs_test_3', pending)
    with app.app_context():
        assert Order.query.filter_by(stripe_session_id='cs_test_3').one().status == 'Abgebrochen'
    assert stocks()[1] == 1 and len(sent) == n_before + 1 and 'fehlgeschlagen' in sent[-1].subject
    print('OK SEPA fehlgeschlagen → storniert, Bestand zurück, Kunde informiert')

    # --- Widerrufsfunktion ------------------------------------------------------
    html = ok(c.post('/vertrag-widerrufen', data={
        'name': 'Max Muster', 'email': 'kunde@example.org', 'order_number': num}))
    assert 'Widerruf bestätigen' in html
    html = ok(c.post('/vertrag-widerrufen', data={
        'name': 'Max Muster', 'email': 'KUNDE@example.org', 'order_number': num, 'step': 'confirm'}))
    assert 'Dein Widerruf ist eingegangen' in html and 'UTC' not in html
    with app.app_context():
        assert Withdrawal.query.one().order_id == oid
    receipt = [m for m in sent if 'Eingangsbestätigung' in m.subject]
    assert receipt and 'UTC' not in receipt[0].body and any('WIDERRUF' in m.subject for m in sent)
    print('OK Widerruf zweistufig, zugeordnet, Eingangsbestätigung (deutsche Zeit)')

    # --- Admin: Versand + Storno --------------------------------------------------
    ok(c.post('/admin/login', data={'username': 'a', 'password': 'p'}), 302)
    assert 'Widerruf eingegangen' in ok(c.get(f'/admin/bestellungen/{oid}'))
    assert 'Offene Widerrufe' in ok(c.get('/admin/bestellungen'))
    ok(c.post(f'/admin/bestellungen/{oid}/versendet',
              data={'carrier': 'DHL', 'tracking_number': '00340434', 'notify': '1'}), 302)
    assert 'piececode=00340434' in sent[-1].body
    ok(c.post(f'/admin/bestellungen/{oid}/stornieren', data={'restock': '1', 'confirm': 'on'}), 302)
    with app.app_context():
        assert Order.query.get(oid).status == 'Storniert'
    assert stocks() == [2, 2]
    ok(c.post('/admin/produkte/1/loeschen'), 302)
    with app.app_context():
        assert Product.query.get(1).is_active is False
    print('OK Versandmail mit Tracking, Storno mit Rückbuchung, Löschen → deaktivieren')
    boutique(c)


def boutique(admin_client):
    """Zweites Schaufenster: eigene Produktauswahl, eigener Warenkorb, eigenes Branding."""
    ok(admin_client.post('/admin/produkte/neu', data={
        'name': 'Nippel-Pasties Glitzer', 'price': '24,00', 'is_active': '1',
        'show_in_boutique': '1', 'variant_label': 'Farbe',
        'variants-0-name': 'Rosé', 'variants-0-stock': '3', 'variants-0-active': '1'}), 302)
    assert 'Aktives Produkt: bitte mindestens einen Shop' in ok(admin_client.post(
        '/admin/produkte/neu', data={'name': 'Ohne Shop', 'price': '1', 'is_active': '1',
                                    'variants-0-name': 'S', 'variants-0-active': '1'},
        follow_redirects=True))
    assert 'Boutique' in ok(admin_client.get('/admin/produkte'))
    with app.app_context():
        bp = Product.query.filter_by(slug='nippel-pasties-glitzer').one()
        bvid = bp.variants[0].id
    admin_client.get('/admin/logout')

    c = app.test_client()
    for p in ['/boutique/', '/boutique/warenkorb', '/boutique/agb', '/boutique/widerruf',
              '/boutique/versand', '/boutique/impressum', '/boutique/datenschutz',
              '/boutique/vertrag-widerrufen']:
        assert 'Boutique' in ok(c.get(p)), p
    html = ok(c.get('/boutique/'))
    assert 'Nippel-Pasties Glitzer' in html and 'Kabelhalter' not in html
    assert 'Nippel-Pasties' not in ok(c.get('/shop'))
    assert c.get('/shop/nippel-pasties-glitzer').status_code == 404
    assert c.get('/boutique/shop').status_code == 301
    html = ok(c.get('/boutique/shop/nippel-pasties-glitzer'))
    assert '24,00 €' in html and 'Wolfsgartenstraße 6' in html and 'href="/boutique/agb"' in html
    assert 'href="/boutique/versand"' in html and 'href="/boutique/vertrag-widerrufen"' in html
    imp = ok(c.get('/boutique/impressum'))
    assert '§ 5 DDG' in imp and 'ec.europa.eu' not in imp
    print('OK Boutique: eigene Produktauswahl, eigene Rechtsseiten')

    # Boutique-Produkt kann nicht in den Hauptshop-Warenkorb
    ok(c.post('/warenkorb/hinzufuegen', data={'variant_id': bvid, 'qty': 1}), 302)
    assert 'Warenkorb ist leer' in ok(c.get('/warenkorb'))
    ok(c.post('/boutique/warenkorb/hinzufuegen', data={'variant_id': bvid, 'qty': 2}), 302)
    assert '48,00 €' in ok(c.get('/boutique/warenkorb'))
    assert 'Warenkorb ist leer' in ok(c.get('/warenkorb'))
    assert 'Zahlungspflichtig bestellen' in ok(c.get('/boutique/kasse'))
    print('OK getrennte Warenkörbe')

    created = {}
    with mock.patch('stripe.checkout.Session.create',
                    side_effect=lambda **kw: created.update(kw) or NS(id='cs_b_1', url='https://x')):
        ok(c.post('/boutique/kasse'), 303)
    assert created['success_url'].startswith('https://stumpfmeista3d.org/boutique/kasse/danke')
    assert '/boutique/agb' in created['custom_text']['submit']['message']
    n = len(sent)
    webhook(c, 'checkout.session.completed', 'cs_b_1', paid_session('cs_b_1'))
    with app.app_context():
        o = Order.query.filter_by(stripe_session_id='cs_b_1').one()
        assert o.storefront == 'boutique' and o.status == 'Bezahlt'
    conf = sent[n]
    assert 'Stumpfmeista3D Boutique' in conf.subject
    assert 'Paul – Stumpfmeista3D Boutique' in conf.body and '/boutique/vertrag-widerrufen' in conf.body
    assert 'https://stumpfmeista3d.org/boutique/agb' in conf.body
    print('OK Boutique-Bestellung: Herkunft gespeichert, Mails im Boutique-Branding')

    # --- Eigene Domain ---------------------------------------------------------
    app.config['BOUTIQUE_DOMAIN'] = 'boutique.example.de'
    d = app.test_client()
    html = ok(d.get('/', headers={'Host': 'boutique.example.de'}))
    assert 'Nippel-Pasties Glitzer' in html and 'href="/boutique' not in html
    assert 'href="/agb"' in html and 'href="/shop/nippel-pasties-glitzer"' in html
    ok(d.get('/shop/nippel-pasties-glitzer', headers={'Host': 'boutique.example.de'}))
    ok(d.get('/static/css/input.css', headers={'Host': 'boutique.example.de'}))
    r = d.get('/boutique/agb')  # Hauptdomain
    assert r.status_code == 301 and r.headers['Location'] == 'https://boutique.example.de/agb'
    assert 'Stumpfmeista3D' in ok(d.get('/'))  # Hauptseite unverändert
    ok(d.post('/warenkorb/hinzufuegen', data={'variant_id': bvid, 'qty': 1},
              headers={'Host': 'boutique.example.de'}), 302)
    with mock.patch('stripe.checkout.Session.create',
                    side_effect=lambda **kw: created.update(kw) or NS(id='cs_b_2', url='https://x')):
        ok(d.post('/kasse', headers={'Host': 'boutique.example.de'}), 303)
    assert created['success_url'].startswith('https://boutique.example.de/kasse/danke')
    app.config['BOUTIQUE_DOMAIN'] = ''
    print('OK eigene Domain: Routing, Links, 301 von /boutique, Stripe-URLs')


def discounts_and_made_to_order():
    """Fertigung auf Bestellung (kein Bestand, Lieferzeit-Zuschlag) + Rabattcodes."""
    from datetime import date, timedelta
    a = app.test_client()
    ok(a.post('/admin/login', data={'username': 'a', 'password': 'p'}), 302)
    ok(a.post('/admin/produkte/neu', data={
        'name': 'Anhänger Druck', 'price': '3,00', 'is_active': '1', 'show_in_main': '1',
        'show_in_boutique': '1', 'delivery_time': '4–6 Werktage',
        'made_to_order': '1', 'extra_day_per_units': '10',
        'variants-0-name': 'Rot', 'variants-0-stock': '0', 'variants-0-active': '1',
        'variants-1-name': 'Blau', 'variants-1-stock': '0', 'variants-1-active': '1'}), 302)
    assert 'ganze Zahl ab 1' in ok(a.post('/admin/produkte/neu', data={
        'name': 'Y', 'price': '1', 'made_to_order': '1', 'extra_day_per_units': '0',
        'variants-0-name': 'S'}, follow_redirects=True))
    with app.app_context():
        mp = Product.query.filter_by(slug='anhaenger-druck').one()
        rot, blau = [v.id for v in mp.variants]
        assert mp.made_to_order and mp.extra_day_per_units == 10 and not mp.is_sold_out
    assert 'auf Bestellung' in ok(a.get('/admin/produkte'))

    # --- Rabattcodes anlegen ---
    yesterday = (date.today() - timedelta(days=2)).isoformat()
    for data in (
        {'code': 'stamm20', 'note': 'Stammkundin', 'kind': 'percent', 'value': '20',
         'storefront': 'all', 'is_active': '1', 'max_uses': '1'},
        {'code': 'ALT10', 'kind': 'percent', 'value': '10', 'storefront': 'all',
         'is_active': '1', 'valid_until': yesterday},
        {'code': 'NURBOUTIQUE', 'kind': 'fixed', 'value': '5,00', 'storefront': 'boutique',
         'is_active': '1'},
        {'code': 'VERSANDFREI', 'kind': 'fixed', 'value': '', 'free_shipping': '1',
         'storefront': 'all', 'is_active': '1', 'min_order': '30,00'},
    ):
        ok(a.post('/admin/rabattcodes/neu', data=data), 302)
    assert 'gibt es schon' in ok(a.post('/admin/rabattcodes/neu', data={
        'code': 'Stamm20', 'kind': 'percent', 'value': '5'}, follow_redirects=True))
    assert 'von 0 bis 100' in ok(a.post('/admin/rabattcodes/neu', data={
        'code': 'ZUVIEL', 'kind': 'percent', 'value': '150'}, follow_redirects=True))
    html = ok(a.get('/admin/rabattcodes'))
    assert 'STAMM20' in html and 'Abgelaufen' in html and 'versandkostenfrei' in html
    with app.app_context():
        stamm_id = DiscountCode.query.filter_by(code='STAMM20').one().id
    ok(a.get('/admin/rabattcodes/neu'))
    ok(a.get(f'/admin/rabattcodes/{stamm_id}/bearbeiten'))
    a.get('/admin/logout')
    print('OK Admin: Fertigungsartikel + Rabattcodes anlegen/validieren')

    # --- Kunde: Fertigungsartikel ---
    c = app.test_client()
    html = ok(c.get('/shop/anhaenger-druck'))
    assert 'für dich gefertigt' in html and 'MadeToOrder' in html and 'Ab 10 Stück' in html
    assert 'max="50"' in html and 'Leider ausverkauft' not in html
    ok(c.post('/warenkorb/hinzufuegen', data={'variant_id': rot, 'qty': 7}), 302)
    ok(c.post('/warenkorb/hinzufuegen', data={'variant_id': blau, 'qty': 5}), 302)
    html = ok(c.get('/warenkorb'))
    assert '36,00 €' in html and '4–6 Werktage + 1 Werktag Fertigung' in html, html[:200]
    print('OK Fertigung auf Bestellung: ohne Bestand bestellbar, +1 Werktag ab 10 Stück')

    # --- Rabattcodes einlösen ---
    def apply(client, code, prefix=''):
        return ok(client.post(f'{prefix}/warenkorb/rabattcode', data={'code': code},
                              follow_redirects=True))
    assert 'nicht gültig' in apply(c, 'GIBTSNICHT')
    assert 'abgelaufen' in apply(c, 'alt10')
    assert 'nicht gültig' in apply(c, 'NURBOUTIQUE')
    html = apply(c, ' stamm20 ')
    assert 'STAMM20 eingelöst' in html and '−7,20 €' in html and '33,75 €' in html, \
        re.findall(r'[−\d.,]+ €', html)
    html = ok(c.get('/kasse'))
    assert '−7,20 €' in html and 'value="3375"' in html

    # Preis ändert sich zwischen Übersicht und Klick → zurück zur Übersicht
    r = c.post('/kasse', data={'expected_total': '9999'})
    assert r.status_code == 302 and r.headers['Location'].endswith('/kasse')

    created, coupons = {}, []
    with mock.patch('stripe.Coupon.create',
                    side_effect=lambda **kw: coupons.append(kw) or NS(id='co_1')), \
         mock.patch('stripe.checkout.Session.create',
                    side_effect=lambda **kw: created.update(kw) or NS(id='cs_d_1', url='https://x')):
        ok(c.post('/kasse', data={'expected_total': '3375'}), 303)
    assert coupons[0]['amount_off'] == 720 and coupons[0]['max_redemptions'] == 1
    assert created['discounts'] == [{'coupon': 'co_1'}]
    with app.app_context():
        o = Order.query.filter_by(stripe_session_id='cs_d_1').one()
        assert (o.subtotal_cents, o.discount_cents, o.shipping_cents, o.total_cents) == \
            (3600, 720, 495, 3375)
        assert o.discount_code == 'STAMM20' and all(i.made_to_order for i in o.items)
        assert o.items[0].delivery_time == '4–6 Werktage + 1 Werktag Fertigung'
        assert [v.stock for v in Product.query.filter_by(slug='anhaenger-druck').one().variants] == [0, 0]
    n = len(sent)
    paid = paid_session('cs_d_1')
    paid['amount_total'] = 3375
    webhook(c, 'checkout.session.completed', 'cs_d_1', paid)
    conf = sent[n].body
    assert 'Rabatt (STAMM20)  —  −7,20 €' in conf and '33,75 €' in conf
    assert 'Lieferzeit: 4–6 Werktage + 1 Werktag Fertigung (Fertigung nach Bestellung)' in conf
    with app.app_context():
        o = Order.query.filter_by(stripe_session_id='cs_d_1').one()
        assert o.status == 'Bezahlt' and not o.notes
        oid = o.id
    print('OK Rabattcode: Prüfung, Anzeige, Stripe-Gutschein, Preisschutz, Bestätigungsmail')

    # max_uses=1 → zweiter Kunde bekommt ihn nicht mehr
    c2 = app.test_client()
    ok(c2.post('/warenkorb/hinzufuegen', data={'variant_id': rot, 'qty': 1}), 302)
    assert 'bereits eingelöst' in apply(c2, 'STAMM20')
    # Mindestbestellwert + versandkostenfrei
    assert 'ab einem Bestellwert von 30,00 €' in apply(c2, 'VERSANDFREI')
    ok(c2.post('/warenkorb/hinzufuegen', data={'variant_id': rot, 'qty': 9}), 302)
    html = ok(c2.get('/warenkorb'))
    created = {}
    assert 'VERSANDFREI' in html and 'kostenlos' in html and '30,00 €' in html
    with mock.patch('stripe.checkout.Session.create',
                    side_effect=lambda **kw: created.update(kw) or NS(id='cs_d_2', url='https://x')):
        ok(c2.post('/kasse'), 303)
    assert 'discounts' not in created
    rate = created['shipping_options'][0]['shipping_rate_data']
    assert rate['fixed_amount']['amount'] == 0 and 'VERSANDFREI' in rate['display_name']
    # Boutique-Code in der Boutique
    b = app.test_client()
    ok(b.post('/boutique/warenkorb/hinzufuegen', data={'variant_id': rot, 'qty': 2}), 302)
    html = apply(b, 'nurboutique', '/boutique')
    assert 'NURBOUTIQUE eingelöst' in html and '−5,00 €' in html and '5,95 €' in html
    # Stripe-Mindestbetrag 0,50 €: Rabatt größer als Warenwert wird gedeckelt
    with app.app_context():
        db.session.add(DiscountCode(code='ALLES', kind='percent', value=100, free_shipping=True))
        db.session.commit()
    html = apply(b, 'ALLES', '/boutique')
    assert '−5,50 €' in html and '0,50 €' in html
    print('OK Rabattcode: Einlöselimit, Mindestbestellwert, versandkostenfrei, Shop-Bindung')

    # Admin: Bestellung zeigt Rabatt + Fertigung; benutzter Code wird nur deaktiviert
    ok(a.post('/admin/login', data={'username': 'a', 'password': 'p'}), 302)
    html = ok(a.get(f'/admin/bestellungen/{oid}'))
    assert 'STAMM20' in html and 'fertigen' in html and '−7,20 €' in html
    assert 'Eingelöst in 1 Bestellung' in ok(a.get(f'/admin/rabattcodes/{stamm_id}/bearbeiten'))
    assert 'nicht mehr umbenannt' in ok(a.post(f'/admin/rabattcodes/{stamm_id}/bearbeiten', data={
        'code': 'NEU', 'kind': 'percent', 'value': '20'}, follow_redirects=True))
    ok(a.post(f'/admin/bestellungen/{oid}/stornieren', data={'restock': '1'}), 302)
    with app.app_context():
        assert [v.stock for v in Product.query.filter_by(slug='anhaenger-druck').one().variants] == [0, 0]
    ok(a.post(f'/admin/rabattcodes/{stamm_id}/loeschen'), 302)
    with app.app_context():
        assert DiscountCode.query.get(stamm_id).is_active is False
    print('OK Admin: Rabatt + Fertigung in Bestellung, Storno ohne Bestandsbuchung')


def disabled_mode():
    """SHOP_ENABLED=false: Shop 404, Rechtstexte erreichbar."""
    app.config['SHOP_ENABLED'] = False
    c = app.test_client()
    for p in ['/shop', '/warenkorb', '/kasse']:
        assert c.get(p).status_code == 404, p
    assert c.get('/agb').status_code == 200 and c.get('/vertrag-widerrufen').status_code == 200
    assert 'href="/shop"' not in c.get('/').get_data(as_text=True)
    app.config['BOUTIQUE_ENABLED'] = False
    assert c.get('/boutique/').status_code == 404 and c.get('/boutique/agb').status_code == 404
    app.config['SHOP_ENABLED'] = True
    app.config['BOUTIQUE_ENABLED'] = True
    print('OK SHOP_ENABLED/BOUTIQUE_ENABLED=false verstecken die Shops')


if __name__ == '__main__':
    main()
    discounts_and_made_to_order()
    disabled_mode()
    print('\nALLE SHOP-TESTS GRÜN')
