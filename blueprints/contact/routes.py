import os
import uuid
from flask import (Blueprint, request, jsonify, current_app, flash,
                   redirect, url_for)
from werkzeug.utils import secure_filename
from extensions import db, limiter
from models import Inquiry, InquiryFile, Customer

contact_bp = Blueprint('contact', __name__)

ALLOWED_EXTENSIONS = {'stl', '3mf', 'pdf', 'jpg', 'jpeg', 'png'}


def _allowed_file(filename):
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS)


def _save_file(file_obj, upload_folder):
    """Speichert eine hochgeladene Datei sicher und gibt (disk_name, original_name, size) zurück."""
    original_name = secure_filename(file_obj.filename)
    ext = original_name.rsplit('.', 1)[1].lower() if '.' in original_name else ''
    disk_name = f'{uuid.uuid4().hex}.{ext}'
    path = os.path.join(upload_folder, disk_name)
    file_obj.save(path)
    size = os.path.getsize(path)
    return disk_name, original_name, size


@contact_bp.route('/senden', methods=['POST'])
@limiter.limit('5 per hour')  # Spam-Schutz
def send():
    """Nimmt das Kontaktformular entgegen, speichert Anfrage + Uploads."""
    # --- Pflichtfelder prüfen ---
    required = ['first_name', 'last_name', 'email', 'subject', 'message']
    for field in required:
        if not request.form.get(field, '').strip():
            return jsonify({'success': False, 'error': f'Pflichtfeld fehlt: {field}'}), 400

    # --- Inquiry anlegen ---
    inquiry = Inquiry(
        first_name=request.form['first_name'].strip(),
        last_name=request.form['last_name'].strip(),
        email=request.form['email'].strip().lower(),
        phone=request.form.get('phone', '').strip() or None,
        subject=request.form['subject'].strip(),
        message=request.form['message'].strip(),
    )

    # Prüfen ob Kunde bereits existiert → verknüpfen
    existing_customer = Customer.query.filter_by(
        email=inquiry.email
    ).first()
    if existing_customer:
        inquiry.customer = existing_customer

    db.session.add(inquiry)
    db.session.flush()  # ID für File-Relation generieren

    # --- Datei-Uploads verarbeiten ---
    upload_folder = current_app.config['UPLOAD_FOLDER']
    files = request.files.getlist('files')
    errors = []

    for file_obj in files:
        if not file_obj or not file_obj.filename:
            continue
        if not _allowed_file(file_obj.filename):
            errors.append(f'Dateityp nicht erlaubt: {file_obj.filename}')
            continue
        disk_name, original_name, size = _save_file(file_obj, upload_folder)
        inquiry_file = InquiryFile(
            inquiry_id=inquiry.id,
            filename=disk_name,
            original_name=original_name,
            file_size=size,
        )
        db.session.add(inquiry_file)

    db.session.commit()

    # --- E-Mail-Benachrichtigung (optional, wenn Mail konfiguriert) ---
    _send_notification(inquiry)

    return jsonify({
        'success': True,
        'message': 'Anfrage erfolgreich gesendet!',
        'warnings': errors,
    })


def _send_notification(inquiry):
    """Sendet E-Mail im Hintergrund-Thread — blockiert Gunicorn-Worker nicht."""
    import threading
    from flask_mail import Message
    from extensions import mail

    admin_email = current_app.config.get('ADMIN_EMAIL')
    if not admin_email:
        return

    msg = Message(
        subject=f'[Stumpfmeista3D] Neue Anfrage: {inquiry.subject}',
        recipients=[admin_email],
        body=(
            f'Neue Kontaktanfrage von {inquiry.first_name} {inquiry.last_name}\n'
            f'E-Mail: {inquiry.email}\n'
            f'Telefon: {inquiry.phone or "—"}\n\n'
            f'Betreff: {inquiry.subject}\n\n'
            f'{inquiry.message}'
        ),
    )

    # App-Kontext in den Thread mitgeben
    app = current_app._get_current_object()

    def send_async():
        with app.app_context():
            try:
                mail.send(msg)
            except Exception as e:
                app.logger.error(f'Mailversand fehlgeschlagen: {e}')

    threading.Thread(target=send_async, daemon=True).start()
