from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'real-life-super-secret-key-123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///sports_booking.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Login Manager Setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ---------------------------------------------------------------------------
# DATABASE MODELS
# ---------------------------------------------------------------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    bookings = db.relationship('Booking', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Ground(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    sport_type = db.Column(db.String(50), nullable=False)
    location = db.Column(db.String(100), nullable=False)
    price_per_hour = db.Column(db.Integer, default=500)
    status = db.Column(db.String(20), default='Available')

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ground_id = db.Column(db.Integer, db.ForeignKey('ground.id'), nullable=False)
    booking_date = db.Column(db.String(20), nullable=False)
    time_slot = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('ground_id', 'booking_date', 'time_slot', name='unique_ground_booking_slot'),
    )

    ground = db.relationship('Ground', backref='bookings')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------------------------------------------------------------------------
# ROUTES & LOGIC
# ---------------------------------------------------------------------------

@app.route('/')
def ground_list():
    grounds = Ground.query.filter_by(status='Available').all()
    return render_template('grounds.html', grounds=grounds)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

        if User.query.filter_by(email=email).first() or User.query.filter_by(username=username).first():
            flash('Username or Email already exists.', 'danger')
            return redirect(url_for('register'))

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for('ground_list'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('ground_list'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('ground_list'))

# API to fetch booked slots dynamically
@app.route('/api/booked-slots/<int:ground_id>/<date>')
def get_booked_slots(ground_id, date):
    booked = Booking.query.filter_by(ground_id=ground_id, booking_date=date).all()
    slots = [b.time_slot for b in booked]
    return jsonify({'booked_slots': slots})

@app.route('/book/<int:ground_id>', methods=['GET', 'POST'])
@login_required
def create_booking(ground_id):
    ground = Ground.query.get_or_404(ground_id)
    error_message = None

    if request.method == 'POST':
        date = request.form.get('date')
        slot = request.form.get('slot')

        try:
            new_booking = Booking(
                user_id=current_user.id,
                ground_id=ground.id,
                booking_date=date,
                time_slot=slot
            )
            db.session.add(new_booking)
            db.session.commit()
            flash('Booking confirmed successfully!', 'success')
            return redirect(url_for('my_bookings'))
        except IntegrityError:
            db.session.rollback()
            error_message = f"Slot '{slot}' on {date} is already reserved!"

    return render_template('booking_form.html', ground=ground, error=error_message)

@app.route('/my-bookings')
@login_required
def my_bookings():
    bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.created_at.desc()).all()
    return render_template('my_bookings.html', bookings=bookings)

@app.route('/cancel-booking/<int:booking_id>', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id == current_user.id:
        db.session.delete(booking)
        db.session.commit()
        flash('Booking cancelled.', 'info')
    return redirect(url_for('my_bookings'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)