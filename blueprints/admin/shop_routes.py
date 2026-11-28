"""Admin: Produkte, Bestellungen, Rabattcodes, Widerrufe."""
import itertools
import os
import re
import uuid
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from flask import render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required
from sqlalchemy import update

from extensions import db
from models import (Product, ProductVariant, ProductImage, ProductOption, ProductOptionValue,
                    Order, OrderItem,
                    Withdrawal, DiscountCode, DISCOUNT_KINDS, ORDER_STATUSES)
from blueprints.shop import services as svc
from .routes import admin_bp


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def parse_euro(value):
    """'12,90' / '12.90' / '12' → 1290; leer → None."""
    value = (value or '').strip().replace('€', '').replace(' ', '')
    if not value:
        return None
    if ',' in value:
        value = value.replace('.', '').replace(',', '.')
    try:
        cents = int((Decimal(value) * 100).quantize(Decimal('1')))
    except InvalidOperation:
        raise ValueError(f'Ungültiger Preis: {value}')
    if cents < 0:
        raise ValueError('Preis darf nicht negativ sein.')
    return cents


def cents_to_input(cents):
    if cents is None:
        return ''
    return f'{cents / 100:.2f}'.replace('.', ',')


def slugify(text):
    text = text.lower()
    for a, b in (('ä', 'ae'), ('ö', 'oe'), ('ü', 'ue'), ('ß', 'ss')):
        text = text.replace(a, b)
    text = re.sub(r'[^a-z0-9]+', '-', text).strip('-')
    return text or 'produkt'


def unique_slug(base, product_id=None):
    slug, i = base, 2
    while True:
        existing = Product.query.filter_by(slug=slug).first()
        if not existing or existing.id == product_id:
            return slug
        slug = f'{base}-{i}'
        i += 1


_MAGIC = {
    'jpg': [b'\xff\xd8\xff'], 'jpeg': [b'\xff\xd8\xff'],
    'png': [b'\x89PNG'], 'webp': [b'RIFF'],
}


def save_product_image(file_obj):
    name = file_obj.filename or ''
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if ext not in current_app.config['PRODUCT_IMAGE_EXTENSIONS']:
        raise ValueError(f'Dateityp nicht erlaubt: {name}')
    head = file_obj.stream.read(12)
    file_obj.stream.seek(0)
    if not any(head.startswith(m) for m in _MAGIC[ext]) or (ext == 'webp' and head[8:12] != b'WEBP'):
        raise ValueError(f'Keine gültige Bilddatei: {name}')
    disk_name = f'{uuid.uuid4().hex}.{"jpg" if ext == "jpeg" else ext}'
    file_obj.save(os.path.join(current_app.config['UPLOAD_FOLDER'], 'products', disk_name))
    return disk_name


def delete_product_image_file(filename):
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'products', filename)
    if os.path.exists(path):
        os.remove(path)


# ---------------------------------------------------------------------------
# Produkte
# ---------------------------------------------------------------------------
@admin_bp.route('/produkte')
@login_required
def products():
    all_products = Product.query.order_by(Product.sort_order, Product.name).all()
    return render_template('admin/products.html', products=all_products)


@admin_bp.route('/produkte/neu', methods=['GET', 'POST'])
@login_required
def product_new():
    if request.method == 'POST':
        product = Product()
        db.session.add(product)
        if _save_product_form(product):
            flash(f'Produkt „{product.name}" angelegt.', 'success')
            return redirect(url_for('admin.product_edit', product_id=product.id))
        db.session.rollback()
        return render_template('admin/product_form.html', product=None, form=request.form,
                               cents_to_input=cents_to_input)
    return render_template('admin/product_form.html', product=None, form={},
                           cents_to_input=cents_to_input)


