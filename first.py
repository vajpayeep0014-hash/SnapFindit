import os
import json
import base64
import mimetypes
import requests
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
db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
if not db_url:
    raise ValueError("DATABASE_URL is not set")

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
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
GEMINI_API_KEY     = os.environ.get('GEMINI_API_KEY', '')
print(f'[STARTUP] GEMINI_API_KEY loaded: {bool(GEMINI_API_KEY)}, length: {len(GEMINI_API_KEY)}')
GEMINI_URL         = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent'
GROQ_API_KEY       = os.environ.get('GROQ_API_KEY', '')
GROQ_URL           = 'https://api.groq.com/openai/v1/chat/completions'
print(f'[STARTUP] GROQ_API_KEY loaded: {bool(GROQ_API_KEY)}, length: {len(GROQ_API_KEY)}')

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
    id             = db.Column(db.Integer, primary_key=True)
    name           = db.Column(db.String(120), nullable=False)
    location       = db.Column(db.String(200), nullable=False)
    block          = db.Column(db.String(50), nullable=True)
    category       = db.Column(db.String(50), nullable=False, default='Generic')
    description    = db.Column(db.Text)
    image_file     = db.Column(db.String(500), nullable=False)
    claimed        = db.Column(db.Boolean, default=False)
    pending        = db.Column(db.Boolean, default=False)
    approved       = db.Column(db.Boolean, default=False)  # admin must approve before showing publicly
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    reporter_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    claimer_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    claimed_at     = db.Column(db.DateTime, nullable=True)
    claim_requests = db.relationship('ClaimRequest', backref='item', lazy=True)


