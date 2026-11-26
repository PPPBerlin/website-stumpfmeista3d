from flask import (Blueprint, render_template, redirect, url_for,
                   request, flash, abort, jsonify)
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db
from models import (AdminUser, Customer, Inquiry, Project, ProjectFile, PROJECT_STATUSES,
                    Order, Withdrawal)

admin_bp = Blueprint('admin', __name__, template_folder='../../templates/admin')


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = AdminUser.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('admin.dashboard'))
        flash('Ungültige Anmeldedaten.', 'error')
    return render_template('admin/login.html')


@admin_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('admin.login'))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@admin_bp.route('/')
@login_required
def dashboard():
    stats = {
        'customers': Customer.query.count(),
        'open_inquiries': Inquiry.query.filter_by(status='Neu').count(),
        'active_projects': Project.query.filter(
            Project.status.notin_(['Abgeschlossen', 'Archiviert'])
        ).count(),
        'orders_to_ship': Order.query.filter_by(status='Bezahlt').count(),
        'open_withdrawals': Withdrawal.query.filter_by(is_processed=False).count(),
    }
    recent_inquiries = (Inquiry.query.order_by(Inquiry.created_at.desc())
                        .limit(5).all())
    return render_template('admin/dashboard.html', stats=stats,
                           recent_inquiries=recent_inquiries)


# ---------------------------------------------------------------------------
# Anfragen (Inquiries)
# ---------------------------------------------------------------------------
@admin_bp.route('/anfragen')
@login_required
def inquiries():
    all_inquiries = Inquiry.query.order_by(Inquiry.created_at.desc()).all()
    return render_template('admin/inquiries.html', inquiries=all_inquiries)


@admin_bp.route('/anfragen/<int:inquiry_id>')
@login_required
def inquiry_detail(inquiry_id):
    inquiry = Inquiry.query.get_or_404(inquiry_id)
    # Als gelesen markieren
    if inquiry.status == 'Neu':
        inquiry.status = 'Gelesen'
        db.session.commit()
    customers = Customer.query.order_by(Customer.last_name).all()
    return render_template('admin/inquiry_detail.html', inquiry=inquiry,
                           customers=customers)


@admin_bp.route('/anfragen/<int:inquiry_id>/konvertieren', methods=['POST'])
@login_required
def inquiry_convert(inquiry_id):
    """Anfrage → neuen Kunden anlegen oder bestehenden verknüpfen + Projekt erstellen."""
    inquiry = Inquiry.query.get_or_404(inquiry_id)
    action = request.form.get('action')

    if action == 'new_customer':
        customer = Customer(
            first_name=inquiry.first_name,
            last_name=inquiry.last_name,
            email=inquiry.email,
            phone=inquiry.phone,
        )
        db.session.add(customer)
        db.session.flush()
    elif action == 'existing_customer':
        customer_id = request.form.get('customer_id')
        customer = Customer.query.get_or_404(customer_id)
    else:
        flash('Ungültige Aktion.', 'error')
        return redirect(url_for('admin.inquiry_detail', inquiry_id=inquiry_id))

    inquiry.customer = customer
    inquiry.status = 'Konvertiert'

    # Automatisch ein Projekt anlegen
    project = Project(
        title=inquiry.subject,
        description=inquiry.message,
        customer=customer,
        inquiry=inquiry,
    )
    db.session.add(project)
    db.session.commit()
    flash(f'Anfrage konvertiert. Projekt "{project.title}" angelegt.', 'success')
    return redirect(url_for('admin.project_detail', project_id=project.id))


# ---------------------------------------------------------------------------
# Kunden
# ---------------------------------------------------------------------------
@admin_bp.route('/kunden')
@login_required
def customers():
    q = request.args.get('q', '').strip()
    query = Customer.query
    if q:
        like = f'%{q}%'
        query = query.filter(
            (Customer.first_name.ilike(like)) |
            (Customer.last_name.ilike(like)) |
            (Customer.email.ilike(like)) |
            (Customer.company.ilike(like))
        )
    all_customers = query.order_by(Customer.last_name).all()
    return render_template('admin/customers.html', customers=all_customers, q=q)