@admin_bp.route('/produkte/<int:product_id>/bearbeiten', methods=['GET', 'POST'])
@login_required
def product_edit(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        if _save_product_form(product):
            flash('Produkt gespeichert.', 'success')
            return redirect(url_for('admin.product_edit', product_id=product.id))
        db.session.rollback()
        product = Product.query.get_or_404(product_id)
    return render_template('admin/product_form.html', product=product, form={},
                           cents_to_input=cents_to_input)


def _save_product_form(product):
    """Übernimmt Formular inkl. Varianten und Bilder. Gibt False bei Fehlern zurück."""
    f = request.form
    errors = []

    product.name = f.get('name', '').strip()
    if not product.name:
        errors.append('Name fehlt.')
    product.short_description = f.get('short_description', '').strip() or None
    product.description = f.get('description', '').strip() or None
    product.delivery_time = f.get('delivery_time', '').strip() or '3–5 Werktage'
    product.material = f.get('material', '').strip() or None
    product.safety_info = f.get('safety_info', '').strip() or None
    product.is_active = f.get('is_active') == '1'
    product.show_in_main = f.get('show_in_main') == '1'
    product.show_in_boutique = f.get('show_in_boutique') == '1'
    if product.is_active and not (product.show_in_main or product.show_in_boutique):
        errors.append('Aktives Produkt: bitte mindestens einen Shop auswählen.')
    product.sort_order = f.get('sort_order', 0, type=int) or 0
    product.made_to_order = f.get('made_to_order') == '1'
    extra = f.get('extra_day_per_units', '').strip()
    if product.made_to_order and extra:
        if not extra.isdigit() or int(extra) < 1:
            errors.append('„+1 Werktag je … Stück“ muss eine ganze Zahl ab 1 sein.')
        else:
            product.extra_day_per_units = int(extra)
    else:
        product.extra_day_per_units = None
    try:
        price = parse_euro(f.get('price'))
        if price is None:
            errors.append('Preis fehlt.')
        product.price_cents = price or 0
    except ValueError as e:
        errors.append(str(e))

    slug_input = f.get('slug', '').strip()
    with db.session.no_autoflush:
        product.slug = unique_slug(slugify(slug_input or product.name), product.id)

    # --- Bestand/SKU/aktiv der bestehenden Kombinationen ---
    for v in product.variants:
        if f.get(f'combo-{v.id}-seen') != '1':
            continue
        v.sku = f.get(f'combo-{v.id}-sku', '').strip() or None
        v.is_active = f.get(f'combo-{v.id}-active') == '1'
        raw = f.get(f'combo-{v.id}-stock', '').strip()
        if raw:
            if not raw.isdigit():
                errors.append(f'„{v.name}": Bestand muss eine ganze Zahl sein.')
            else:
                v.stock = int(raw)

    # --- Optionsgruppen: opt-<g>-<feld>, Werte: opt-<g>-val-<i>-<feld> ---
    groups, values = {}, {}
    for key, value in f.items():
        m = re.match(r'opt-(\d+)-val-(\d+)-(\w+)$', key)
        if m:
            values.setdefault(int(m.group(1)), {}).setdefault(int(m.group(2)), {})[m.group(3)] = value.strip()
            continue
        m = re.match(r'opt-(\d+)-(\w+)$', key)
        if m:
            groups.setdefault(int(m.group(1)), {})[m.group(2)] = value.strip()

    existing_opts = {o.id: o for o in product.options}
    kept, drop_opts, drop_vals = [], [], []
    for g in sorted(set(groups) | set(values)):
        row = groups.get(g, {})
        opt = existing_opts.get(int(row['id'])) if row.get('id', '').isdigit() else None
        rows = [values.get(g, {})[i] for i in sorted(values.get(g, {}))]
        live = [r for r in rows if r.get('name') and r.get('delete') != '1']
        name = row.get('name', '')
        if row.get('delete') == '1' or (not name and not live):
            if opt:
                drop_opts.append(opt)
            continue
        if not name:
            errors.append(f'Optionsgruppe {g + 1}: Name fehlt (z. B. „Größe“).')
            continue
        if not live:
            errors.append(f'Optionsgruppe „{name}": mindestens einen Wert eintragen.')
            continue
        if not opt:
            opt = ProductOption()
            product.options.append(opt)
        opt.name, opt.position = name, len(kept)
        existing_vals = {v.id: v for v in opt.values}
        kept_vals, seen = [], set()
        for r in rows:
            val = existing_vals.get(int(r['id'])) if r.get('id', '').isdigit() else None
            if not r.get('name') or r.get('delete') == '1':
                if val:
                    drop_vals.append(val)
                continue
            if r['name'].lower() in seen:
                errors.append(f'„{name}": Wert „{r["name"]}" ist doppelt.')
                continue
            seen.add(r['name'].lower())
            if not val:
                val = ProductOptionValue()
                opt.values.append(val)
            val.name, val.position = r['name'], len(kept_vals)
            try:
                val.surcharge_cents = parse_euro(r.get('surcharge')) or 0
            except ValueError as e:
                errors.append(f'„{name}: {r["name"]}": {e} Aufpreise dürfen nicht negativ sein.')
            kept_vals.append(val)
        kept.append(kept_vals)

    if len(kept) > 3:
        errors.append('Maximal 3 Optionsgruppen.')
    combos = list(itertools.product(*kept))  # ohne Gruppen: [()] → „Standard“
    if len(combos) > 150:
        errors.append(f'{len(combos)} Kombinationen sind zu viele (max. 150).')
    default_stock = f.get('default_stock', '0').strip()
    default_stock = int(default_stock) if default_stock.isdigit() else 0

    if not errors:
        db.session.flush()  # IDs für neue Werte
        by_key = {frozenset(x.id for x in v.values): v for v in list(product.variants)}
        wanted = {frozenset(x.id for x in c): c for c in combos}
        for key, v in by_key.items():
            if key not in wanted:
                _delete_variant(v)
        for pos, (key, combo) in enumerate(wanted.items()):
            v = by_key.get(key)
            if not v:
                v = ProductVariant(stock=0 if product.made_to_order else default_stock,
                                   is_active=True)
                v.values = list(combo)
                product.variants.append(v)
            v.name = ' / '.join(x.name for x in combo) or 'Standard'
            v.position = pos
        for val in drop_vals:
            if val.option in product.options and val in val.option.values:
                val.option.values.remove(val)
            db.session.delete(val)
        for opt in drop_opts:
            product.options.remove(opt)
            db.session.delete(opt)

    # --- Bilder: Löschen / Reihenfolge / Alt-Text ---
    for img in list(product.images):
        if f.get(f'image-{img.id}-delete') == '1':
            product.images.remove(img)
            db.session.delete(img)
            delete_product_image_file(img.filename)
            continue
        img.position = f.get(f'image-{img.id}-position', img.position, type=int)
        img.alt = f.get(f'image-{img.id}-alt', '').strip() or None

    if errors:
        for e in errors:
            flash(e, 'error')
        return False

    # --- Neue Bilder ---
    next_pos = max([i.position for i in product.images], default=-1) + 1
    for file_obj in request.files.getlist('images'):
        if not file_obj or not file_obj.filename:
            continue
        try:
            disk_name = save_product_image(file_obj)
        except ValueError as e:
            flash(str(e), 'error')
            continue
        product.images.append(ProductImage(filename=disk_name, position=next_pos))
        next_pos += 1

    product.updated_at = datetime.utcnow()
    db.session.commit()
    return True


def _delete_variant(variant):
    # Bestellpositionen behalten ihre Kopie von Name/Preis
    if variant.id:
        OrderItem.query.filter_by(variant_id=variant.id).update({'variant_id': None})
    variant.values = []
    variant.product.variants.remove(variant)
    db.session.delete(variant)


@admin_bp.route('/produkte/<int:product_id>/duplizieren', methods=['POST'])
@login_required
def product_duplicate(product_id):
    """Komplette Kopie ohne Bilder, als Entwurf. SKUs werden geleert (müssen eindeutig sein)."""
    src = Product.query.get_or_404(product_id)
    copy = Product(
        name=f'{src.name} (Kopie)'[:200], short_description=src.short_description,
        description=src.description, price_cents=src.price_cents,
        delivery_time=src.delivery_time, material=src.material, safety_info=src.safety_info,
        made_to_order=src.made_to_order, extra_day_per_units=src.extra_day_per_units,
        show_in_main=src.show_in_main, show_in_boutique=src.show_in_boutique,
        sort_order=src.sort_order, is_active=False,
    )
    with db.session.no_autoflush:
        copy.slug = unique_slug(slugify(copy.name))
    value_map = {}
    for o in src.options:
        new_opt = ProductOption(name=o.name, position=o.position)
        for v in o.values:
            nv = ProductOptionValue(name=v.name, surcharge_cents=v.surcharge_cents,
                                    position=v.position)
            new_opt.values.append(nv)
            value_map[v.id] = nv
        copy.options.append(new_opt)
    for v in src.variants:
        nv = ProductVariant(name=v.name, stock=v.stock, is_active=v.is_active, position=v.position)
        nv.values = [value_map[x.id] for x in v.values]
        copy.variants.append(nv)
    db.session.add(copy)
    db.session.commit()
    flash('Kopie angelegt (Entwurf, ohne Bilder). Bitte Namen anpassen.', 'success')
    return redirect(url_for('admin.product_edit', product_id=copy.id))


@admin_bp.route('/produkte/<int:product_id>/loeschen', methods=['POST'])
@login_required
def product_delete(product_id):
    product = Product.query.get_or_404(product_id)
    variant_ids = [v.id for v in product.variants]
    if variant_ids and OrderItem.query.filter(OrderItem.variant_id.in_(variant_ids)).count():
        product.is_active = False
        db.session.commit()
        flash('Produkt hat bereits Bestellungen und wurde deshalb nur deaktiviert.', 'info')
        return redirect(url_for('admin.products'))
    filenames = [i.filename for i in product.images]
    db.session.delete(product)
    db.session.commit()
    for fn in filenames:
        delete_product_image_file(fn)
    flash('Produkt gelöscht.', 'success')
    return redirect(url_for('admin.products'))


# ---------------------------------------------------------------------------
# Bestellungen
# ---------------------------------------------------------------------------
@admin_bp.route('/bestellungen')
@login_required
def orders():
    status_filter = request.args.get('status', '')
    query = Order.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    else:
        query = query.filter(Order.status != 'Abgebrochen')
    all_orders = query.order_by(Order.created_at.desc()).all()
    open_withdrawals = (Withdrawal.query.filter_by(is_processed=False)
                        .order_by(Withdrawal.created_at.desc()).all())
    return render_template('admin/orders.html', orders=all_orders, statuses=ORDER_STATUSES,
                           status_filter=status_filter, open_withdrawals=open_withdrawals)


@admin_bp.route('/bestellungen/<int:order_id>')
@login_required
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    withdrawals = Withdrawal.query.filter(
        (Withdrawal.order_id == order.id) | (Withdrawal.order_number == order.number)
    ).order_by(Withdrawal.created_at).all()
    return render_template('admin/order_detail.html', order=order, carriers=svc.CARRIERS,
                           tracking_url=svc.tracking_url(order), withdrawals=withdrawals)


@admin_bp.route('/bestellungen/<int:order_id>/versendet', methods=['POST'])
@login_required
def order_ship(order_id):
    order = Order.query.get_or_404(order_id)
    if order.status not in ('Bezahlt', 'Versendet'):
        flash('Nur bezahlte Bestellungen können versendet werden.', 'error')
        return redirect(url_for('admin.order_detail', order_id=order.id))
    order.carrier = request.form.get('carrier') or None
    order.tracking_number = request.form.get('tracking_number', '').strip() or None
    order.status = 'Versendet'
    order.shipped_at = order.shipped_at or datetime.utcnow()
    db.session.commit()
    if request.form.get('notify') == '1':
        svc.send_shipping_notification(order)
        flash('Als versendet markiert, Versandmail geht raus.', 'success')
    else:
        flash('Als versendet markiert.', 'success')
    return redirect(url_for('admin.order_detail', order_id=order.id))


@admin_bp.route('/bestellungen/<int:order_id>/stornieren', methods=['POST'])
@login_required
def order_cancel(order_id):
    order = Order.query.get_or_404(order_id)
    if order.status == 'Offen':
        svc.abort_order(order, 'Abgebrochen', expire_stripe=True)
        flash('Offene Bestellung abgebrochen, Bestand freigegeben.', 'success')
        return redirect(url_for('admin.order_detail', order_id=order.id))
    if order.status not in ('Bezahlt', 'Versendet'):
        return redirect(url_for('admin.order_detail', order_id=order.id))
    if request.form.get('restock') == '1':
        for item in order.items:
            if item.variant_id and not item.made_to_order:
                db.session.execute(update(ProductVariant)
                                   .where(ProductVariant.id == item.variant_id)
                                   .values(stock=ProductVariant.stock + item.quantity))
    order.status = 'Storniert'
    db.session.commit()
    flash('Bestellung storniert. Denk an die Erstattung im Stripe-Dashboard!', 'success')
    return redirect(url_for('admin.order_detail', order_id=order.id))


@admin_bp.route('/bestellungen/<int:order_id>/notiz', methods=['POST'])
@login_required
def order_notes(order_id):
    order = Order.query.get_or_404(order_id)
    order.notes = request.form.get('notes', '').strip() or None
    db.session.commit()
    flash('Notiz gespeichert.', 'success')
    return redirect(url_for('admin.order_detail', order_id=order.id))


# ---------------------------------------------------------------------------
# Rabattcodes
# ---------------------------------------------------------------------------
@admin_bp.route('/rabattcodes')
@login_required
def discounts():
    codes = DiscountCode.query.order_by(DiscountCode.is_active.desc(),
                                        DiscountCode.created_at.desc()).all()
    return render_template('admin/discounts.html', codes=codes, today=svc.berlin_today())


@admin_bp.route('/rabattcodes/neu', methods=['GET', 'POST'])
@login_required
def discount_new():
    dc = DiscountCode()
    if request.method == 'POST':
        if _save_discount_form(dc, new=True):
            flash(f'Rabattcode {dc.code} angelegt.', 'success')
            return redirect(url_for('admin.discounts'))
        db.session.rollback()
    return render_template('admin/discount_form.html', dc=None, form=request.form,
                           kinds=DISCOUNT_KINDS, cents_to_input=cents_to_input)


@admin_bp.route('/rabattcodes/<int:code_id>/bearbeiten', methods=['GET', 'POST'])
@login_required
def discount_edit(code_id):
    dc = DiscountCode.query.get_or_404(code_id)
    if request.method == 'POST':
        if _save_discount_form(dc):
            flash('Rabattcode gespeichert.', 'success')
            return redirect(url_for('admin.discounts'))
        db.session.rollback()
        dc = DiscountCode.query.get_or_404(code_id)
        return render_template('admin/discount_form.html', dc=dc, form=request.form,
                               kinds=DISCOUNT_KINDS, cents_to_input=cents_to_input)
    orders = dc.orders.filter(Order.status.in_(('Bezahlt', 'Versendet', 'Storniert'))) \
        .order_by(Order.created_at.desc()).all()
    return render_template('admin/discount_form.html', dc=dc, form={}, orders=orders,
                           kinds=DISCOUNT_KINDS, cents_to_input=cents_to_input)


def _parse_date(value, label, errors):
    value = (value or '').strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(f'{label}: ungültiges Datum.')
        return None


def _save_discount_form(dc, new=False):
    f = request.form
    errors = []
    code = svc.normalize_code(f.get('code'))
    if not re.fullmatch(r'[A-Z0-9_-]{3,40}', code or ''):
        errors.append('Code: 3–40 Zeichen, nur Buchstaben (ohne Umlaute), Ziffern, - und _.')
    else:
        with db.session.no_autoflush:
            other = DiscountCode.query.filter_by(code=code).first()
        if other and other.id != dc.id:
            errors.append(f'Den Code {code} gibt es schon.')
    if not new and dc.code != code and dc.orders.count():
        errors.append('Der Code wurde schon benutzt und kann nicht mehr umbenannt werden '
                      '— leg stattdessen einen neuen an.')
    dc.code = code
    dc.note = f.get('note', '').strip() or None
    dc.kind = f.get('kind') if f.get('kind') in DISCOUNT_KINDS else 'percent'
    dc.free_shipping = f.get('free_shipping') == '1'
    raw = f.get('value', '').strip()
    try:
        if dc.kind == 'percent':
            dc.value = int(raw.replace('%', '').strip() or 0)
            if not 0 <= dc.value <= 100:
                raise ValueError
        else:
            dc.value = parse_euro(raw) or 0
    except ValueError:
        errors.append('Rabatt: bei Prozent eine ganze Zahl von 0 bis 100, '
                      'sonst ein Eurobetrag wie 5,00.')
    if not dc.value and not dc.free_shipping:
        errors.append('Bitte einen Rabatt angeben oder „versandkostenfrei“ wählen.')
    try:
        dc.min_order_cents = parse_euro(f.get('min_order')) or 0
    except ValueError as e:
        errors.append(f'Mindestbestellwert: {e}')
    dc.valid_from = _parse_date(f.get('valid_from'), 'Gültig ab', errors)
    dc.valid_until = _parse_date(f.get('valid_until'), 'Gültig bis', errors)
    if dc.valid_from and dc.valid_until and dc.valid_until < dc.valid_from:
        errors.append('„Gültig bis“ liegt vor „Gültig ab“.')
    max_uses = f.get('max_uses', '').strip()
    if max_uses and (not max_uses.isdigit() or int(max_uses) < 1):
        errors.append('Max. Einlösungen: ganze Zahl ab 1 oder leer für unbegrenzt.')
    dc.max_uses = int(max_uses) if max_uses.isdigit() and int(max_uses) >= 1 else None
    dc.storefront = f.get('storefront') if f.get('storefront') in ('all', 'main', 'boutique') else 'all'
    dc.is_active = f.get('is_active') == '1'

    if errors:
        for e in errors:
            flash(e, 'error')
        return False
    if new:
        db.session.add(dc)
    db.session.commit()
    return True


@admin_bp.route('/rabattcodes/<int:code_id>/loeschen', methods=['POST'])
@login_required
def discount_delete(code_id):
    dc = DiscountCode.query.get_or_404(code_id)
    if dc.orders.count():
        dc.is_active = False
        db.session.commit()
        flash(f'{dc.code} wurde schon benutzt und ist jetzt deaktiviert '
              '(bleibt für die Bestellhistorie erhalten).', 'info')
    else:
        db.session.delete(dc)
        db.session.commit()
        flash(f'Rabattcode {dc.code} gelöscht.', 'success')
    return redirect(url_for('admin.discounts'))


@admin_bp.route('/widerrufe/<int:withdrawal_id>/erledigt', methods=['POST'])
@login_required
def withdrawal_done(withdrawal_id):
    w = Withdrawal.query.get_or_404(withdrawal_id)
    w.is_processed = True
    db.session.commit()
    flash('Widerruf als erledigt markiert.', 'success')
    return redirect(request.referrer or url_for('admin.orders'))
