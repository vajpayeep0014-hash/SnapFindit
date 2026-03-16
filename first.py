import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'fallback-dev-key')   
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'heic', 'heif'}
COLLEGE_DOMAIN = '@medicaps.ac.in'
ADMIN_EMAILS = {'admin@medicaps.ac.in', 'security@medicaps.ac.in'}

db = SQLAlchemy(app)
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
    'pool_size': 5,
    'max_overflow': 2
}


# ─── Models ────────────────────────────────────────────────────────────────────

class User(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    email        = db.Column(db.String(200), unique=True, nullable=False)
    name         = db.Column(db.String(120), nullable=False)
    password     = db.Column(db.String(300), nullable=False)
    is_admin     = db.Column(db.Boolean, default=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    items_posted = db.relationship('Item', backref='reporter', lazy=True, foreign_keys='Item.reporter_id')
    claims       = db.relationship('Item', backref='claimer', lazy=True, foreign_keys='Item.claimer_id')


class Item(db.Model):
    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(120), nullable=False)
    location        = db.Column(db.String(200), nullable=False)
    category        = db.Column(db.String(50), nullable=False, default='Generic')
    description     = db.Column(db.Text)
    image_file      = db.Column(db.String(200), nullable=False)
    secret_question = db.Column(db.String(300))
    secret_answer   = db.Column(db.String(300))
    serial_number   = db.Column(db.String(200))
    claimed         = db.Column(db.Boolean, default=False)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    reporter_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    claimer_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    claimed_at      = db.Column(db.DateTime, nullable=True)


# ─── Auth helpers ───────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in.', 'warning')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or not user.is_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

def current_user():
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ─── Auth routes ───────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email.endswith(COLLEGE_DOMAIN):
            flash(f'Only college IDs ending with {COLLEGE_DOMAIN} are allowed.', 'danger')
            return render_template('login.html')

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['user_name'] = user.name
            session['is_admin'] = user.is_admin
            flash(f'Welcome back, {user.name.split()[0]}!', 'success')
            return redirect(url_for('admin') if user.is_admin else url_for('index'))
        flash('Invalid credentials. Please try again.', 'danger')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        name     = request.form.get('name', '').strip()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')

        if not email.endswith(COLLEGE_DOMAIN):
            flash(f'Only college IDs ending with {COLLEGE_DOMAIN} are accepted.', 'danger')
            return render_template('register.html')
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('register.html')
        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('register.html')
        if User.query.filter_by(email=email).first():
            flash('An account with this email already exists.', 'danger')
            return render_template('register.html')

        user = User(
            email    = email,
            name     = name,
            password = generate_password_hash(password),
            is_admin = email in ADMIN_EMAILS
        )
        db.session.add(user)
        db.session.commit()
        flash('Account created! You can now log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))


# ─── Main routes ───────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    items = Item.query.filter_by(claimed=False).order_by(Item.id.desc()).all()
    user = current_user()
    return render_template('index.html', items=items, user=user)


@app.route('/my-claims')
@login_required
def my_claims():
    user = current_user()
    claimed_items = Item.query.filter_by(claimer_id=user.id).order_by(Item.claimed_at.desc()).all()
    reported_items = Item.query.filter_by(reporter_id=user.id).order_by(Item.created_at.desc()).all()
    return render_template('my_claims.html', claimed_items=claimed_items, reported_items=reported_items, user=user)


@app.route('/upload', methods=['POST'])
@login_required
def upload_item():
    name     = request.form.get('name', '').strip()
    location = request.form.get('location', '').strip()
    category = request.form.get('category', 'Generic')
    description = request.form.get('description', '').strip()

    if not name or not location:
        flash('Please fill in all required fields.', 'danger')
        return redirect(url_for('index'))

    file = request.files.get('photo')
    if not file or not file.filename:
        flash('Please upload a photo.', 'danger')
        return redirect(url_for('index'))
    if not allowed_file(file.filename):
        flash('Invalid file type.', 'danger')
        return redirect(url_for('index'))

    ext      = file.filename.rsplit('.', 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    user = current_user()
    item = Item(
        name            = name,
        location        = location,
        category        = category,
        description     = description,
        image_file      = filename,
        reporter_id     = user.id,
        secret_question = request.form.get('secret_question', '').strip(),
        secret_answer   = request.form.get('secret_answer', '').strip().lower(),
        serial_number   = None,
    )
    db.session.add(item)
    db.session.commit()
    flash('Item reported successfully! Thank you for helping someone out.', 'success')
    return redirect(url_for('index'))


@app.route('/verify/<int:item_id>', methods=['POST'])
@login_required
def verify_claim(item_id):
    item   = Item.query.get_or_404(item_id)
    answer = request.form.get('answer', '').strip().lower()
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    user = current_user()

    if item.claimed:
        msg = 'This item has already been claimed.'
        return jsonify({'success': False, 'message': msg}) if is_ajax else (flash(msg, 'warning'), redirect(url_for('index')))[1]

    correct = answer == (item.secret_answer or '').lower()

    if correct:
        item.claimed    = True
        item.claimer_id = user.id
        item.claimed_at = datetime.utcnow()
        db.session.commit()
        reporter = User.query.get(item.reporter_id)
        contact = reporter.email if reporter else 'N/A'
        msg = f'Verified! Contact the finder at: {contact}'
        return jsonify({'success': True, 'message': msg, 'contact': contact}) if is_ajax else (flash(msg, 'success'), redirect(url_for('index')))[1]
    else:
        msg = 'Incorrect answer. Please try again.'
        return jsonify({'success': False, 'message': msg}) if is_ajax else (flash(msg, 'danger'), redirect(url_for('index')))[1]


# ─── Admin routes ───────────────────────────────────────────────────────────────

@app.route('/admin')
@admin_required
def admin():
    all_items  = Item.query.order_by(Item.id.desc()).all()
    all_users  = User.query.order_by(User.created_at.desc()).all()
    active     = Item.query.filter_by(claimed=False).count()
    claimed    = Item.query.filter_by(claimed=True).count()
    user_count = User.query.count()
    user = current_user()
    return render_template('admin.html', items=all_items, users=all_users,
                           active=active, claimed=claimed, user_count=user_count, user=user)


@app.route('/admin/delete/<int:item_id>', methods=['POST'])
@admin_required
def admin_delete(item_id):
    item = Item.query.get_or_404(item_id)
    try:
        img_path = os.path.join(app.config['UPLOAD_FOLDER'], item.image_file)
        if os.path.exists(img_path):
            os.remove(img_path)
    except Exception:
        pass
    db.session.delete(item)
    db.session.commit()
    flash('Item deleted.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/unclaim/<int:item_id>', methods=['POST'])
@admin_required
def admin_unclaim(item_id):
    item = Item.query.get_or_404(item_id)
    item.claimed    = False
    item.claimer_id = None
    item.claimed_at = None
    db.session.commit()
    flash('Item marked as unclaimed.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/toggle-admin/<int:user_id>', methods=['POST'])
@admin_required
def toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    user.is_admin = not user.is_admin
    db.session.commit()
    flash(f"{'Granted' if user.is_admin else 'Removed'} admin for {user.email}", 'success')
    return redirect(url_for('admin'))


@app.route('/api/stats')
def stats():
    return jsonify({
        'active':  Item.query.filter_by(claimed=False).count(),
        'claimed': Item.query.filter_by(claimed=True).count(),
    })


# ─── Init ───────────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()
    # Create a default admin if none exists
    if not User.query.filter_by(email='admin@medicaps.ac.in').first():
        admin_user = User(
            email    = 'admin@medicaps.ac.in',
            name     = 'Campus Admin',
            password = generate_password_hash('admin123'),
            is_admin = True
        )
        db.session.add(admin_user)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)