class ClaimRequest(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    item_id     = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    claimant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    phone       = db.Column(db.String(20), nullable=False)
    when_where  = db.Column(db.Text, nullable=False)
    proof_photo = db.Column(db.String(500), nullable=True)
    status      = db.Column(db.String(20), default='pending')
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    claimant    = db.relationship('User', backref='claim_requests')


class FlaggedItem(db.Model):
    """Finder posts flagged as spam by AI — admin reviews here."""
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(120), nullable=False)
    location    = db.Column(db.String(200), nullable=False)
    block       = db.Column(db.String(50), nullable=True)
    category    = db.Column(db.String(50), nullable=False, default='Generic')
    description = db.Column(db.Text)
    image_file  = db.Column(db.String(500), nullable=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    ai_reason   = db.Column(db.Text)
    status      = db.Column(db.String(20), default='flagged')  # flagged/approved/deleted
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    reporter    = db.relationship('User', backref='flagged_items')


class FlaggedClaim(db.Model):
    """Claim requests flagged as spam by AI — admin reviews here."""
    id          = db.Column(db.Integer, primary_key=True)
    item_id     = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    claimant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    phone       = db.Column(db.String(20), nullable=False)
    when_where  = db.Column(db.Text, nullable=False)
    proof_photo = db.Column(db.String(500), nullable=True)
    ai_reason   = db.Column(db.Text)
    status      = db.Column(db.String(20), default='flagged')  # flagged/approved/deleted
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    item        = db.relationship('Item', backref='flagged_claims')
    claimant    = db.relationship('User', backref='flagged_claims')


# ─── Gemini helpers ────────────────────────────────────────────────────────────

def _gemini(prompt):
    """Raw Gemini text-only call."""
    resp = requests.post(
        f'{GEMINI_URL}?key={GEMINI_API_KEY}',
        json={'contents': [{'parts': [{'text': prompt}]}]},
        timeout=(3, 5)
    )
    return resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()


def _cloudinary_categorize(image_url):
    """Legacy — kept for compatibility. Tags now captured at upload time."""
    return []


def _parse_json(text):
    """Strip markdown fences and parse JSON."""
    if '```' in text:
        text = text.split('```')[1]
        if text.startswith('json'):
            text = text[4:]
    return json.loads(text.strip())


def check_item_spam(name, location, description):
    if not GEMINI_API_KEY:
        return {'flagged': False, 'reason': ''}
    try:
        prompt = f"""You are a spam filter for Medicaps University Lost & Found (SnapFind).
Decide if this found item report is spam, fake, or gibberish.

Item name: {name}
Location: {location}
Description: {description}

Flag if: name/location is gibberish, offensive, clearly fake, or a test entry like "asdf", "test123".
Do NOT flag: short but real descriptions, common items, incomplete descriptions.

Reply ONLY with JSON (no markdown):
{{"flagged": true or false, "reason": "one line reason if flagged, else empty string"}}"""
        data = _parse_json(_gemini(prompt))
        return {'flagged': bool(data.get('flagged')), 'reason': data.get('reason', '')}
    except Exception:
        return {'flagged': False, 'reason': ''}


def check_photo_matches_item(item_name, proof_photo_url, tags=None):
    """Use Cloudinary AI tags to check if proof photo matches the item name."""
    if not proof_photo_url:
        app.logger.warning('PHOTO_CHECK: skipped -- proof_photo_url is None')
        return {'flagged': False, 'reason': ''}
    try:
        if not tags:
            app.logger.warning('PHOTO_CHECK: no tags returned, skipping')
            return {'flagged': False, 'reason': ''}

        # Check if any tag loosely matches the item name
        item_words = set(item_name.lower().replace('-', ' ').split())
        tag_words  = set(' '.join(tags).lower().split())

        # Build common synonyms for known item types
        synonyms = {
            'earbuds': ['earphone', 'earbud', 'headphone', 'airpod', 'audio', 'music', 'wireless'],
            'phone':   ['mobile', 'smartphone', 'telephone', 'device', 'screen', 'iphone', 'android'],
            'laptop':  ['computer', 'notebook', 'macbook', 'keyboard', 'screen', 'device'],
            'wallet':  ['purse', 'cash', 'money', 'leather', 'card'],
            'watch':   ['clock', 'timepiece', 'wristwatch', 'smartwatch', 'band'],
            'bag':     ['backpack', 'handbag', 'luggage', 'sack', 'pouch'],
            'bottle':  ['water', 'flask', 'container', 'drink'],
            'id':      ['card', 'identity', 'badge', 'student'],
            'keys':    ['key', 'keychain', 'lock'],
        }

        # Expand item words with synonyms
        expanded = set(item_words)
        for key, syns in synonyms.items():
            if key in item_words or any(w in item_words for w in syns):
                expanded.update(syns)
                expanded.add(key)

        match = bool(expanded & tag_words)
        app.logger.info(f'PHOTO_CHECK: item_words={item_words}, tags={tags}, match={match}')

        if not match:
            return {
                'flagged': True,
                'reason': f'Photo does not appear to show a {item_name}. Detected: {", ".join(tags[:5])}'
            }
        return {'flagged': False, 'reason': ''}
    except Exception as e:
        app.logger.error(f'PHOTO_CHECK exception: {e}')
        return {'flagged': False, 'reason': ''}


def check_claim_spam(item_name, when_where):
    if not GEMINI_API_KEY:
        return {'flagged': False, 'reason': ''}
    try:
        prompt = f"""You are a fraud filter for Medicaps University Lost & Found (SnapFind).
Decide if this claim request looks fake or spam.

Item being claimed: {item_name}
Claimer says they lost it: {when_where}

Flag if: the when/where is gibberish, totally nonsensical, or obvious spam (e.g. "idk", "asdf", "abc").
Do NOT flag: short but plausible answers like "yesterday near canteen" or "Monday in library".

Reply ONLY with JSON (no markdown):
{{"flagged": true or false, "reason": "one line reason if flagged, else empty string"}}"""
        data = _parse_json(_gemini(prompt))
        return {'flagged': bool(data.get('flagged')), 'reason': data.get('reason', '')}
    except Exception:
        return {'flagged': False, 'reason': ''}


def gemini_chat(message):
    """Chatbot using Groq (Llama 3) — fast and free."""
    if not GROQ_API_KEY:
        return "The chatbot isn't configured yet. Please contact the admin at Room 114, V Block."
    try:
        system = """You are SnapFind Assistant, the helpful chatbot for Medicaps University's Lost & Found system."""

        resp = requests.post(
            GROQ_URL,
            headers={
                'Authorization': f'Bearer {GROQ_API_KEY}',
                'Content-Type': 'application/json'
            },
            json={
                'model': 'llama3-8b-8192',
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user',   'content': message}
                ],
                'max_tokens': 200,
                'temperature': 0.7
            },
            timeout=(3, 8)
        )
        resp_json = resp.json()
        if 'choices' not in resp_json:
            app.logger.error(f'GROQ_CHAT bad response: {resp_json}')
            raise ValueError(f'No choices in response')
        return resp_json['choices'][0]['message']['content'].strip()
    except Exception as e:
        app.logger.error(f'GROQ_CHAT error: {e}')
        return "Sorry, I'm having trouble right now. Please visit Room 114, V Block for help."


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
    items = Item.query.filter_by(claimed=False, approved=True).order_by(Item.id.desc()).all()
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


