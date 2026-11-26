from extensions import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime


# ---------------------------------------------------------------------------
# Workflow-Stufen für Projekte
# ---------------------------------------------------------------------------
PROJECT_STATUSES = [
    'Anfrage',
    'In Beratung',
    'Konstruktion',
    'Im Druck',
    'Abgeschlossen',
    'Archiviert',
]


# ---------------------------------------------------------------------------
# Admin-User (Flask-Login)
# ---------------------------------------------------------------------------
class AdminUser(UserMixin, db.Model):
    __tablename__ = 'admin_users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_superadmin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<AdminUser {self.username}>'


@login_manager.user_loader
def load_user(user_id):
    return AdminUser.query.get(int(user_id))


# ---------------------------------------------------------------------------
# Kunde
# ---------------------------------------------------------------------------
class Customer(db.Model):
    __tablename__ = 'customers'

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    company = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationen
    inquiries = db.relationship('Inquiry', backref='customer', lazy='dynamic')
    projects = db.relationship('Project', backref='customer', lazy='dynamic')

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'

    def __repr__(self):
        return f'<Customer {self.full_name}>'


# ---------------------------------------------------------------------------
# Kontaktanfrage (aus dem Kontaktformular)
# ---------------------------------------------------------------------------
class Inquiry(db.Model):
    __tablename__ = 'inquiries'

    id = db.Column(db.Integer, primary_key=True)
    # Absender-Daten
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    # Status der Anfrage
    status = db.Column(db.String(50), default='Neu')  # Neu, Gelesen, Konvertiert
    # Optionale Verknüpfung mit bestehendem Kunden
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Anhänge zur Anfrage
    files = db.relationship('InquiryFile', backref='inquiry', lazy='dynamic',
                            cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Inquiry {self.id} von {self.email}>'


class InquiryFile(db.Model):
    __tablename__ = 'inquiry_files'

    id = db.Column(db.Integer, primary_key=True)
    inquiry_id = db.Column(db.Integer, db.ForeignKey('inquiries.id'), nullable=False)
    filename = db.Column(db.String(300), nullable=False)   # sicherer Dateiname auf Disk
    original_name = db.Column(db.String(300), nullable=False)  # Original-Dateiname des Users
    file_size = db.Column(db.Integer, nullable=True)       # Bytes
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<InquiryFile {self.original_name}>'


# ---------------------------------------------------------------------------
# Projekt (Auftrag für einen Kunden)
# ---------------------------------------------------------------------------
class Project(db.Model):
    __tablename__ = 'projects'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='Anfrage', nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    # Optionaler Bezug zur ursprünglichen Anfrage
    inquiry_id = db.Column(db.Integer, db.ForeignKey('inquiries.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Anhänge zum Projekt
    files = db.relationship('ProjectFile', backref='project', lazy='dynamic',
                            cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Project {self.title} [{self.status}]>'


class ProjectFile(db.Model):
    __tablename__ = 'project_files'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    filename = db.Column(db.String(300), nullable=False)
    original_name = db.Column(db.String(300), nullable=False)
    file_size = db.Column(db.Integer, nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<ProjectFile {self.original_name}>'


# ---------------------------------------------------------------------------
# Shop: Produkte, Varianten, Bilder
# Alle Geldbeträge in Cent (Integer), um Rundungsfehler zu vermeiden.
# ---------------------------------------------------------------------------
class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    short_description = db.Column(db.String(300), nullable=True)
    description = db.Column(db.Text, nullable=True)
    price_cents = db.Column(db.Integer, nullable=False, default=0)
    # Bezeichnung der Variantenauswahl, z.B. "Farbe" oder "Größe"
    variant_label = db.Column(db.String(50), nullable=False, default='Ausführung')
    delivery_time = db.Column(db.String(100), nullable=False, default='3–5 Werktage')
    # GPSR: Material + Warn-/Sicherheitshinweise (werden auf der Produktseite angezeigt)
    material = db.Column(db.String(200), nullable=True)
    safety_info = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    # In welchen Schaufenstern erscheint das Produkt? (siehe storefronts.py)
    show_in_main = db.Column(db.Boolean, nullable=False, default=True, server_default='1')
    show_in_boutique = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    variants = db.relationship('ProductVariant', backref='product',
                               order_by='ProductVariant.position',
                               cascade='all, delete-orphan')
    images = db.relationship('ProductImage', backref='product',
                             order_by='ProductImage.position',
                             cascade='all, delete-orphan')

    def in_storefront(self, key):
        return bool(getattr(self, f'show_in_{key}', False))

    @property
    def storefront_keys(self):
        return [k for k in ('main', 'boutique') if self.in_storefront(k)]

    @property
    def active_variants(self):
        return [v for v in self.variants if v.is_active]

    @property
    def cover_image(self):
        return self.images[0] if self.images else None

    @property
    def min_price_cents(self):
        prices = [v.effective_price_cents for v in self.active_variants]
        return min(prices) if prices else self.price_cents

    @property
    def has_price_range(self):
        return len({v.effective_price_cents for v in self.active_variants}) > 1

    @property
    def total_stock(self):
        return sum(v.stock for v in self.active_variants)

    @property
    def is_sold_out(self):
        return self.total_stock <= 0

    def __repr__(self):
        return f'<Product {self.slug}>'


class ProductVariant(db.Model):
    __tablename__ = 'product_variants'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    # Leer = Produktpreis gilt
    price_cents = db.Column(db.Integer, nullable=True)
    stock = db.Column(db.Integer, nullable=False, default=0)
    sku = db.Column(db.String(64), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    position = db.Column(db.Integer, nullable=False, default=0)

    @property
    def effective_price_cents(self):
        return self.price_cents if self.price_cents is not None else self.product.price_cents

    def __repr__(self):
        return f'<ProductVariant {self.product_id}:{self.name}>'


class ProductImage(db.Model):
    __tablename__ = 'product_images'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    filename = db.Column(db.String(300), nullable=False)
    alt = db.Column(db.String(200), nullable=True)
    position = db.Column(db.Integer, nullable=False, default=0)

    def __repr__(self):
        return f'<ProductImage {self.filename}>'


# ---------------------------------------------------------------------------
# Shop: Bestellungen
# ---------------------------------------------------------------------------
ORDER_STATUSES = [
    'Offen',        # Checkout gestartet, Zahlung ausstehend (Bestand reserviert)
    'Bezahlt',      # Zahlung bestätigt → versandbereit
    'Versendet',
    'Storniert',    # nach Zahlung storniert (Erstattung über Stripe-Dashboard)
    'Abgebrochen',  # Checkout abgebrochen/abgelaufen, nie bezahlt
]


class Order(db.Model):
    __tablename__ = 'orders'

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='Offen')
    # Schaufenster, in dem bestellt wurde ('main' / 'boutique')
    storefront = db.Column(db.String(20), nullable=False, default='main', server_default='main')

    # Kundendaten (kommen nach Zahlung von Stripe)
    email = db.Column(db.String(200), nullable=True)
    name = db.Column(db.String(200), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    address_line1 = db.Column(db.String(200), nullable=True)
    address_line2 = db.Column(db.String(200), nullable=True)
    postal_code = db.Column(db.String(20), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    country = db.Column(db.String(2), nullable=True)

    subtotal_cents = db.Column(db.Integer, nullable=False, default=0)
    shipping_cents = db.Column(db.Integer, nullable=False, default=0)
    total_cents = db.Column(db.Integer, nullable=False, default=0)

    stripe_session_id = db.Column(db.String(255), unique=True, nullable=True)
    stripe_payment_intent = db.Column(db.String(255), nullable=True)
    # True, solange der Bestand für diese Bestellung abgezogen ist
    stock_reserved = db.Column(db.Boolean, nullable=False, default=False)

    carrier = db.Column(db.String(50), nullable=True)
    tracking_number = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)
    shipped_at = db.Column(db.DateTime, nullable=True)

    items = db.relationship('OrderItem', backref='order', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Order {self.number} [{self.status}]>'


class OrderItem(db.Model):
    __tablename__ = 'order_items'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    # Kann NULL werden, wenn die Variante später gelöscht wird —
    # deshalb werden Name und Preis zum Kaufzeitpunkt mitgespeichert.
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=True)
    product_name = db.Column(db.String(200), nullable=False)
    variant_name = db.Column(db.String(100), nullable=True)
    unit_price_cents = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

    variant = db.relationship('ProductVariant')

    @property
    def line_total_cents(self):
        return self.unit_price_cents * self.quantity

    @property
    def display_name(self):
        if self.variant_name and self.variant_name != 'Standard':
            return f'{self.product_name} – {self.variant_name}'
        return self.product_name


# ---------------------------------------------------------------------------
# Widerrufserklärungen über die Widerrufsfunktion der Website
# (Pflicht seit 19.06.2026, Art. 11a Verbraucherrechte-RL)
# ---------------------------------------------------------------------------
class Withdrawal(db.Model):
    __tablename__ = 'withdrawals'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    order_number = db.Column(db.String(50), nullable=False)
    message = db.Column(db.Text, nullable=True)
    # Automatisch zugeordnet, wenn Bestellnummer + E-Mail passen
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=True)
    is_processed = db.Column(db.Boolean, nullable=False, default=False)
    storefront = db.Column(db.String(20), nullable=False, default='main', server_default='main')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    order = db.relationship('Order', backref='withdrawals')
