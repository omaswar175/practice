from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///sports_booking.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ---------------------------------------------------------------------------
# DATABASE MODELS
# ---------------------------------------------------------------------------

# 1. User Account Table
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

# 2. Sports Ground Entity Table
class Ground(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    sport_type = db.Column(db.String(50), nullable=False) # e.g., Football, Cricket, Badminton
    location = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='Available')

# 3. Equipment Inventory Entity Table
class Equipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ground_id = db.Column(db.Integer, db.ForeignKey('ground.id'), nullable=False)
    item_name = db.Column(db.String(100), nullable=False) # e.g., Footballs, Rackets
    total_qty = db.Column(db.Integer, nullable=False)
    available_qty = db.Column(db.Integer, nullable=False)
    rental_fee = db.Column(db.Float, default=0.0)

# 4. Ground Booking Entity Table (Enforces Double-Booking Prevention)
class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ground_id = db.Column(db.Integer, db.ForeignKey('ground.id'), nullable=False)
    booking_date = db.Column(db.String(20), nullable=False) # Format: YYYY-MM-DD
    time_slot = db.Column(db.String(20), nullable=False) # e.g., "07:00-08:00"
    status = db.Column(db.String(20), default='Confirmed')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # DB UNIQUE constraint on ground_id + booking_date + time_slot stops duplicate reservations
    __table_args__ = (
        db.UniqueConstraint('ground_id', 'booking_date', 'time_slot', name='unique_ground_booking_slot'),
    )

    ground = db.relationship('Ground', backref='bookings')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------------------------------------------------------------------------
# BACKEND ROUTES & LOGIC
# ---------------------------------------------------------------------------

# Ground List View
@app.route('/')
def ground_list():
    grounds = Ground.query.filter_options() if hasattr(Ground, 'query') else Ground.query.filter_by(status='Available').all()
    return render_template('grounds.html', grounds=grounds)

# Booking Creation Logic
@app.route('/book/<int:ground_id>', methods=['GET', 'POST'])
@login_required
def create_booking(ground_id):
    ground = Ground.query.get_or_404(ground_id)
    error_message = None

    if request.method == 'POST':
        date = request.form.get('date')
        slot = request.form.get('slot')

        try:
            # Safely attempt database creation
            new_booking = Booking(
                user_id=current_user.id,
                ground_id=ground.id,
                booking_date=date,
                time_slot=slot
            )
            db.session.add(new_booking)
            db.session.commit()
            flash('Booking confirmed successfully!', 'success')
            return redirect(url_for('ground_list'))
        except IntegrityError:
            # Rollback database transaction when unique constraint fails
            db.session.rollback()
            error_message = f"Slot '{slot}' on {date} is already reserved! Please choose another slot."

    return render_template('booking_form.html', ground=ground, error=error_message)

# Admin Analytics View
@app.route('/analytics')
@login_required
def admin_analytics():
    if not current_user.is_admin:
        flash('Access restricted to admins.', 'danger')
        return redirect(url_for('ground_list'))

    # Calculate peak hours using SQLAlchemy group_by and count
    peak_slots = db.session.query(
        Booking.time_slot, 
        func.count(Booking.id).label('total_bookings')
    ).filter_by(status='Confirmed') \
     .group_by(Booking.time_slot) \
     .order_by(db.desc('total_bookings')).all()

    return render_template('analytics.html', peak_slots=peak_slots)

if __name__ == '__main__':
    with app.app_context():
        db.create_all() # Generates SQLite database tables automatically
    app.run(debug=True)