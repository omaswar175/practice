from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import os
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'real-life-super-secret-key-123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///sports_booking.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Razorpay Configuration (Replace with your actual keys)
app.config['RAZORPAY_KEY_ID'] = os.environ.get('RAZORPAY_KEY_ID', 'rzp_test_1234567890')
app.config['RAZORPAY_KEY_SECRET'] = os.environ.get('RAZORPAY_KEY_SECRET', 'test_secret_key')

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
    contact_phone = db.Column(db.String(20), nullable=True)
    amenities = db.Column(db.String(255), nullable=True)  # Comma-separated: lights, parking, changing_room
    rating = db.Column(db.Float, default=4.5)
    external_api_id = db.Column(db.String(100), nullable=True)  # For tracking real ground APIs

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ground_id = db.Column(db.Integer, db.ForeignKey('ground.id'), nullable=False)
    booking_date = db.Column(db.String(20), nullable=False)
    time_slot = db.Column(db.String(20), nullable=False)
    payment_status = db.Column(db.String(20), default='Pending')  # Pending, Completed, Failed
    payment_id = db.Column(db.String(100), nullable=True)  # Razorpay Payment ID
    total_amount = db.Column(db.Integer, default=0)  # in paise
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('ground_id', 'booking_date', 'time_slot', name='unique_ground_booking_slot'),
    )

    ground = db.relationship('Ground', backref='bookings')

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    razorpay_order_id = db.Column(db.String(100), unique=True, nullable=False)
    razorpay_payment_id = db.Column(db.String(100), nullable=True)
    razorpay_signature = db.Column(db.String(255), nullable=True)
    amount = db.Column(db.Integer, nullable=False)  # in paise
    status = db.Column(db.String(20), default='pending')  # pending, success, failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    booking = db.relationship('Booking', backref='payments')
    user = db.relationship('User', backref='payments')

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
            # Calculate total amount (assuming 1 hour per slot)
            total_amount = ground.price_per_hour * 100  # Convert to paise
            
            new_booking = Booking(
                user_id=current_user.id,
                ground_id=ground.id,
                booking_date=date,
                time_slot=slot,
                payment_status='Pending',
                total_amount=total_amount
            )
            db.session.add(new_booking)
            db.session.commit()
            
            # Redirect to payment page
            return redirect(url_for('initiate_payment', booking_id=new_booking.id))
        except IntegrityError:
            db.session.rollback()
            error_message = f"Slot '{slot}' on {date} is already reserved!"

    return render_template('booking_form.html', ground=ground, error=error_message)

# ============================================================================
# PAYMENT ROUTES (Razorpay Integration)
# ============================================================================

@app.route('/payment/<int:booking_id>', methods=['GET'])
@login_required
def initiate_payment(booking_id):
    """Initiate payment for a booking"""
    booking = Booking.query.get_or_404(booking_id)
    
    if booking.user_id != current_user.id:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('my_bookings'))
    
    if booking.payment_status == 'Completed':
        flash('Payment already completed for this booking.', 'info')
        return redirect(url_for('my_bookings'))
    
    try:
        # Create Razorpay order (mock implementation)
        import uuid
        razorpay_order_id = f"order_{booking_id}_{uuid.uuid4().hex[:8]}"
        
        payment = Payment(
            booking_id=booking.id,
            user_id=current_user.id,
            razorpay_order_id=razorpay_order_id,
            amount=booking.total_amount,
            status='pending'
        )
        db.session.add(payment)
        db.session.commit()
        
        context = {
            'booking': booking,
            'ground': booking.ground,
            'order_id': razorpay_order_id,
            'amount': booking.total_amount,
            'user_email': current_user.email,
            'user_phone': '9876543210',  # Should be user's phone from profile
            'key_id': app.config['RAZORPAY_KEY_ID']
        }
        
        return render_template('payment.html', **context)
    except Exception as e:
        flash(f'Error initiating payment: {str(e)}', 'danger')
        return redirect(url_for('my_bookings'))

@app.route('/payment/verify', methods=['POST'])
@login_required
def verify_payment():
    """Verify payment signature from Razorpay"""
    try:
        data = request.get_json()
        payment_id = data.get('razorpay_payment_id')
        order_id = data.get('razorpay_order_id')
        signature = data.get('razorpay_signature')
        
        # Find payment record
        payment = Payment.query.filter_by(razorpay_order_id=order_id).first()
        if not payment:
            return jsonify({'success': False, 'message': 'Payment record not found'}), 404
        
        # In production, verify signature here using Razorpay SDK
        # For now, we'll accept the payment as verified (DEMO ONLY)
        # import hmac
        # import hashlib
        # message = f"{order_id}|{payment_id}"
        # signature_check = hmac.new(
        #     app.config['RAZORPAY_KEY_SECRET'].encode(),
        #     message.encode(),
        #     hashlib.sha256
        # ).hexdigest()
        
        # Update payment status
        payment.razorpay_payment_id = payment_id
        payment.razorpay_signature = signature
        payment.status = 'success'
        payment.updated_at = datetime.utcnow()
        
        # Update booking status
        booking = payment.booking
        booking.payment_status = 'Completed'
        booking.payment_id = payment_id
        booking.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Payment verified successfully'}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/payment/success/<int:booking_id>')
@login_required
def payment_success(booking_id):
    """Payment success page"""
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != current_user.id:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('my_bookings'))
    
    return render_template('payment_success.html', booking=booking)

