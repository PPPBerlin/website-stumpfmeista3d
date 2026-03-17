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