@admin_bp.route('/kunden/neu', methods=['GET', 'POST'])
@login_required
def customer_new():
    if request.method == 'POST':
        customer = Customer(
            first_name=request.form['first_name'].strip(),
            last_name=request.form['last_name'].strip(),
            email=request.form['email'].strip().lower(),
            phone=request.form.get('phone', '').strip() or None,
            company=request.form.get('company', '').strip() or None,
            notes=request.form.get('notes', '').strip() or None,
        )
        db.session.add(customer)
        db.session.commit()
        flash(f'Kunde {customer.full_name} angelegt.', 'success')
        return redirect(url_for('admin.customer_detail', customer_id=customer.id))
    return render_template('admin/customer_form.html', customer=None)


@admin_bp.route('/kunden/<int:customer_id>')
@login_required
def customer_detail(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    return render_template('admin/customer_detail.html', customer=customer)


@admin_bp.route('/kunden/<int:customer_id>/bearbeiten', methods=['GET', 'POST'])
@login_required
def customer_edit(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    if request.method == 'POST':
        customer.first_name = request.form['first_name'].strip()
        customer.last_name = request.form['last_name'].strip()
        customer.email = request.form['email'].strip().lower()
        customer.phone = request.form.get('phone', '').strip() or None
        customer.company = request.form.get('company', '').strip() or None
        customer.notes = request.form.get('notes', '').strip() or None
        db.session.commit()
        flash('Kundendaten aktualisiert.', 'success')
        return redirect(url_for('admin.customer_detail', customer_id=customer.id))
    return render_template('admin/customer_form.html', customer=customer)


# ---------------------------------------------------------------------------
# Projekte
# ---------------------------------------------------------------------------
@admin_bp.route('/projekte')
@login_required
def projects():
    status_filter = request.args.get('status', '')
    query = Project.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    all_projects = query.order_by(Project.updated_at.desc()).all()
    return render_template('admin/projects.html', projects=all_projects,
                           statuses=PROJECT_STATUSES, status_filter=status_filter)


@admin_bp.route('/projekte/neu', methods=['GET', 'POST'])
@login_required
def project_new():
    customers = Customer.query.order_by(Customer.last_name).all()
    if request.method == 'POST':
        project = Project(
            title=request.form['title'].strip(),
            description=request.form.get('description', '').strip() or None,
            customer_id=int(request.form['customer_id']),
            status=request.form.get('status', 'Anfrage'),
        )
        db.session.add(project)
        db.session.commit()
        flash(f'Projekt "{project.title}" angelegt.', 'success')
        return redirect(url_for('admin.project_detail', project_id=project.id))
    return render_template('admin/project_form.html', project=None,
                           customers=customers, statuses=PROJECT_STATUSES)


@admin_bp.route('/projekte/<int:project_id>')
@login_required
def project_detail(project_id):
    project = Project.query.get_or_404(project_id)
    return render_template('admin/project_detail.html', project=project,
                           statuses=PROJECT_STATUSES)


@admin_bp.route('/projekte/<int:project_id>/status', methods=['POST'])
@login_required
def project_status_update(project_id):
    """AJAX-Endpunkt: Status eines Projekts aktualisieren."""
    project = Project.query.get_or_404(project_id)
    new_status = request.json.get('status')
    if new_status not in PROJECT_STATUSES:
        return jsonify({'success': False, 'error': 'Ungültiger Status'}), 400
    project.status = new_status
    db.session.commit()
    return jsonify({'success': True, 'status': project.status})


@admin_bp.route('/projekte/<int:project_id>/bearbeiten', methods=['GET', 'POST'])
@login_required
def project_edit(project_id):
    project = Project.query.get_or_404(project_id)
    customers = Customer.query.order_by(Customer.last_name).all()
    if request.method == 'POST':
        project.title = request.form['title'].strip()
        project.description = request.form.get('description', '').strip() or None
        project.customer_id = int(request.form['customer_id'])
        project.status = request.form.get('status', project.status)
        db.session.commit()
        flash('Projekt aktualisiert.', 'success')
        return redirect(url_for('admin.project_detail', project_id=project.id))
    return render_template('admin/project_form.html', project=project,
                           customers=customers, statuses=PROJECT_STATUSES)


# Shop-Verwaltung (Produkte, Bestellungen, Widerrufe) — registriert sich an admin_bp
from . import shop_routes  # noqa: E402,F401
