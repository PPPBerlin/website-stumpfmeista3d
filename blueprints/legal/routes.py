"""
Rechtsseiten — pro Schaufenster registriert (/agb und /boutique/agb …).
Inhalte kommen aus templates/legal/*.txt (eine Quelle für alle Designs + Mails).
"""
from flask import Blueprint, render_template, request, current_app, flash
from flask_mail import Message

from extensions import db, limiter
from models import Order, Withdrawal
from storefronts import current_sf, sf_context, BOUTIQUE
from blueprints.shop.services import _send_async
from blueprints.shop.routes import storefront_guard

legal_bp = Blueprint('legal', __name__)


@legal_bp.before_request
def _guard():
    # Hauptseite: Rechtsseiten immer erreichbar. Boutique: wie der Boutique-Shop.
    if current_sf() is BOUTIQUE:
        return storefront_guard()


PAGES = {
    'impressum': ('Impressum', 'Angaben gemäß § 5 DDG', ['legal/impressum.txt']),
    'datenschutz': ('Datenschutzerklärung', 'Gemäß Art. 13, 14 DSGVO', ['legal/datenschutz.txt']),
    'agb': ('Allgemeine Geschäftsbedingungen', 'AGB für den Online-Shop', ['legal/agb.txt']),
    'widerruf': ('Widerrufsbelehrung', 'Für Verbraucher',
                 ['legal/widerruf.txt', 'legal/widerrufsformular.txt']),
    'versand': ('Versand & Zahlung', 'Alles zu Lieferung und Bezahlung', ['legal/versand.txt']),
}


def _page_template():
    return 'boutique/legal.html' if current_sf() is BOUTIQUE else 'legal/page.html'


def _render_page(key):
    title, subtitle, sources = PAGES[key]
    return render_template(_page_template(), page_key=key, title=title, subtitle=subtitle,
                           sources=sources, show_withdrawal_button=(key == 'widerruf'))


@legal_bp.route('/impressum')
def impressum():
    return _render_page('impressum')


@legal_bp.route('/datenschutz')
def datenschutz():
    return _render_page('datenschutz')


@legal_bp.route('/agb')
def agb():
    return _render_page('agb')


@legal_bp.route('/widerruf')
def widerruf():
    return _render_page('widerruf')


@legal_bp.route('/versand')
def versand():
    return _render_page('versand')


# ---------------------------------------------------------------------------
# Elektronische Widerrufsfunktion (Art. 11a RL 2011/83/EU, seit 19.06.2026)
# Schritt 1: Erklärung ausfüllen → Schritt 2: „Widerruf bestätigen"
# → Eingangsbestätigung per E-Mail (dauerhafter Datenträger)
# ---------------------------------------------------------------------------
def _withdraw_template():
    return 'boutique/withdraw.html' if current_sf() is BOUTIQUE else 'legal/withdraw.html'


@legal_bp.route('/vertrag-widerrufen', methods=['GET', 'POST'])
@limiter.limit('10 per hour', methods=['POST'])
def withdraw():
    form = {k: request.form.get(k, '').strip()
            for k in ('name', 'email', 'order_number', 'message')}
    if request.method == 'GET':
        form['order_number'] = request.args.get('bestellung', '')
        return render_template(_withdraw_template(), step='form', form=form)

    missing = [k for k in ('name', 'email', 'order_number') if not form[k]]
    if missing or '@' not in form['email']:
        flash('Bitte Name, E-Mail-Adresse und Bestellnummer angeben.', 'error')
        return render_template(_withdraw_template(), step='form', form=form)

    if request.form.get('step') != 'confirm':
        return render_template(_withdraw_template(), step='review', form=form)

    # Bestellung zuordnen, wenn Nummer und E-Mail zusammenpassen
    number = form['order_number'].lstrip('#').strip()
    order = Order.query.filter_by(number=number).first()
    if order and (order.email or '').lower() != form['email'].lower():
        order = None

    w = Withdrawal(name=form['name'], email=form['email'].lower(),
                   order_number=form['order_number'], message=form['message'] or None,
                   order=order, storefront=current_sf().key)
    db.session.add(w)
    db.session.commit()

    _send_withdrawal_mails(w)
    return render_template(_withdraw_template(), step='done', withdrawal=w)


def _send_withdrawal_mails(w):
    from legal_format import berlin
    sf = current_sf()
    received = berlin(w.created_at, '%d.%m.%Y um %H:%M Uhr')
    body = render_template('emails/withdrawal_receipt.txt', w=w, received=received,
                           **sf_context(sf))
    msg = Message(subject=f'Eingangsbestätigung deines Widerrufs (Bestellung {w.order_number})',
                  recipients=[w.email], body=body)
    admin = current_app.config.get('ADMIN_EMAIL')
    if admin:
        msg.reply_to = admin
        _send_async(Message(
            subject=f'[{sf.name}] WIDERRUF zu Bestellung {w.order_number}',
            recipients=[admin],
            body=(f'Widerruf eingegangen am {received}\n\n'
                  f'Name: {w.name}\nE-Mail: {w.email}\nBestellnummer: {w.order_number}\n'
                  f'Zugeordnet: {"ja" if w.order else "NEIN – bitte manuell prüfen"}\n\n'
                  f'{w.message or ""}'),
        ))
    _send_async(msg)