# ─── Upload ────────────────────────────────────────────────────────────────────

@app.route('/upload', methods=['POST'])
@login_required
def upload_item():
    name        = request.form.get('name', '').strip()
    location    = request.form.get('location', '').strip()
    block       = request.form.get('block', 'Other')
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

    # ── AI spam check ──
    ai = check_item_spam(name, location, description)
    if ai['flagged']:
        db.session.add(FlaggedItem(
            name=name, location=location, block=block, category=category,
            description=description, image_file=image_url,
            reporter_id=user.id, ai_reason=ai['reason']
        ))
        db.session.commit()
        flash('Your post was flagged for review. If it is genuine, admin will approve it shortly.', 'warning')
        return redirect(url_for('index'))

    db.session.add(Item(
        name=name, location=location, block=block, category=category,
        description=description, image_file=image_url, reporter_id=user.id
    ))
    db.session.commit()

    pickup = 'Room 114, V Block' if block == 'V Block' else 'the Guard Room'
    flash(f'Item submitted! Please physically hand it in to {pickup}. It will appear on the listings once admin verifies it.', 'success')
    return redirect(url_for('index'))


# ─── Claim request ─────────────────────────────────────────────────────────────

@app.route('/claim/<int:item_id>', methods=['POST'])
@login_required
def submit_claim(item_id):
    item    = Item.query.get_or_404(item_id)
    user    = current_user()
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def respond(success, msg):
        if is_ajax:
            return jsonify({'success': success, 'message': msg})
        flash(msg, 'success' if success else ('warning' if not success else 'danger'))
        return redirect(url_for('index'))

    if item.claimed:
        return respond(False, 'This item has already been returned to its owner.')
    if item.pending:
        return respond(False, 'A claim is already pending admin review for this item.')
    if ClaimRequest.query.filter_by(item_id=item_id, claimant_id=user.id, status='pending').first():
        return respond(False, 'You have already submitted a claim for this item.')

    phone      = request.form.get('phone', '').strip()
    when_where = request.form.get('when_where', '').strip()
    if not phone or not when_where:
        return respond(False, 'Please fill in all required fields.')

    # Optional proof photo
    proof_photo_url = None
    proof_tags      = []
    proof_file = request.files.get('proof_photo')
    app.logger.info(f'CLAIM_PHOTO: file={proof_file}, filename={proof_file.filename if proof_file else None}')
    if proof_file and proof_file.filename and allowed_file(proof_file.filename):
        try:
            r = cloudinary.uploader.upload(
                proof_file,
                format='jpg',
                transformation=[{'quality': 'auto'}],
                categorization='google_tagging',
                auto_tagging=0.5
            )
            proof_photo_url = r['secure_url']
            # Extract tags from upload response
            info = r.get('info', {})
            cat  = info.get('categorization', {}).get('google_tagging', {})
            proof_tags = [c['tag'] for c in cat.get('data', []) if c.get('confidence', 0) >= 0.5]
            app.logger.info(f'CLAIM_PHOTO: uploaded OK → tags={proof_tags}')
        except Exception as e:
            app.logger.error(f'CLAIM_PHOTO: upload failed → {e}')
    else:
        app.logger.warning(f'CLAIM_PHOTO: skipped — not a valid file')

    # ── AI spam check: text ──
    ai = check_claim_spam(item.name, when_where)
    if ai['flagged']:
        db.session.add(FlaggedClaim(
            item_id=item.id, claimant_id=user.id, phone=phone,
            when_where=when_where, proof_photo=proof_photo_url, ai_reason=ai['reason']
        ))
        db.session.commit()
        return respond(False, 'Please provide more specific details about when and where you lost the item.')

    # ── AI spam check: photo (if uploaded) ──
    if proof_photo_url:
        photo_check = check_photo_matches_item(item.name, proof_photo_url, tags=proof_tags)
        if photo_check['flagged']:
            db.session.add(FlaggedClaim(
                item_id=item.id, claimant_id=user.id, phone=phone,
                when_where=when_where, proof_photo=proof_photo_url,
                ai_reason=f'Photo mismatch: {photo_check["reason"]}'
            ))
            db.session.commit()
            return respond(False, 'The photo you uploaded does not appear to match the claimed item. Please upload a correct photo or leave it blank.')

    db.session.add(ClaimRequest(
        item_id=item.id, claimant_id=user.id,
        phone=phone, when_where=when_where, proof_photo=proof_photo_url
    ))
    item.pending = True
    db.session.commit()

    pickup = 'Room 114, V Block' if item.block == 'V Block' else 'the Guard Room'
    return respond(True, f'Claim submitted! If approved, collect your item from {pickup}.')