@app.route('/payment/failed/<int:booking_id>')
@login_required
def payment_failed(booking_id):
    """Payment failed page"""
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != current_user.id:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('my_bookings'))
    
    return render_template('payment_failed.html', booking=booking)

@app.route('/my-bookings')
@login_required
def my_bookings():
    bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.updated_at.desc()).all()
    return render_template('my_bookings.html', bookings=bookings)

@app.route('/cancel-booking/<int:booking_id>', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id == current_user.id:
        # Can only cancel if payment not completed
        if booking.payment_status != 'Completed':
            db.session.delete(booking)
            db.session.commit()
            flash('Booking cancelled.', 'info')
        else:
            flash('Cannot cancel a paid booking. Please contact support.', 'warning')
    return redirect(url_for('my_bookings'))

# ============================================================================
# REAL TURF/GROUND API INTEGRATION
# ============================================================================

@app.route('/api/sync-grounds', methods=['POST'])
def sync_grounds_from_api():
    """Sync real grounds from external APIs"""
    try:
        # Example: Fetch from JustDial or custom API
        # For demo purposes, we'll show how to structure this
        external_grounds = fetch_real_grounds_from_api()
        
        for ground_data in external_grounds:
            # Check if ground already exists by external_api_id
            existing = Ground.query.filter_by(
                external_api_id=ground_data.get('api_id')
            ).first()
            
            if not existing:
                new_ground = Ground(
                    name=ground_data.get('name'),
                    sport_type=ground_data.get('sport_type'),
                    location=ground_data.get('location'),
                    price_per_hour=ground_data.get('price_per_hour', 500),
                    contact_phone=ground_data.get('phone'),
                    amenities=ground_data.get('amenities'),
                    rating=ground_data.get('rating', 4.5),
                    external_api_id=ground_data.get('api_id'),
                    status='Available'
                )
                db.session.add(new_ground)
        
        db.session.commit()
        return jsonify({'success': True, 'message': f'{len(external_grounds)} grounds synced'}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

def fetch_real_grounds_from_api():
    """
    Fetch real grounds from external APIs
    
    Available APIs:
    1. JustDial API - Sports Grounds listing
    2. Google Places API - Ground locations
    3. Custom Sports Booking APIs (Bounce, SportzWare, etc.)
    
    Example implementation using mock data:
    """
    try:
        import requests
        
        # Example: Using a custom or free Sports API
        # Replace with actual API endpoint and key
        
        API_KEY = os.environ.get('SPORTS_API_KEY', 'demo_key')
        API_ENDPOINT = 'https://api.example-sports.com/grounds'
        
        # This is a mock response - replace with actual API call
        response = {
            'grounds': [
                {
                    'api_id': 'ground_001',
                    'name': 'SportZone Football Field',
                    'sport_type': 'Football',
                    'location': 'Mumbai, Maharashtra',
                    'price_per_hour': 800,
                    'phone': '9876543210',
                    'amenities': 'lights, parking, changing_room',
                    'rating': 4.8
                },
                {
                    'api_id': 'ground_002',
                    'name': 'Elite Cricket Academy',
                    'sport_type': 'Cricket',
                    'location': 'Pune, Maharashtra',
                    'price_per_hour': 1200,
                    'phone': '9876543211',
                    'amenities': 'lights, parking, cafeteria',
                    'rating': 4.6
                }
            ]
        }
        
        # Uncomment below for real API call:
        # response = requests.get(
        #     API_ENDPOINT,
        #     headers={'Authorization': f'Bearer {API_KEY}'},
        #     timeout=10
        # ).json()
        
        return response.get('grounds', [])
    except Exception as e:
        print(f'Error fetching grounds from API: {str(e)}')
        return []

@app.route('/api/grounds/search', methods=['GET'])
def search_grounds():
    """Search grounds by location, sport type, or price"""
    try:
        location = request.args.get('location', '').strip()
        sport_type = request.args.get('sport_type', '').strip()
        max_price = request.args.get('max_price', type=int)
        min_price = request.args.get('min_price', type=int)
        
        query = Ground.query.filter_by(status='Available')
        
        if location:
            query = query.filter(Ground.location.ilike(f'%{location}%'))
        
        if sport_type:
            query = query.filter(Ground.sport_type.ilike(f'%{sport_type}%'))
        
        if min_price:
            query = query.filter(Ground.price_per_hour >= min_price)
        
        if max_price:
            query = query.filter(Ground.price_per_hour <= max_price)
        
        grounds = query.all()
        
        return jsonify({
            'success': True,
            'count': len(grounds),
            'grounds': [{
                'id': g.id,
                'name': g.name,
                'sport_type': g.sport_type,
                'location': g.location,
                'price_per_hour': g.price_per_hour,
                'amenities': g.amenities,
                'rating': g.rating,
                'contact_phone': g.contact_phone
            } for g in grounds]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/ground/<int:ground_id>/details')
def get_ground_details(ground_id):
    """Get detailed information about a ground"""
    ground = Ground.query.get_or_404(ground_id)
    
    return jsonify({
        'id': ground.id,
        'name': ground.name,
        'sport_type': ground.sport_type,
        'location': ground.location,
        'price_per_hour': ground.price_per_hour,
        'amenities': ground.amenities.split(',') if ground.amenities else [],
        'rating': ground.rating,
        'contact_phone': ground.contact_phone,
        'status': ground.status,
        'bookings_count': len(ground.bookings)
    })

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)