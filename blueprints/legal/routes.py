from datetime import datetime

from flask import Blueprint, render_template, request, current_app, flash, redirect, url_for
from flask_mail import Message

from extensions import db, limiter
from models import Order, Withdrawal
from blueprints.shop.services import _send_async

legal_bp = Blueprint('legal', __name__)


@legal_bp.route('/agb')
def agb():
    return render_template('legal/page.html', title='Allgemeine Geschäftsbedingungen',
                           subtitle='AGB für den Online-Shop', sources=['legal/agb.txt'])


@legal_bp.route('/widerruf')
def widerruf():
    return render_template('legal/page.html', title='Widerrufsbelehrung',
                           subtitle='Für Verbraucher',
                           sources=['legal/widerruf.txt', 'legal/widerrufsformular.txt'],
                           show_withdrawal_button=True)


@legal_bp.route('/versand')
def versand():
    return render_template('legal/versand.html')


# ---------------------------------------------------------------------------
# Elektronische Widerrufsfunktion (Art. 11a RL 2011/83/EU, seit 19.06.2026)
# Schritt 1: Erklärung ausfüllen → Schritt 2: „Widerruf bestätigen"
# → Eingangsbestätigung per E-Mail (dauerhafter Datenträger)
# ---------------------------------------------------------------------------
@legal_bp.route('/vertrag-widerrufen', methods=['GET', 'POST'])
@limiter.limit('10 per hour', methods=['POST'])
def withdraw():
    form = {k: request.form.get(k, '').strip()
            for k in ('name', 'email', 'order_number', 'message')}
    if request.method == 'GET':
        form['order_number'] = request.args.get('bestellung', '')
        return render_template('legal/withdraw.html', step='form', form=form)

    missing = [k for k in ('name', 'email', 'order_number') if not form[k]]
    if missing or '@' not in form['email']:
        flash('Bitte Name, E-Mail-Adresse und Bestellnummer angeben.', 'error')
        return render_template('legal/withdraw.html', step='form', form=form)

    if request.form.get('step') != 'confirm':
        return render_template('legal/withdraw.html', step='review', form=form)

    # Bestellung zuordnen, wenn Nummer und E-Mail zusammenpassen
    number = form['order_number'].lstrip('#').strip()
    order = Order.query.filter_by(number=number).first()
    if order and (order.email or '').lower() != form['email'].lower():
        order = None

    w = Withdrawal(name=form['name'], email=form['email'].lower(),
                   order_number=form['order_number'], message=form['message'] or None,
                   order=order)
    db.session.add(w)
    db.session.commit()

    _send_withdrawal_mails(w)
    return render_template('legal/withdraw.html', step='done', withdrawal=w)


def _send_withdrawal_mails(w):
    from legal_format import berlin
    received = berlin(w.created_at, '%d.%m.%Y um %H:%M Uhr')
    body = render_template('emails/withdrawal_receipt.txt', w=w, received=received)
    msg = Message(subject=f'Eingangsbestätigung deines Widerrufs (Bestellung {w.order_number})',
                  recipients=[w.email], body=body)
    admin = current_app.config.get('ADMIN_EMAIL')
    if admin:
        msg.reply_to = admin
        _send_async(Message(
            subject=f'[Stumpfmeista3D] WIDERRUF zu Bestellung {w.order_number}',
            recipients=[admin],
            body=(f'Widerruf eingegangen am {received}\n\n'
                  f'Name: {w.name}\nE-Mail: {w.email}\nBestellnummer: {w.order_number}\n'
                  f'Zugeordnet: {"ja" if w.order else "NEIN – bitte manuell prüfen"}\n\n'
                  f'{w.message or ""}'),
        ))
    _send_async(msg)