# ─── Chatbot ───────────────────────────────────────────────────────────────────

@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    data    = request.get_json()
    message = (data or {}).get('message', '').strip()
    if not message:
        return jsonify({'reply': 'Please type a message.'})
    return jsonify({'reply': gemini_chat(message)})


# ─── Admin routes ───────────────────────────────────────────────────────────────

@app.route('/admin')
@admin_required
def admin():
    user           = current_user()
    all_items      = Item.query.filter_by(approved=True).order_by(Item.id.desc()).all()
    pending_items  = Item.query.filter_by(approved=False).order_by(Item.id.desc()).all()
    all_users      = User.query.order_by(User.created_at.desc()).all()
    claim_requests = ClaimRequest.query.filter_by(status='pending').order_by(ClaimRequest.created_at.desc()).all()
    flagged_items  = FlaggedItem.query.filter_by(status='flagged').order_by(FlaggedItem.created_at.desc()).all()
    flagged_claims = FlaggedClaim.query.filter_by(status='flagged').order_by(FlaggedClaim.created_at.desc()).all()
    active         = Item.query.filter_by(claimed=False, approved=True).count()
    claimed        = Item.query.filter_by(claimed=True).count()
    user_count     = User.query.count()
    pending_count  = ClaimRequest.query.filter_by(status='pending').count()
    pending_items_count = Item.query.filter_by(approved=False).count()
    flagged_count  = (FlaggedItem.query.filter_by(status='flagged').count() +
                      FlaggedClaim.query.filter_by(status='flagged').count())
    return render_template('admin.html',
                           items=all_items,
                           pending_items=pending_items,
                           users=all_users,
                           claim_requests=claim_requests,
                           flagged_items=flagged_items,
                           flagged_claims=flagged_claims,
                           active=active, claimed=claimed,
                           user_count=user_count,
                           pending_count=pending_count,
                           pending_items_count=pending_items_count,
                           flagged_count=flagged_count,
                           user=user)


