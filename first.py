import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = 'change-this-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///snapfind.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

db = SQLAlchemy(app)


class Item(db.Model):
    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(120), nullable=False)
    location        = db.Column(db.String(200), nullable=False)
    contact         = db.Column(db.String(200), nullable=False)
    category        = db.Column(db.String(50),  nullable=False, default='Generic')
    image_file      = db.Column(db.String(200), nullable=False)
    secret_question = db.Column(db.String(300))
    secret_answer   = db.Column(db.String(300))
    serial_number   = db.Column(db.String(200))
    claimed         = db.Column(db.Boolean, default=False)



def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS



@app.route('/')
def index():
    items = Item.query.filter_by(claimed=False).order_by(Item.id.desc()).all()
    return render_template('index.html', items=items)


@app.route('/upload', methods=['POST'])
def upload_item():
    name     = request.form.get('name', '').strip()
    location = request.form.get('location', '').strip()
    contact  = request.form.get('contact', '').strip()
    category = request.form.get('category', 'Generic')

    if not name or not location or not contact:
        flash('Please fill in all required fields.', 'danger')
        return redirect(url_for('index'))

    file = request.files.get('photo')
    if not file or not file.filename:
        flash('Please upload a photo.', 'danger')
        return redirect(url_for('index'))

    if not allowed_file(file.filename):
        flash('Invalid file type. Please upload an image.', 'danger')
        return redirect(url_for('index'))

    ext      = file.filename.rsplit('.', 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    item = Item(
        name            = name,
        location        = location,
        contact         = contact,
        category        = category,
        image_file      = filename,
        secret_question = request.form.get('secret_question', '').strip() if category == 'Generic'     else None,
        secret_answer   = request.form.get('secret_answer',   '').strip().lower() if category == 'Generic'     else None,
        serial_number   = request.form.get('serial_number',   '').strip() if category == 'Electronics' else None,
    )
    db.session.add(item)
    db.session.commit()

    flash('Item reported successfully! Thank you.', 'success')
    return redirect(url_for('index'))


@app.route('/verify/<int:item_id>', methods=['POST'])
def verify_claim(item_id):
    item   = Item.query.get_or_404(item_id)
    answer = request.form.get('answer', '').strip().lower()
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if item.claimed:
        msg = 'This item has already been claimed.'
        if is_ajax:
            return jsonify({'success': False, 'message': msg})
        flash(msg, 'warning')
        return redirect(url_for('index'))

    if item.category == 'Electronics':
        correct = answer == (item.serial_number or '').lower()
    else:
        correct = answer == (item.secret_answer or '').lower()

    if correct:
        item.claimed = True
        db.session.commit()
        msg = f'Verified! Contact the finder at: {item.contact}'
        if is_ajax:
            return jsonify({'success': True, 'message': msg})
        flash(msg, 'success')
    else:
        msg = 'Incorrect answer. Please try again.'
        if is_ajax:
            return jsonify({'success': False, 'message': msg})
        flash(msg, 'danger')

    return redirect(url_for('index'))


@app.route('/api/stats')
def stats():
    return jsonify({
        'active':  Item.query.filter_by(claimed=False).count(),
        'claimed': Item.query.filter_by(claimed=True).count(),
    })



with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
