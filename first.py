import os
import cloudinary
import cloudinary.uploader
import cloudinary.api
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'fallback-dev-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

cloudinary.config(
    cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key    = os.environ.get('CLOUDINARY_API_KEY'),
    api_secret = os.environ.get('CLOUDINARY_API_SECRET')
)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'heic', 'heif'}
COLLEGE_DOMAIN     = '@medicaps.ac.in'
ADMIN_EMAILS       = {'admin@medicaps.ac.in', 'security@medicaps.ac.in'}

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle':  300,
    'pool_size':     5,
    'max_overflow':  2
}

db = SQLAlchemy(app)


# ─── Models ────────────────────────────────────────────────────────────────────

class User(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    email        = db.Column(db.String(200), unique=True, nullable=False)
    name         = db.Column(db.String(120), nullable=False)
    password     = db.Column(db.String(300), nullable=False)
    is_admin     = db.Column(db.Boolean, default=False)
    phone        = db.Column(db.String(20), nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    items_posted = db.relationship('Item', backref='reporter', lazy=True, foreign_keys='Item.reporter_id')
    claims       = db.relationship('Item', backref='claimer', lazy=True, foreign_keys='Item.claimer_id')


class Item(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(120), nullable=False)
    location     = db.Column(db.String(200), nullable=False)
    block        = db.Column(db.String(50), nullable=True)   # 'V Block' or 'Other'
    category     = db.Column(db.String(50), nullable=False, default='Generic')
    description  = db.Column(db.Text)
    image_file   = db.Column(db.String(500), nullable=False)
    claimed      = db.Column(db.Boolean, default=False)
    pending      = db.Column(db.Boolean, default=False)      # True when claim request submitted
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    reporter_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    claimer_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    claimed_at   = db.Column(db.DateTime, nullable=True)
    claim_requests = db.relationship('ClaimRequest', backref='item', lazy=True)


class ClaimRequest(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    item_id      = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    claimant_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    phone        = db.Column(db.String(20), nullable=False)   # Q1: contact number
    when_where   = db.Column(db.Text, nullable=False)         # Q2: when/where did you lose it
    proof_photo  = db.Column(db.String(500), nullable=True)   # optional photo proof
    status       = db.Column(db.String(20), default='pending')  # pending / approved / rejected
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    claimant     = db.relationship('User', backref='claim_requests')


# ─── Helpers ───────────────────────────────────────────────────────────────────

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
            flash(f'Only {COLLEGE_DOMAIN} emails are allowed.', 'danger')
            return render_template('login.html')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session['user_id']  = user.id
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
        phone    = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')

        if not email.endswith(COLLEGE_DOMAIN):
            flash(f'Only {COLLEGE_DOMAIN} emails are accepted.', 'danger')
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
            phone    = phone,
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
    user  = current_user()
    items = Item.query.filter_by(claimed=False).order_by(Item.id.desc()).all()
    return render_template('index.html', items=items, user=user)


@app.route('/my-claims')
@login_required
def my_claims():
    user           = current_user()
    claimed_items  = Item.query.filter_by(claimer_id=user.id).order_by(Item.claimed_at.desc()).all()
    reported_items = Item.query.filter_by(reporter_id=user.id).order_by(Item.created_at.desc()).all()
    my_requests    = ClaimRequest.query.filter_by(claimant_id=user.id).order_by(ClaimRequest.created_at.desc()).all()
    return render_template('my_claims.html',
                           claimed_items=claimed_items,
                           reported_items=reported_items,
                           my_requests=my_requests,
                           user=user)


# ─── Upload (finder posts item) ────────────────────────────────────────────────

@app.route('/upload', methods=['POST'])
@login_required
def upload_item():
    name        = request.form.get('name', '').strip()
    location    = request.form.get('location', '').strip()
    block       = request.form.get('block', 'Other')           # 'V Block' or 'Other'
    category    = request.form.get('category', 'Generic')
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

    try:
        result    = cloudinary.uploader.upload(file, format='jpg', transformation=[{'quality': 'auto'}])
        image_url = result['secure_url']
    except Exception as e:
        flash(f'Image upload failed: {str(e)}', 'danger')
        return redirect(url_for('index'))

    user = current_user()
    item = Item(
        name        = name,
        location    = location,
        block       = block,
        category    = category,
        description = description,
        image_file  = image_url,
        reporter_id = user.id,
    )
    db.session.add(item)
    db.session.commit()

    # Tell finder where to physically submit
    if block == 'V Block':
        flash('Item posted! Please physically submit it to Room 114, V Block.', 'success')
    else:
        flash('Item posted! Please physically submit it to the Guard Room.', 'success')

    return redirect(url_for('index'))


# ─── Claim request (loser submits claim) ───────────────────────────────────────

@app.route('/claim/<int:item_id>', methods=['POST'])
@login_required
def submit_claim(item_id):
    item     = Item.query.get_or_404(item_id)
    user     = current_user()
    is_ajax  = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if item.claimed:
        msg = 'This item has already been returned to its owner.'
        return jsonify({'success': False, 'message': msg}) if is_ajax else (flash(msg, 'warning'), redirect(url_for('index')))[1]

    if item.pending:
        msg = 'A claim is already pending admin review for this item.'
        return jsonify({'success': False, 'message': msg}) if is_ajax else (flash(msg, 'warning'), redirect(url_for('index')))[1]

    # Check if this user already submitted a claim for this item
    existing = ClaimRequest.query.filter_by(item_id=item_id, claimant_id=user.id, status='pending').first()
    if existing:
        msg = 'You have already submitted a claim for this item.'
        return jsonify({'success': False, 'message': msg}) if is_ajax else (flash(msg, 'warning'), redirect(url_for('index')))[1]

    phone      = request.form.get('phone', '').strip()
    when_where = request.form.get('when_where', '').strip()

    if not phone or not when_where:
        msg = 'Please fill in all required fields.'
        return jsonify({'success': False, 'message': msg}) if is_ajax else (flash(msg, 'danger'), redirect(url_for('index')))[1]

    # Optional proof photo upload
    proof_photo_url = None
    proof_file = request.files.get('proof_photo')
    if proof_file and proof_file.filename and allowed_file(proof_file.filename):
        try:
            result = cloudinary.uploader.upload(proof_file, format='jpg', transformation=[{'quality': 'auto'}])
            proof_photo_url = result['secure_url']
        except Exception:
            pass  # photo is optional, silently skip on failure

    claim = ClaimRequest(
        item_id     = item.id,
        claimant_id = user.id,
        phone       = phone,
        when_where  = when_where,
        proof_photo = proof_photo_url,
    )
    item.pending = True
    db.session.add(claim)
    db.session.commit()

    if item.block == 'V Block':
        pickup = 'Room 114, V Block'
    else:
        pickup = 'the Guard Room'
    msg = f'Claim submitted! If approved, go collect your item from {pickup}.'
    return jsonify({'success': True, 'message': msg}) if is_ajax else (flash(msg, 'success'), redirect(url_for('index')))[1]


# ─── Admin routes ───────────────────────────────────────────────────────────────

@app.route('/admin')
@admin_required
def admin():
    user           = current_user()
    all_items      = Item.query.order_by(Item.id.desc()).all()
    all_users      = User.query.order_by(User.created_at.desc()).all()
    claim_requests = ClaimRequest.query.filter_by(status='pending').order_by(ClaimRequest.created_at.desc()).all()
    active         = Item.query.filter_by(claimed=False).count()
    claimed        = Item.query.filter_by(claimed=True).count()
    user_count     = User.query.count()
    pending_count  = ClaimRequest.query.filter_by(status='pending').count()
    return render_template('admin.html',
                           items=all_items, users=all_users,
                           claim_requests=claim_requests,
                           active=active, claimed=claimed,
                           user_count=user_count,
                           pending_count=pending_count,
                           user=user)


@app.route('/admin/claim/approve/<int:claim_id>', methods=['POST'])
@admin_required
def approve_claim(claim_id):
    claim   = ClaimRequest.query.get_or_404(claim_id)
    item    = claim.item
    claimer = claim.claimant

    item.claimed    = True
    item.pending    = False
    item.claimer_id = claimer.id
    item.claimed_at = datetime.utcnow()
    claim.status    = 'approved'

    # Reject all other pending claims for the same item
    other_claims = ClaimRequest.query.filter_by(item_id=item.id, status='pending').all()
    for c in other_claims:
        c.status = 'rejected'

    db.session.commit()
    flash(f'Claim approved. "{item.name}" marked as returned to {claimer.name}.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/claim/reject/<int:claim_id>', methods=['POST'])
@admin_required
def reject_claim(claim_id):
    claim      = ClaimRequest.query.get_or_404(claim_id)
    item       = claim.item
    claim.status = 'rejected'

    # If no more pending claims, unset item.pending
    remaining = ClaimRequest.query.filter_by(item_id=item.id, status='pending').count()
    if remaining == 0:
        item.pending = False

    db.session.commit()
    flash('Claim rejected.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/delete/<int:item_id>', methods=['POST'])
@admin_required
def admin_delete(item_id):
    item = Item.query.get_or_404(item_id)
    # Delete associated claim requests first
    ClaimRequest.query.filter_by(item_id=item_id).delete()
    db.session.delete(item)
    db.session.commit()
    flash('Item deleted.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/unclaim/<int:item_id>', methods=['POST'])
@admin_required
def admin_unclaim(item_id):
    item            = Item.query.get_or_404(item_id)
    item.claimed    = False
    item.pending    = False
    item.claimer_id = None
    item.claimed_at = None
    db.session.commit()
    flash('Item marked as unclaimed.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/toggle-admin/<int:user_id>', methods=['POST'])
@admin_required
def toggle_admin(user_id):
    user          = User.query.get_or_404(user_id)
    user.is_admin = not user.is_admin
    db.session.commit()
    flash(f"{'Granted' if user.is_admin else 'Removed'} admin for {user.email}", 'success')
    return redirect(url_for('admin'))


# ─── API ────────────────────────────────────────────────────────────────────────

@app.route('/api/stats')
def stats():
    return jsonify({
        'active':  Item.query.filter_by(claimed=False).count(),
        'claimed': Item.query.filter_by(claimed=True).count(),
    })


# ─── Init ───────────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()
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