@app.route('/admin/item/approve/<int:item_id>', methods=['POST'])
@admin_required
def approve_item(item_id):
    item = Item.query.get_or_404(item_id)
    item.approved = True
    db.session.commit()
    flash(f'"{item.name}" approved and is now live on the listings.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/item/reject/<int:item_id>', methods=['POST'])
@admin_required
def reject_item(item_id):
    item = Item.query.get_or_404(item_id)
    ClaimRequest.query.filter_by(item_id=item_id).delete()
    db.session.delete(item)
    db.session.commit()
    flash('Item rejected and removed.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/claim/approve/<int:claim_id>', methods=['POST'])
@admin_required
def approve_claim(claim_id):
    claim = ClaimRequest.query.get_or_404(claim_id)
    item  = claim.item
    item.claimed = True; item.pending = False
    item.claimer_id = claim.claimant_id; item.claimed_at = datetime.utcnow()
    claim.status = 'approved'
    for c in ClaimRequest.query.filter_by(item_id=item.id, status='pending').all():
        c.status = 'rejected'
    db.session.commit()
    flash(f'Claim approved. "{item.name}" marked as returned to {claim.claimant.name}.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/claim/reject/<int:claim_id>', methods=['POST'])
@admin_required
def reject_claim(claim_id):
    claim = ClaimRequest.query.get_or_404(claim_id)
    claim.status = 'rejected'
    if ClaimRequest.query.filter_by(item_id=claim.item_id, status='pending').count() == 0:
        claim.item.pending = False
    db.session.commit()
    flash('Claim rejected.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/flagged-item/approve/<int:fid>', methods=['POST'])
@admin_required
def approve_flagged_item(fid):
    fi = FlaggedItem.query.get_or_404(fid)
    db.session.add(Item(
        name=fi.name, location=fi.location, block=fi.block,
        category=fi.category, description=fi.description,
        image_file=fi.image_file or '', reporter_id=fi.reporter_id,
        approved=True
    ))
    fi.status = 'approved'
    db.session.commit()
    flash(f'"{fi.name}" approved and moved to live listings.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/flagged-item/delete/<int:fid>', methods=['POST'])
@admin_required
def delete_flagged_item(fid):
    FlaggedItem.query.get_or_404(fid).status = 'deleted'
    db.session.commit()
    flash('Flagged item deleted.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/flagged-claim/approve/<int:fid>', methods=['POST'])
@admin_required
def approve_flagged_claim(fid):
    fc   = FlaggedClaim.query.get_or_404(fid)
    item = Item.query.get(fc.item_id)
    if not item:
        flash('Item no longer exists.', 'danger')
        return redirect(url_for('admin'))
    db.session.add(ClaimRequest(
        item_id=fc.item_id, claimant_id=fc.claimant_id,
        phone=fc.phone, when_where=fc.when_where, proof_photo=fc.proof_photo
    ))
    item.pending = True
    fc.status    = 'approved'
    db.session.commit()
    flash('Flagged claim approved and moved to pending claims.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/flagged-claim/delete/<int:fid>', methods=['POST'])
@admin_required
def delete_flagged_claim(fid):
    FlaggedClaim.query.get_or_404(fid).status = 'deleted'
    db.session.commit()
    flash('Flagged claim deleted.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/delete/<int:item_id>', methods=['POST'])
@admin_required
def admin_delete(item_id):
    item = Item.query.get_or_404(item_id)
    ClaimRequest.query.filter_by(item_id=item_id).delete()
    db.session.delete(item)
    db.session.commit()
    flash('Item deleted.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/unclaim/<int:item_id>', methods=['POST'])
@admin_required
def admin_unclaim(item_id):
    item = Item.query.get_or_404(item_id)
    item.claimed = False; item.pending = False
    item.claimer_id = None; item.claimed_at = None
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
    if not User.query.filter_by(email='admin@medicaps.ac.in').first():
        db.session.add(User(
            email    = 'admin@medicaps.ac.in',
            name     = 'Campus Admin',
            password = generate_password_hash('admin123'),
            is_admin = True
        ))
        db.session.commit()

if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)