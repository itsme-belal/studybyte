import os
from dotenv import load_dotenv
load_dotenv()  # Loads .env file locally; safely ignored on Render (env vars are set there directly)

# ── eventlet monkey-patch: ONLY in production (Render).
# eventlet is incompatible with Python 3.12 locally; we use threading mode instead.
_is_production = os.environ.get('FLASK_ENV') == 'production'
if _is_production:
    import eventlet
    eventlet.monkey_patch()

from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime, timedelta
import random, string, re, uuid, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

# ── All secrets loaded from environment variables ──────────────────────────────
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-change-in-production')

# ── Database: Supabase PostgreSQL on Render, SQLite locally ───────────────────
database_url = os.environ.get('DATABASE_URL', 'sqlite:///studybyte_v5.db')
if database_url.startswith('postgres://'):
    # Supabase / Heroku-style URLs use postgres:// which SQLAlchemy requires as postgresql://
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,       # Reconnects dropped connections automatically
    'pool_recycle': 300,         # Recycle connections every 5 min (Supabase idle limit)
}

# ── File uploads: local disk for dev, /tmp for cloud ──────────────────────────
upload_folder = os.path.join(app.root_path, 'uploads')
try:
    os.makedirs(upload_folder, exist_ok=True)
except OSError:
    upload_folder = '/tmp/uploads'
    os.makedirs(upload_folder, exist_ok=True)
app.config['UPLOAD_FOLDER'] = upload_folder

db = SQLAlchemy(app)

# ── SocketIO: eventlet on Render, threading locally (Python 3.12 compatible) ──
_async_mode = 'eventlet' if _is_production else 'threading'
socketio = SocketIO(
    app,
    async_mode=_async_mode,
    cors_allowed_origins=os.environ.get('CORS_ORIGINS', '*'),
    logger=False,
    engineio_logger=False,
)

# ----------------- MODELS -----------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    studentId = db.Column(db.String(50), nullable=True)
    department = db.Column(db.String(100), nullable=True)
    rating = db.Column(db.Float, default=0.0)
    review_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='Active')
    
    is_verified = db.Column(db.Boolean, default=False)
    is_tutor_verified = db.Column(db.Boolean, default=False)
    grade_report = db.Column(db.String(255), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    created_date = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)
    
    # New Profile Fields
    theme_preference = db.Column(db.String(20), default='system')
    profile_pic = db.Column(db.String(255), nullable=True)
    cover_photo = db.Column(db.String(255), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    skills = db.Column(db.String(255), nullable=True)
    social_links = db.Column(db.Text, nullable=True) 
    education = db.Column(db.Text, nullable=True)

class Wallet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    balance = db.Column(db.Float, default=0.0)

class TransactionHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class TokenPurchaseRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    method = db.Column(db.String(50), nullable=False)
    mobile_number = db.Column(db.String(20), nullable=False)
    transaction_id = db.Column(db.String(100), nullable=False)
    bdt_amount = db.Column(db.Float, nullable=False)
    token_amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='Pending')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class WithdrawalRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    method = db.Column(db.String(50), nullable=False)
    mobile_number = db.Column(db.String(20), nullable=False)
    token_amount = db.Column(db.Float, nullable=False)
    bdt_amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='Pending')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class AvailabilitySlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tutor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.String(20), nullable=False)
    start_time = db.Column(db.String(10), nullable=False)
    end_time = db.Column(db.String(10), nullable=False)
    is_booked = db.Column(db.Boolean, default=False)
    is_frozen = db.Column(db.Boolean, default=False)
    tutor = db.relationship('User', foreign_keys=[tutor_id], backref='slots')

class TopicListing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tutor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Float, nullable=False)
    is_advertised = db.Column(db.Boolean, default=False)
    ad_expiry_time = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    tutor = db.relationship('User', backref='listings', foreign_keys=[tutor_id])

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    learner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    listing_id = db.Column(db.Integer, db.ForeignKey('topic_listing.id'), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey('availability_slot.id'), nullable=False)
    status = db.Column(db.String(20), default='Pending')
    
    # BUG FIX #2: Double-Blind Check-In System
    # Replaces the old easily-exploited meeting code.
    tutor_confirmed = db.Column(db.Boolean, default=False)
    learner_confirmed = db.Column(db.Boolean, default=False)
    tutor_join_time = db.Column(db.DateTime, nullable=True)
    learner_join_time = db.Column(db.DateTime, nullable=True)
    tutor_left_time = db.Column(db.DateTime, nullable=True)
    learner_left_time = db.Column(db.DateTime, nullable=True)
    # ----------------------------

    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    has_review = db.Column(db.Boolean, default=False)
    
    learner = db.relationship('User', foreign_keys=[learner_id])
    listing = db.relationship('TopicListing')
    slot = db.relationship('AvailabilitySlot')

class EscrowTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='Held')
    booking = db.relationship('Booking', backref='escrow_transactions', foreign_keys=[booking_id])

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=True)

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    sender = db.relationship('User', foreign_keys=[sender_id])

class CourseMaterial(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    uploader = db.relationship('User', foreign_keys=[uploaded_by])

class MeetingRoom(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    room_name = db.Column(db.String(100), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)
    action_url = db.Column(db.String(255), nullable=True)

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Dispute(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # Reporter
    reason = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='Open')
    admin_notes = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    booking = db.relationship('Booking')
    user = db.relationship('User')

class SystemFinance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    total_revenue = db.Column(db.Float, default=0.0)
    total_expenses = db.Column(db.Float, default=0.0)
    net_profit = db.Column(db.Float, default=0.0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

class SupportTicket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='Open') # strictly 'Open' or 'Closed'
    admin_reply = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('support_tickets', lazy=True))

_db_initialized = False

@app.before_request
def initialize_database():
    # Database wiped manually by admin; recreating on next request.
    global _db_initialized
    if not _db_initialized:
        try:
            db.create_all()
            # ── Auto-create admin from environment variables only ──────────────────
            # Set ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_NAME in your Render env vars.
            # If not set, no admin is created automatically (must be done manually).
            admin_email    = os.environ.get('ADMIN_EMAIL')
            admin_password = os.environ.get('ADMIN_PASSWORD')
            admin_name     = os.environ.get('ADMIN_NAME', 'Platform Admin')

            if admin_email and admin_password:
                admin = User.query.filter_by(role='admin').first()
                if not admin:
                    admin = User(
                        name=admin_name,
                        email=admin_email,
                        password_hash=generate_password_hash(admin_password),
                        role='admin',
                        status='Active',
                        is_verified=True
                    )
                    db.session.add(admin)
                    print(f"Admin account created: {admin_email}")
                else:
                    # Sync existing admin with environment variables
                    admin.email = admin_email
                    admin.name = admin_name
                    admin.password_hash = generate_password_hash(admin_password)
                    print(f"Admin account synced with environment variables: {admin_email}")
                db.session.commit()
            else:
                if not User.query.filter_by(role='admin').first():
                    print("WARNING: No admin account exists. Set ADMIN_EMAIL and ADMIN_PASSWORD env vars to auto-create one.")
            _db_initialized = True
        except Exception as e:
            print(f"CRITICAL DATABASE ERROR: {e}")
            _db_initialized = True  # Prevent infinite retry loops that drain database connections

# ----------------- UTILS -----------------

def update_system_finance(revenue=0.0, expense=0.0):
    try:
        sf = SystemFinance.query.first()
        if not sf:
            sf = SystemFinance(total_revenue=0.0, total_expenses=0.0, net_profit=0.0)
            db.session.add(sf)
        sf.total_revenue += revenue
        sf.total_expenses += expense
        sf.net_profit = sf.total_revenue - sf.total_expenses
        sf.last_updated = datetime.utcnow()
        db.session.commit()
    except Exception as e:
        print(f"Failed to update system finance: {e}")
        db.session.rollback()

def log_activity(user_id, action_type, description):
    try:
        activity = ActivityLog(user_id=user_id, action_type=action_type, description=description)
        db.session.add(activity)
        db.session.commit()
        # emit to admin room — safe-guarded for serverless environments
        try:
            socketio.emit('new_activity', {
                'action_type': action_type,
                'description': description,
                'time': 'Just now'
            }, room='admin_feed')
        except Exception:
            pass
    except Exception as e:
        print(f"Failed to log activity: {e}")

def send_verification_email(to_email, code):
    """
    Sends a 6-digit verification code via Brevo (Sendinblue) REST API.
    Uses HTTPS — no SMTP ports needed, works on Render free tier.
    Can send to ANY email address without domain verification.
    Requires BREVO_API_KEY and EMAIL_USER environment variables.
    """
    api_key = os.environ.get('BREVO_API_KEY')
    sender_email = os.environ.get('EMAIL_USER', 'noreply@studybyte.com')

    if not api_key:
        print("WARNING: BREVO_API_KEY not set. Email not sent.")
        return False

    try:
        import requests as _req
        response = _req.post(
            'https://api.brevo.com/v3/smtp/email',
            headers={
                'api-key': api_key,
                'Content-Type': 'application/json'
            },
            json={
                'sender': {'name': 'StudyByte', 'email': sender_email},
                'to': [{'email': to_email}],
                'subject': 'StudyByte Password Reset Code',
                'textContent': (
                    f'Hello,\n\n'
                    f'Your StudyByte password reset code is:\n\n'
                    f'  {code}\n\n'
                    f'This code expires in 10 minutes.\n\n'
                    f'If you did not request this, please ignore this email.\n\n'
                    f'— The StudyByte Team'
                )
            },
            timeout=10
        )
        if response.status_code in (200, 201):
            return True
        else:
            print(f"Brevo API Error: {response.status_code} {response.text}")
            return False
    except Exception as e:
        print(f"Brevo Email Error: {e}")
        return False

@app.context_processor
def inject_user():
    user = None
    wallet = None
    notifications = []
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if not user:
            # Stale session (e.g. DB was wiped) — clear it silently
            session.clear()
        else:
            wallet = Wallet.query.filter_by(user_id=user.id).first()
            # Retroactive fix: Create wallet if missing (especially for Google Auth users)
            if not wallet and user.role != 'admin':
                wallet = Wallet(user_id=user.id, balance=0)
                db.session.add(wallet)
                try:
                    db.session.commit()
                except:
                    db.session.rollback()
            
            notifications = Notification.query.filter_by(user_id=user.id, is_read=False).order_by(Notification.timestamp.desc()).all()
    return dict(current_user=user, wallet=wallet, unread_notifications=notifications)

def login_required(f):
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first.', 'error')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user:
            # User was deleted (e.g. DB wipe) — clear stale session
            session.clear()
            flash('Your session has expired. Please log in again.', 'error')
            return redirect(url_for('login'))
        if user.status == 'Suspended':
            session.clear()
            flash('Your account is suspended. Please contact support.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

def check_and_freeze_slots():
    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M')
    
    slots = AvailabilitySlot.query.filter_by(is_booked=False, is_frozen=False).all()
    modified = False
    for slot in slots:
        if slot.date < now_str or (slot.date == now_str and slot.end_time < time_str):
            slot.is_frozen = True
            modified = True
            notif = Notification(user_id=slot.tutor_id, message=f"Your course slot on {slot.date} has expired. Please add new time slots.", action_url='/tutor/availability')
            db.session.add(notif)
            
    expired_bookings = Booking.query.join(AvailabilitySlot).filter(Booking.status == 'Pending').all()
    for b in expired_bookings:
        if b.slot.date < now_str or (b.slot.date == now_str and b.slot.end_time < time_str):
            b.status = 'Cancelled'
            learner_wallet = Wallet.query.filter_by(user_id=b.learner_id).first()
            if learner_wallet:
                learner_wallet.balance += b.listing.price
                tx = TransactionHistory(user_id=b.learner_id, amount=b.listing.price, type='Refund', description=f"Auto-Refund: Tutor no response for BKG-{b.id}")
                db.session.add(tx)
                
                notif = Notification(user_id=b.learner_id, message=f"Booking BKG-{b.id} cancelled automatically (tutor unresponsive). Fully refunded.", action_url='/learner/dashboard')
                db.session.add(notif)
                notif_tutor = Notification(user_id=b.listing.tutor_id, message=f"Booking BKG-{b.id} expired automatically.", action_url='/tutor/dashboard')
                db.session.add(notif_tutor)
            modified = True
            
    # Session Auto-Close Logic
    active_bookings = Booking.query.join(AvailabilitySlot).filter(Booking.status == 'Confirmed').all()
    for b in active_bookings:
        if b.slot.date < now_str or (b.slot.date == now_str and b.slot.end_time < time_str):
            escrow = EscrowTransaction.query.filter_by(booking_id=b.id, status='Held').first()
            if b.learner_confirmed and b.tutor_confirmed:
                b.status = 'Completed'
                if escrow:
                    escrow.status = 'Released'
                    tutor_wallet = Wallet.query.filter_by(user_id=b.listing.tutor_id).first()
                    platform_fee = b.listing.price * 0.05
                    tutor_payout = b.listing.price - platform_fee
                    tutor_wallet.balance += tutor_payout
                    update_system_finance(revenue=platform_fee)
                    db.session.add(TransactionHistory(user_id=b.listing.tutor_id, amount=platform_fee, type='Commission', description=f"Platform Fee (BKG-{b.id})"))
                    db.session.add(TransactionHistory(user_id=b.listing.tutor_id, amount=tutor_payout, type='Received', description=f"Escrow released: {b.listing.title} (after 5% fee)"))
            elif b.tutor_confirmed and not b.learner_confirmed:
                # Learner no-show
                b.status = 'Completed'
                if escrow:
                    escrow.status = 'Released'
                    tutor_wallet = Wallet.query.filter_by(user_id=b.listing.tutor_id).first()
                    platform_fee = b.listing.price * 0.05
                    tutor_payout = b.listing.price - platform_fee
                    tutor_wallet.balance += tutor_payout
                    update_system_finance(revenue=platform_fee)
                    db.session.add(TransactionHistory(user_id=b.listing.tutor_id, amount=platform_fee, type='Commission', description=f"Platform Fee (BKG-{b.id})"))
                    db.session.add(TransactionHistory(user_id=b.listing.tutor_id, amount=tutor_payout, type='Received', description=f"Learner No-Show: {b.listing.title} (after 5% fee)"))
            elif b.learner_confirmed and not b.tutor_confirmed:
                # Tutor no-show
                b.status = 'Completed'
                if escrow:
                    escrow.status = 'Refunded'
                    learner_wallet = Wallet.query.filter_by(user_id=b.learner_id).first()
                    tutor_wallet = Wallet.query.filter_by(user_id=b.listing.tutor_id).first()
                    
                    # 40% penalty to tutor: 20% to learner, 20% to system
                    penalty = b.listing.price * 0.40
                    learner_comp = b.listing.price * 0.20
                    system_comp = b.listing.price * 0.20
                    
                    tutor_wallet.balance -= penalty
                    db.session.add(TransactionHistory(user_id=b.listing.tutor_id, amount=-penalty, type='Penalty', description=f"Tutor No-Show penalty: {b.listing.title}"))
                    
                    learner_wallet.balance += b.listing.price + learner_comp
                    db.session.add(TransactionHistory(user_id=b.learner_id, amount=b.listing.price + learner_comp, type='Refund', description=f"Tutor No-Show Full Refund + Compensation"))
                    
                    update_system_finance(revenue=system_comp)
            else:
                # Neither confirmed -> Stuck Payment system
                b.status = 'Payment Under Review'
                # Escrow remains Held
                
            modified = True

    if modified:
        # After freeze: notify any tutor who now has ZERO available slots
        try:
            db.session.flush()
            affected_tutors = set(slot.tutor_id for slot in slots if slot.is_frozen)
            for tutor_id in affected_tutors:
                remaining = AvailabilitySlot.query.filter_by(
                    tutor_id=tutor_id, is_booked=False, is_frozen=False
                ).count()
                if remaining == 0:
                    db.session.add(Notification(
                        user_id=tutor_id,
                        message="⚠️ You have NO available time slots. Your courses are hidden from learners until you add new slots.",
                        action_url='/tutor/availability'
                    ))
            db.session.commit()
        except:
            db.session.rollback()
            
    # Check Advertisement Expiry
    expired_ads = TopicListing.query.filter(TopicListing.is_advertised == True, TopicListing.ad_expiry_time <= now).all()
    if expired_ads:
        for ad in expired_ads:
            ad.is_advertised = False
            ad.ad_expiry_time = None
            notif = Notification(user_id=ad.tutor_id, message=f"Your advertisement for '{ad.title}' has expired.", action_url='/tutor/dashboard')
            db.session.add(notif)
        try:
            db.session.commit()
        except:
            db.session.rollback()

# ----------------- ROUTES -----------------


@app.route('/')
def index():
    check_and_freeze_slots()

    # Get tutors who have at least one available (not booked, not frozen) slot
    active_tutor_ids = [
        t[0] for t in db.session.query(AvailabilitySlot.tutor_id)
        .filter_by(is_booked=False, is_frozen=False).distinct().all()
    ]

    # Suggested = advertised courses from verified tutors WITH available slots
    suggested = (
        TopicListing.query
        .join(User)
        .filter(
            User.is_verified == True,
            TopicListing.tutor_id.in_(active_tutor_ids),
            TopicListing.is_advertised == True,
            TopicListing.ad_expiry_time > datetime.utcnow()
        )
        .order_by(TopicListing.id.desc())
        .limit(6).all()
    )

    # Pass current user for personalized navbar/greeting (None if not logged in)
    current_user_obj = None
    if 'user_id' in session:
        current_user_obj = User.query.get(session['user_id'])

    return render_template('index.html', suggested=suggested, current_user=current_user_obj)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        username = request.form.get('username', '').strip()
        student_id = request.form['student_id']
        email = request.form['email']
        password = request.form['password']
        department = request.form['department']
        role = request.form['role']
        
        if not username:
            flash('Username is required.', 'error')
            return redirect(url_for('register'))
        if User.query.filter_by(username=username).first():
            flash('Username already exists. Please choose a different one.', 'error')
            return redirect(url_for('register'))
            
        if not (6 <= len(password) <= 32):
            flash('Password must be between 6 and 32 characters.', 'error')
            return redirect(url_for('register'))
        if not re.search(r'[a-z]', password) or not re.search(r'[A-Z]', password):
            flash('Password must contain both uppercase and lowercase letters.', 'error')
            return redirect(url_for('register'))
        if not re.search(r'[0-9]', password):
            flash('Password must contain at least one number.', 'error')
            return redirect(url_for('register'))
        if not re.search(r'[@#_]', password):
            flash('Password must contain at least one special character (@, #, _).', 'error')
            return redirect(url_for('register'))
        if ' ' in password:
            flash('Password cannot contain spaces.', 'error')
            return redirect(url_for('register'))
        
        if not re.match(r'^\d{4}-[123]-\d{2}-\d{3}$', student_id):
            flash('Invalid Student ID format. Expected: YYYY-S-DDD-NNN (e.g. 2023-2-60-010)', 'error')
            return redirect(url_for('register'))
            
        if not email.endswith('@std.ewubd.edu'):
            flash('Email must end with @std.ewubd.edu', 'error')
            return redirect(url_for('register'))
            
        email_prefix = email.split('@')[0]
        if email_prefix != student_id:
            flash('The part of the email before @ must match your Student ID exactly.', 'error')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return redirect(url_for('register'))
            
        if role == 'tutor' and User.query.filter_by(name=name, role='tutor').first():
            flash('This tutor name is already registered. Please choose a unique name.', 'error')
            return redirect(url_for('register'))
            
        user = User(
            name=name, username=username, email=email, 
            password_hash=generate_password_hash(password),
            role=role,
            studentId=student_id, department=department,
            status='Active'
        )
        
        # ----------------------------
        # BUG FIX #1: Strict unverified nature for all new bounds.
        # Learners default to false, ensuring a swap later blocks them properly.
        user.is_verified = False
        user.is_tutor_verified = False
        
        if role == 'tutor':
            if 'grade_report' not in request.files:
                flash('Grade report is required for tutors.', 'error')
                return redirect(url_for('register'))
            file = request.files['grade_report']
            if file.filename == '' or not file.filename.lower().endswith('.pdf'):
                flash('Please upload a valid PDF grade report.', 'error')
                return redirect(url_for('register'))
            filename = secure_filename(f"{student_id}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            user.grade_report = filename
        # ----------------------------
            
        db.session.add(user)
        db.session.commit()
        
        wallet = Wallet(user_id=user.id, balance=0)
        db.session.add(wallet)
        db.session.commit()
        
        log_activity(user.id, "REGISTER", f"New user registered: {user.name} ({user.role})")
        
        # ---- MANDATORY VERIFICATION: Send code immediately, do NOT grant session yet ----
        code = ''.join(random.choices(string.digits, k=6))
        session['pending_user_id'] = user.id
        session['signup_email'] = user.email
        session['signup_code'] = code
        email_sent = send_verification_email(user.email, code)
        if email_sent:
            flash('Registration successful! A verification code has been sent to your university email. Please verify to access the platform.', 'success')
        else:
            flash('Registration successful but we could not send the verification email. Please contact support.', 'warning')
        return redirect(url_for('verify_signup'))
        
    return render_template('register.html')

@app.route('/send_verification')
@login_required
def send_verification():
    user = User.query.get(session['user_id'])
    if user.is_verified:
        flash("Already verified.", "info")
        return redirect(url_for('learner_dashboard'))
        
    code = ''.join(random.choices(string.digits, k=6))
    session['signup_email'] = user.email
    session['signup_code'] = code
    send_verification_email(user.email, code)
    flash('Verification code sent to your email.', 'success')
    return redirect(url_for('verify_signup'))

@app.route('/verify_signup', methods=['GET', 'POST'])
def verify_signup():
    email = session.get('signup_email')
    if not email:
        flash('Session expired. Please request a new code.', 'error')
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        code = request.form.get('code')
        if not code or code != session.get('signup_code'):
            flash('Invalid or expired code.', 'error')
            return redirect(url_for('verify_signup'))
            
        user = User.query.filter_by(email=email).first()
        if user:
            user.is_verified = True
            db.session.commit()
            
            # Check if ANY bonus already exists for this user to prevent double-claiming
            existing_bonus = TransactionHistory.query.filter_by(user_id=user.id, type='Bonus').first()
            
            # Bonus logic (only if they haven't received one yet)
            user_count = User.query.filter(User.is_verified == True).count()
            bonus = 100.0 if user_count <= 5 else 30.0
            
            wallet = Wallet.query.filter_by(user_id=user.id).first()
            if not wallet:
                wallet = Wallet(user_id=user.id, balance=0)
                db.session.add(wallet)
            
            actual_bonus_given = 0
            if bonus > 0 and not existing_bonus:
                wallet.balance += bonus
                bonus_history = TransactionHistory(user_id=user.id, amount=bonus, type='Bonus', description='Email Verification Bonus')
                db.session.add(bonus_history)
                actual_bonus_given = int(bonus)
            
            db.session.commit()
            
            # Clear pending session keys and grant full access
            session.pop('signup_email', None)
            session.pop('signup_code', None)
            pending_id = session.pop('pending_user_id', None)
            
            # Grant session (whether they came from registration or login)
            session['user_id'] = user.id
            session['role'] = user.role
            
            log_activity(user.id, "VERIFY", f"User {user.email} verified.")
            
            if actual_bonus_given > 0:
                flash(f'Email verified! Welcome to StudyByte 🎉 {actual_bonus_given} token bonus added to your wallet.', 'success')
            else:
                flash('Email verified! Welcome to StudyByte 🎉', 'success')
            
            if user.role == 'tutor':
                return redirect(url_for('tutor_dashboard'))
            return redirect(url_for('learner_dashboard'))
            
    return render_template('verify_signup.html', email=email)

@app.route('/tutor/listing/<int:listing_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_listing(listing_id):
    if session['role'] != 'tutor':
        return redirect(url_for('index'))
    listing = TopicListing.query.get_or_404(listing_id)
    if listing.tutor_id != session['user_id']:
        return "Unauthorized", 403
        
    categories = ['Computer Science', 'Mathematics', 'Physics', 'Business', 'Languages', 'Arts']
    if request.method == 'POST':
        listing.title = request.form['title']
        listing.description = request.form['description']
        listing.price = float(request.form['price'])
        listing.category = request.form['category']
        listing.updated_at = datetime.utcnow()
        
        db.session.commit()
        flash('Your listing was successfully updated!', 'success')
        return redirect(url_for('tutor_dashboard'))
        
    avail_slots = AvailabilitySlot.query.filter_by(
        tutor_id=listing.tutor_id, is_booked=False, is_frozen=False
    ).order_by(AvailabilitySlot.date, AvailabilitySlot.start_time).all()
    return render_template('edit_listing.html', listing=listing, categories=categories, avail_slots=avail_slots)

@app.route('/tutor/listing/<int:listing_id>/delete', methods=['POST'])
@login_required
def delete_listing(listing_id):
    if session['role'] != 'tutor':
        return "Unauthorized", 403
    listing = TopicListing.query.get_or_404(listing_id)
    if listing.tutor_id != session['user_id']:
        return "Unauthorized", 403
        
    active = Booking.query.filter_by(listing_id=listing.id).filter(Booking.status.in_(['Pending', 'Confirmed'])).first()
    if active:
        flash('Cannot delete listing with active bookings. Cancel them first.', 'error')
        return redirect(url_for('tutor_dashboard'))
        
    db.session.delete(listing)
    db.session.commit()
    flash('Course listing has been deleted.', 'success')
    return redirect(url_for('tutor_dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email_or_username = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        selected_role = request.form.get('role', 'learner')
        user = User.query.filter((User.email == email_or_username) | (User.username == email_or_username)).first()
        if user and check_password_hash(user.password_hash, password):
            if user.status == 'Suspended':
                flash('Your account has been suspended.', 'error')
                return redirect(url_for('login'))
            
            # ---- BLOCK unverified users: send code and redirect to verify ----
            if not user.is_verified and user.role != 'admin':
                code = ''.join(random.choices(string.digits, k=6))
                session['pending_user_id'] = user.id
                session['signup_email'] = user.email
                session['signup_code'] = code
                send_verification_email(user.email, code)
                flash('Your account is not verified yet. A new verification code has been sent to your email.', 'warning')
                return redirect(url_for('verify_signup'))
                
            session['user_id'] = user.id
            user.last_login = datetime.utcnow()
            
            # Admin accounts bypass role selection
            if user.role == 'admin':
                session['role'] = 'admin'
                return redirect(url_for('admin_dashboard'))
                
            if selected_role == 'admin' and user.role != 'admin':
                flash('You are not authorized as an admin.', 'error')
                return redirect(url_for('login'))
                
            # If they want to login as tutor but have no grade report
            if selected_role == 'tutor' and not user.grade_report:
                session['role'] = 'learner'
                user.role = 'learner'
                db.session.commit()
                flash('You must upload a grade report to access the tutor dashboard.', 'warning')
                return redirect(url_for('tutor_apply'))
                
            # Update user's active role context
            user.role = selected_role
            session['role'] = selected_role
            db.session.commit()
            
            flash('Login successful!', 'success')
            log_activity(user.id, "LOGIN", f"User logged in as {selected_role}")
            if selected_role == 'tutor':
                return redirect(url_for('tutor_dashboard'))
            else:
                return redirect(url_for('learner_dashboard'))
                
        flash('Invalid credentials.', 'error')
    return render_template('login.html')

@app.route('/google_auth', methods=['POST'])
def google_auth():
    token = request.form.get('credential')
    if not token:
        flash('Missing Google credentials.', 'error')
        return redirect(url_for('login'))
        
    try:
        # Try with clock skew tolerance (google-auth >= 2.3.0)
        try:
            idinfo = id_token.verify_oauth2_token(
                token, google_requests.Request(), GOOGLE_CLIENT_ID,
                clock_skew_in_seconds=10
            )
        except TypeError:
            # Fallback for older google-auth versions
            idinfo = id_token.verify_oauth2_token(
                token, google_requests.Request(), GOOGLE_CLIENT_ID
            )
        email = idinfo.get('email')
        name  = idinfo.get('name', email.split('@')[0] if email else 'User')
        
        # Enforce EWU emails
        if not (email.endswith('@std.ewubd.edu') or email.endswith('@ewubd.edu')):
            flash('Only authorized EWU GSuite accounts (@std.ewubd.edu or @ewubd.edu) are allowed.', 'error')
            return redirect(url_for('login'))
            
        user = User.query.filter_by(email=email).first()
        if not user:
            # Auto-register as Learner
            student_id = email.split('@')[0]
            base_username = student_id
            username = base_username
            counter = 1
            while User.query.filter_by(username=username).first():
                username = f"{base_username}{counter}"
                counter += 1
                
            # Create a secure random password for them
            random_pw = ''.join(random.choices(string.ascii_letters + string.digits, k=16)) + 'A1@'
            user = User(
                name=name, username=username, email=email,
                password_hash=generate_password_hash(random_pw),
                role='learner',
                studentId=student_id if email.endswith('@std.ewubd.edu') else 'Faculty',
                department='Unknown',
                status='Active'
            )
            user.is_verified = True
            db.session.add(user)
            db.session.flush()  # flush to get user.id without committing

            # Create wallet with signup bonus
            user_count = User.query.count()
            bonus = 100.0 if user_count <= 5 else 0.0
            wallet = Wallet(user_id=user.id, balance=bonus)
            db.session.add(wallet)
            if bonus > 0:
                db.session.add(TransactionHistory(
                    user_id=user.id, amount=bonus,
                    type='Bonus', description='Sign-up Bonus'
                ))
            db.session.commit()

            flash('Google Sign-Up successful! Welcome to StudyByte 🎉', 'success')
            log_activity(user.id, "REGISTER", f"Google Sign-up: {user.name}")
        else:
            if user.status == 'Suspended':
                flash('Your account has been suspended.', 'error')
                return redirect(url_for('login'))
            
            # Ensure they are marked as verified if they log in via Google
            if not user.is_verified:
                user.is_verified = True
                db.session.commit()
            
            flash('Google Sign-In successful!', 'success')
            log_activity(user.id, "LOGIN", "User logged in via Google")
            
        session['user_id'] = user.id
        session['role'] = user.role
        
        if user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif user.role == 'tutor':
            return redirect(url_for('tutor_dashboard'))
        else:
            return redirect(url_for('learner_dashboard'))

    except ValueError as e:
        flash(f'Google token error: {str(e)[:80]}. Please try again.', 'error')
        return redirect(url_for('login'))
    except Exception as e:
        flash('Google Sign-In failed. Please try again or use email login.', 'error')
        return redirect(url_for('login'))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        if 'cancel' in request.form:
            session.pop('reset_email', None)
            session.pop('reset_code', None)
            session.pop('reset_code_time', None)
            return redirect(url_for('forgot_password'))

        if 'email' in request.form:
            email = request.form.get('email', '').strip()
            # Must be valid EWU email
            if not (email.endswith('@std.ewubd.edu') or email.endswith('@ewubd.edu')):
                flash('Please use a valid EWU email address.', 'error')
                return redirect(url_for('forgot_password'))
                
            user = User.query.filter_by(email=email).first()
            if user:
                code = ''.join(random.choices(string.digits, k=6))
                session['reset_email'] = email
                session['reset_code'] = code
                session['reset_code_time'] = datetime.utcnow().timestamp()
                # Send email using the reusable SMTP function
                email_sent = send_verification_email(email, code)
                
                if email_sent:
                    flash('Verification code sent securely to your university email.', 'success')
                else:
                    flash('Failed to deliver email. Check console or SMTP configuration.', 'warning')
            else:
                flash('No account found with that email address.', 'error')
            return redirect(url_for('forgot_password'))
            
        elif 'code' in request.form:
            code = request.form.get('code')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            email = session.get('reset_email')
            
            if not email or session.get('reset_code') != code:
                flash('Invalid verification code.', 'error')
                return redirect(url_for('forgot_password'))
                
            # Check for expiration (10 minutes = 600 seconds)
            reset_time = session.get('reset_code_time', 0)
            if datetime.utcnow().timestamp() - reset_time > 600:
                session.pop('reset_email', None)
                session.pop('reset_code', None)
                session.pop('reset_code_time', None)
                flash('Verification code has expired. Please request a new one.', 'error')
                return redirect(url_for('forgot_password'))
                
            if new_password != confirm_password:
                flash('Passwords do not match.', 'error')
                return redirect(url_for('forgot_password'))
                
            if not (6 <= len(new_password) <= 32):
                flash('Password must be between 6 and 32 characters.', 'error')
                return redirect(url_for('forgot_password'))
            if not re.search(r'[a-z]', new_password) or not re.search(r'[A-Z]', new_password):
                flash('Password must contain both uppercase and lowercase letters.', 'error')
                return redirect(url_for('forgot_password'))
            if not re.search(r'[0-9]', new_password):
                flash('Password must contain at least one number.', 'error')
                return redirect(url_for('forgot_password'))
            if not re.search(r'[@#_]', new_password):
                flash('Password must contain at least one special character (@, #, _).', 'error')
                return redirect(url_for('forgot_password'))
            if ' ' in new_password:
                flash('Password cannot contain spaces.', 'error')
                return redirect(url_for('forgot_password'))
                
            user = User.query.filter_by(email=email).first()
            if user:
                user.password_hash = generate_password_hash(new_password)
                db.session.commit()
                session.pop('reset_email', None)
                session.pop('reset_code', None)
                session.pop('reset_code_time', None)
                flash('Your password has been securely updated. You can now login.', 'success')
                return redirect(url_for('login'))
                
    return render_template('forgot_password.html')

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    user = User.query.get(session['user_id'])
    current_pw = request.form.get('current_password')
    new_pw = request.form.get('new_password')
    confirm_pw = request.form.get('confirm_password')
    
    if not check_password_hash(user.password_hash, current_pw):
        flash('Current password is incorrect!', 'error')
        return redirect(url_for('view_profile', user_id=user.id))
        
    if new_pw != confirm_pw:
        flash('New passwords do not match!', 'error')
        return redirect(url_for('view_profile', user_id=user.id))
        
    if not (6 <= len(new_pw) <= 32):
        flash('Password must be between 6 and 32 characters.', 'error')
        return redirect(url_for('view_profile', user_id=user.id))
    if not re.search(r'[a-z]', new_pw) or not re.search(r'[A-Z]', new_pw):
        flash('Password must contain both uppercase and lowercase letters.', 'error')
        return redirect(url_for('view_profile', user_id=user.id))
    if not re.search(r'[0-9]', new_pw):
        flash('Password must contain at least one number.', 'error')
        return redirect(url_for('view_profile', user_id=user.id))
    if not re.search(r'[@#_]', new_pw):
        flash('Password must contain at least one special character (@, #, _).', 'error')
        return redirect(url_for('view_profile', user_id=user.id))
    if ' ' in new_pw:
        flash('Password cannot contain spaces.', 'error')
        return redirect(url_for('view_profile', user_id=user.id))
        
    user.password_hash = generate_password_hash(new_pw)
    db.session.commit()
    flash('Your password has been securely updated!', 'success')
    return redirect(url_for('view_profile', user_id=user.id))

@app.route('/set_theme', methods=['POST'])
@login_required
def set_theme():
    user = User.query.get(session['user_id'])
    theme = request.json.get('theme', 'system')
    if theme in ['light', 'dark', 'system']:
        user.theme_preference = theme
        db.session.commit()
        return jsonify({'status': 'success', 'theme': theme})
    return jsonify({'status': 'error'})

@app.route('/notifications/read', methods=['POST'])
@login_required
def read_notifications():
    notifications = Notification.query.filter_by(user_id=session['user_id'], is_read=False).all()
    for n in notifications:
        n.is_read = True
    db.session.commit()
    return jsonify({'status': 'success'})

@app.route('/logout')
def logout():
    user_id = session.get('user_id')
    if user_id:
        log_activity(user_id, "LOGOUT", "User logged out")
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('index'))

@app.route('/switch_role/<role>')
@login_required
def switch_role(role):
    user = User.query.get(session['user_id'])
    if user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
        
    if role == 'tutor' and not user.grade_report:
        return redirect(url_for('tutor_apply'))
        
    if role == 'tutor':
        existing_tutor = User.query.filter_by(name=user.name, role='tutor').first()
        if existing_tutor and existing_tutor.id != user.id:
            flash('Your current name belongs to an existing tutor. Please update your profile name first.', 'error')
            return redirect(url_for('dashboard'))

    if role in ['learner', 'tutor']:
        user.role = role
        session['role'] = role
        db.session.commit()
        flash(f'Switched to {role.capitalize()} mode.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/tutor/apply', methods=['GET', 'POST'])
@login_required
def tutor_apply():
    user = User.query.get(session['user_id'])
    if user.grade_report:
        existing_tutor = User.query.filter_by(name=user.name, role='tutor').first()
        if existing_tutor and existing_tutor.id != user.id:
            flash('Your name is used by an existing tutor. Please manually update your profile name.', 'error')
            return redirect(url_for('dashboard'))
            
        user.role = 'tutor'
        session['role'] = 'tutor'
        db.session.commit()
        return redirect(url_for('tutor_dashboard'))
        
    if request.method == 'POST':
        if 'grade_report' not in request.files:
            flash('Grade report is required.', 'error')
            return redirect(url_for('tutor_apply'))
            
        existing_tutor = User.query.filter_by(name=user.name, role='tutor').first()
        if existing_tutor and existing_tutor.id != user.id:
            flash('Your name is heavily identical to an active tutor. Please change your name in Profile before applying.', 'error')
            return redirect(url_for('tutor_apply'))
            
        file = request.files['grade_report']
        if file.filename == '' or not file.filename.lower().endswith('.pdf'):
            flash('Please upload a valid PDF grade report.', 'error')
            return redirect(url_for('tutor_apply'))
            
        filename = secure_filename(f"{user.studentId}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        user.grade_report = filename
        user.is_tutor_verified = False
        user.role = 'tutor'
        session['role'] = 'tutor'
        db.session.commit()
        
        flash('Application submitted! Your tutor account is pending admin review.', 'success')
        return redirect(url_for('tutor_dashboard'))
        
    return render_template('tutor_onboarding.html')

@app.route('/dashboard')
@login_required
def dashboard():
    if session['role'] == 'tutor':
        return redirect(url_for('tutor_dashboard'))
    elif session['role'] == 'admin':
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('learner_dashboard'))

@app.route('/learner/dashboard')
@login_required
def learner_dashboard():
    user = User.query.get(session['user_id'])
    
    # Auto-expire pending sessions gracefully
    for b in Booking.query.filter_by(learner_id=user.id, status='Pending').all():
        try:
            dt_obj = datetime.strptime(f"{b.slot.date} {b.slot.start_time}", "%Y-%m-%d %H:%M")
            if dt_obj < datetime.now():
                b.status = 'Expired'
        except:
            pass
    db.session.commit()
    
    upcoming = Booking.query.filter_by(learner_id=user.id).filter(Booking.status.in_(['Pending', 'Confirmed'])).all()
    past = Booking.query.filter_by(learner_id=user.id).filter(Booking.status.in_(['Completed', 'Cancelled', 'Expired'])).all()
    # Suggested: advertised, verified, has available slots — same filter as marketplace
    active_tutor_ids = [
        t[0] for t in db.session.query(AvailabilitySlot.tutor_id)
        .filter_by(is_booked=False, is_frozen=False).distinct().all()
    ]
    suggested = (
        TopicListing.query
        .join(User)
        .filter(
            User.is_verified == True,
            TopicListing.tutor_id.in_(active_tutor_ids),
            TopicListing.is_advertised == True
        )
        .order_by(TopicListing.id.desc())
        .limit(5).all()
    )
    return render_template('learner_dashboard.html', upcoming_bookings=upcoming, past_bookings=past, suggested_listings=suggested, user=user)

@app.route('/tutor/dashboard')
@login_required
def tutor_dashboard():
    user = User.query.get(session['user_id'])
    listings = TopicListing.query.filter_by(tutor_id=user.id).all()
    
    for l in listings:
        for b in Booking.query.filter_by(listing_id=l.id, status='Pending').all():
            try:
                dt_obj = datetime.strptime(f"{b.slot.date} {b.slot.start_time}", "%Y-%m-%d %H:%M")
                if dt_obj < datetime.now():
                    b.status = 'Expired'
            except:
                pass
    db.session.commit()
    
    listing_ids = [l.id for l in listings]
    bookings = Booking.query.filter(Booking.listing_id.in_(listing_ids)).order_by(Booking.timestamp.desc()).all()
    
    escrow_total = sum([tx.amount for tx in EscrowTransaction.query.filter(EscrowTransaction.booking_id.in_([b.id for b in bookings]), EscrowTransaction.status == 'Held').all()])
    
    return render_template('tutor_dashboard.html', listings=listings, bookings=bookings, escrow_balance=escrow_total, user=user)

@app.route('/tutor/availability', methods=['GET', 'POST'])
@login_required
def manage_availability():
    if session['role'] != 'tutor':
        return redirect(url_for('dashboard'))
    user = User.query.get(session['user_id'])
    if not user.is_verified:
        flash('You must be securely verified by an admin to manage active availability.', 'error')
        return redirect(url_for('tutor_dashboard'))
        
    if request.method == 'POST':
        date = request.form['date']
        start_time = request.form['start_time']
        end_time = request.form['end_time']
        
        try:
            dt_start = datetime.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M")
            dt_end = datetime.strptime(f"{date} {end_time}", "%Y-%m-%d %H:%M")
            
            if dt_start < datetime.now():
                flash('Cannot set availability in the past.', 'error')
                return redirect(url_for('manage_availability'))
                
            duration = (dt_end - dt_start).total_seconds() / 60
            if duration < 5:
                flash('Minimum duration is 5 minutes.', 'error')
                return redirect(url_for('manage_availability'))
            if duration > 300:
                flash('Maximum duration is 5 hours.', 'error')
                return redirect(url_for('manage_availability'))
                
        except ValueError:
            flash('Invalid date or time format.', 'error')
            return redirect(url_for('manage_availability'))
        
        slot = AvailabilitySlot(tutor_id=user.id, date=date, start_time=start_time, end_time=end_time)
        db.session.add(slot)
        db.session.commit()
        flash('Availability slot added.', 'success')
        return redirect(url_for('manage_availability'))
        
    slots = AvailabilitySlot.query.filter_by(tutor_id=user.id).order_by(AvailabilitySlot.date).all()
    return render_template('manage_availability.html', slots=slots)

@app.route('/tutor/availability/delete/<int:slot_id>', methods=['POST'])
@login_required
def delete_availability(slot_id):
    slot = AvailabilitySlot.query.get_or_404(slot_id)
    if slot.tutor_id != session['user_id']:
        return "Unauthorized", 403
    if slot.is_booked:
        flash('Cannot delete a booked slot.', 'error')
    else:
        db.session.delete(slot)
        db.session.commit()
        flash('Slot deleted.', 'success')
    return redirect(url_for('manage_availability'))

@app.route('/admin')
@login_required
def admin_dashboard():
    if session['role'] != 'admin':
        return redirect(url_for('index'))
        
    all_purchases = TransactionHistory.query.filter_by(type='Purchase').all()
    all_fees = TransactionHistory.query.filter_by(type='Penalty').all()
    
    total_revenue_tokens = sum([p.amount for p in all_purchases])
    platform_fees_collected = sum([abs(p.amount) for p in all_fees])
    total_tokens_spent = db.session.query(db.func.sum(TransactionHistory.amount)).filter(TransactionHistory.amount < 0, TransactionHistory.type == 'Payment').scalar() or 0
    total_tokens_spent = abs(total_tokens_spent)

    total_listings = TopicListing.query.count()
    active_tutors_ids = [t[0] for t in db.session.query(AvailabilitySlot.tutor_id).filter_by(is_booked=False, is_frozen=False).distinct().all()]
    active_courses = TopicListing.query.filter(TopicListing.tutor_id.in_(active_tutors_ids)).count()
    hidden_courses = total_listings - active_courses

    payout_bdt = db.session.query(db.func.sum(WithdrawalRequest.bdt_amount)).filter(WithdrawalRequest.status.in_(['Approved', 'Completed', 'Sent'])).scalar() or 0.0
    bonus_tokens = db.session.query(db.func.sum(db.func.abs(TransactionHistory.amount))).filter_by(type='Bonus').scalar() or 0.0
    bonus_bdt = bonus_tokens * 0.50
    total_expense_bdt = payout_bdt + bonus_bdt
    
    token_sell_bdt = db.session.query(db.func.sum(TokenPurchaseRequest.bdt_amount)).filter(TokenPurchaseRequest.status.in_(['Approved', 'Completed'])).scalar() or 0.0
    ad_tokens = db.session.query(db.func.sum(db.func.abs(TransactionHistory.amount))).filter_by(type='Advertisement').scalar() or 0.0
    ad_bdt = ad_tokens * 0.50
    penalty_tokens = db.session.query(db.func.sum(db.func.abs(TransactionHistory.amount))).filter_by(type='Penalty').scalar() or 0.0
    penalty_bdt = penalty_tokens * 0.50
    comm_tokens = db.session.query(db.func.sum(db.func.abs(TransactionHistory.amount))).filter_by(type='Commission').scalar() or 0.0
    platform_fee_bdt = comm_tokens * 0.50
    
    total_earning_bdt = token_sell_bdt + ad_bdt + platform_fee_bdt + penalty_bdt
    net_profit = total_earning_bdt - total_expense_bdt

    # 24h Stats logic
    now = datetime.utcnow()
    day_ago = now - timedelta(hours=24)
    
    p24h_sum = db.session.query(db.func.sum(TokenPurchaseRequest.bdt_amount)).filter(TokenPurchaseRequest.timestamp >= day_ago, TokenPurchaseRequest.status.in_(['Approved', 'Completed'])).scalar() or 0.0
    b24h_tokens = db.session.query(db.func.sum(db.func.abs(TransactionHistory.amount))).filter(TransactionHistory.timestamp >= day_ago, TransactionHistory.type == 'Bonus').scalar() or 0.0
    b24h_bdt = b24h_tokens * 0.50
    w24h_bdt = db.session.query(db.func.sum(WithdrawalRequest.bdt_amount)).filter(WithdrawalRequest.timestamp >= day_ago, WithdrawalRequest.status.in_(['Approved', 'Completed', 'Sent'])).scalar() or 0.0
    a24h_tokens = db.session.query(db.func.sum(db.func.abs(TransactionHistory.amount))).filter(TransactionHistory.timestamp >= day_ago, TransactionHistory.type == 'Advertisement').scalar() or 0.0
    a24h_bdt = a24h_tokens * 0.50
    fee24h_tokens = db.session.query(db.func.sum(db.func.abs(TransactionHistory.amount))).filter(TransactionHistory.timestamp >= day_ago, TransactionHistory.type == 'Commission').scalar() or 0.0
    fee24h_bdt = fee24h_tokens * 0.50
    pen24h_tokens = db.session.query(db.func.sum(db.func.abs(TransactionHistory.amount))).filter(TransactionHistory.timestamp >= day_ago, TransactionHistory.type == 'Penalty').scalar() or 0.0
    pen24h_bdt = pen24h_tokens * 0.50
    
    earn24h = p24h_sum + a24h_bdt + fee24h_bdt + pen24h_bdt
    exp24h = w24h_bdt + b24h_bdt
    profit24h = earn24h - exp24h
    
    stats_24h = {
        'token_sell': p24h_sum,
        'bonus': b24h_bdt,
        'withdrawals': w24h_bdt,
        'ads': a24h_bdt,
        'fees': fee24h_bdt,
        'penalties': pen24h_bdt,
        'earning': earn24h,
        'expense': exp24h,
        'profit': profit24h
    }
    
    # Update explicitly for cards
    sf = SystemFinance.query.first()
    if sf:
        sf.total_revenue = total_earning_bdt
        sf.total_expenses = total_expense_bdt
        sf.net_profit = net_profit
        sf.last_updated = datetime.utcnow()
        db.session.commit()

    stats = {
        'total_users': User.query.count(),
        'students': User.query.filter_by(role='learner').count(),
        'tutors': User.query.filter_by(role='tutor').count(),
        'total_listings': total_listings,
        'active_courses': active_courses,
        'hidden_courses': hidden_courses,
        'total_bookings': Booking.query.count(),
        'total_tokens': db.session.query(db.func.sum(Wallet.balance)).scalar() or 0,
        'revenue_tokens': total_revenue_tokens,
        'tokens_spent': total_tokens_spent,
        'platform_fees': platform_fees_collected,
        'platform_profit': platform_fees_collected,
        'token_sell_bdt': token_sell_bdt,
        'ad_bdt': ad_bdt,
        'platform_fee_bdt': platform_fee_bdt,
        'penalty_bdt': penalty_bdt,
        'bonus_bdt': bonus_bdt,
        'payout_bdt': payout_bdt,
        'total_expense': total_expense_bdt,
        'net_profit': net_profit,
        'gross_earning': total_earning_bdt
    }
    
    all_tutors = User.query.filter_by(role='tutor').all()
    purchases = TokenPurchaseRequest.query.order_by(TokenPurchaseRequest.timestamp.desc()).limit(50).all()
    withdrawals = WithdrawalRequest.query.order_by(WithdrawalRequest.timestamp.desc()).all()
    disputes = Dispute.query.filter_by(status='Open').all()
    all_users = User.query.all()
    transactions = TransactionHistory.query.order_by(TransactionHistory.timestamp.desc()).limit(50).all()
    support_tickets = SupportTicket.query.order_by(SupportTicket.status.desc(), SupportTicket.timestamp.desc()).all()
    
    running_sessions = Booking.query.filter_by(status='Confirmed').all()
    scheduled_sessions = Booking.query.filter_by(status='Pending').all()
    past_sessions = Booking.query.filter(Booking.status.in_(['Completed', 'Cancelled'])).all()
    
    all_courses = TopicListing.query.all()
    activities = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(50).all()
    
    sf = SystemFinance.query.first()
    return render_template('admin_dashboard.html', stats=stats, all_tutors=all_tutors, stats_24h=stats_24h,
                           purchases=purchases, withdrawals=withdrawals, disputes=disputes, users=all_users, transactions=transactions,
                           running_sessions=running_sessions, scheduled_sessions=scheduled_sessions, past_sessions=past_sessions,
                           all_courses=all_courses, activities=activities, sf=sf, support_tickets=support_tickets)

@app.route('/api/admin/analytics', methods=['GET'])
@login_required
def admin_analytics_api():
    if session['role'] != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
        
    # Earning components
    # Using coalesce-like approach with sum. If no record, returns None.
    token_sell_bdt = db.session.query(db.func.sum(TokenPurchaseRequest.bdt_amount)).filter(TokenPurchaseRequest.status.in_(['Approved', 'Completed'])).scalar() or 0.0
    
    # Track platform fees, cancelation charges = Penalty
    # Note: Penalty amount is sometimes positive (fee deducted) sometimes negative (tutor cancellation).
    # Since platform keeps all penalties/fees, we take absolute value.
    penalty_tokens = db.session.query(db.func.sum(db.func.abs(TransactionHistory.amount))).filter_by(type='Penalty').scalar() or 0.0
    platform_fee_bdt = penalty_tokens * 0.50
    
    # Ads
    ad_tokens = db.session.query(db.func.sum(db.func.abs(TransactionHistory.amount))).filter_by(type='Advertisement').scalar() or 0.0
    advertisement_bdt = ad_tokens * 0.50
    
    total_earning = token_sell_bdt + platform_fee_bdt + advertisement_bdt
    
    # Expenses components
    payout_bdt = db.session.query(db.func.sum(WithdrawalRequest.bdt_amount)).filter(WithdrawalRequest.status.in_(['Approved', 'Completed', 'Sent'])).scalar() or 0.0
    bonus_tokens = db.session.query(db.func.sum(db.func.abs(TransactionHistory.amount))).filter_by(type='Bonus').scalar() or 0.0
    bonus_bdt = bonus_tokens * 0.50
    
    total_expense = payout_bdt + bonus_bdt
    platform_profit = total_earning - total_expense
    
    return jsonify({
        "total_revenue": total_earning,
        "token_sell_bdt": token_sell_bdt,
        "advertisement_bdt": advertisement_bdt,
        "platform_fee": platform_fee_bdt,
        "total_expense": total_expense,
        "total_payout": payout_bdt,
        "bonus_bdt": bonus_bdt,
        "platform_profit": platform_profit,
        "is_loss": platform_profit < 0
    })

@app.route('/api/notifications', methods=['GET'])
@login_required
def get_notifications():
    notifs = Notification.query.filter_by(user_id=session['user_id']).order_by(Notification.timestamp.desc()).limit(20).all()
    return jsonify([{
        "id": n.id,
        "message": n.message,
        "is_read": n.is_read,
        "action_url": n.action_url,
        "timestamp": n.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    } for n in notifs])

@app.route('/admin/sessions')
@login_required
def admin_sessions():
    if session['role'] != 'admin':
        return redirect(url_for('index'))
    
    running_sessions = Booking.query.filter_by(status='Confirmed').all()
    scheduled_sessions = Booking.query.filter_by(status='Pending').all()
    past_sessions = Booking.query.filter(Booking.status.in_(['Completed', 'Cancelled'])).all()
    
    return render_template('admin_sessions.html', running=running_sessions, scheduled=scheduled_sessions, past=past_sessions)

@app.route('/admin/verify_tutor/<int:tutor_id>', methods=['POST'])
@login_required
def verify_tutor(tutor_id):
    if session['role'] != 'admin':
        return "Unauthorized", 403
    tutor = User.query.get_or_404(tutor_id)
    action = request.form.get('action')
    if action == 'approve':
        tutor.is_tutor_verified = True
        tutor.is_verified = True  # Approving tutor also verifies their identity
        tutor.rejection_reason = None
        flash(f'Tutor {tutor.name} approved.', 'success')
    elif action == 'reject':
        tutor.rejection_reason = request.form.get('rejection_reason', 'Did not meet criteria.')
        flash(f'Tutor {tutor.name} rejected.', 'success')
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/tutors')
def tutor_search():
    check_and_freeze_slots()
    q = request.args.get('q', '')
    query = User.query.filter_by(role='tutor', is_tutor_verified=True)
    if q:
        query = query.filter(User.name.contains(q) | User.skills.contains(q) | User.department.contains(q))
    tutors = query.all()
    return render_template('tutor_search.html', tutors=tutors)

@app.route('/user/<int:user_id>')
def view_profile(user_id):
    profile_user = User.query.get_or_404(user_id)
    if profile_user.role == 'tutor':
         listings = TopicListing.query.filter_by(tutor_id=user_id).all()
    else:
         listings = []
    return render_template('view_profile.html', profile_user=profile_user, listings=listings)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/marketplace')
def marketplace():
    check_and_freeze_slots()
    q = request.args.get('q', '')
    cat = request.args.get('category', '')
    
    active_tutors = db.session.query(AvailabilitySlot.tutor_id).filter_by(is_booked=False, is_frozen=False).distinct().all()
    active_tutor_ids = [t[0] for t in active_tutors]
    
    query = TopicListing.query.join(User).filter(User.is_verified == True, TopicListing.tutor_id.in_(active_tutor_ids))
    if q:
        query = query.filter(TopicListing.title.contains(q))
    if cat:
        query = query.filter(TopicListing.category == cat)
    
    # Only include listings from tutors with at least one available slot
    query = query.order_by(TopicListing.is_advertised.desc(), TopicListing.id.desc())
    listings = query.all()
    return render_template('marketplace.html', listings=listings)

@app.route('/listing/<int:listing_id>')
@login_required
def view_listing(listing_id):
    check_and_freeze_slots()
    listing = TopicListing.query.get_or_404(listing_id)
    available_slots = AvailabilitySlot.query.filter_by(tutor_id=listing.tutor_id, is_booked=False, is_frozen=False).all()
    return render_template('view_listing.html', listing=listing, slots=available_slots)

@app.route('/listing/<int:listing_id>/advertise', methods=['POST'])
@login_required
def advertise_listing(listing_id):
    if session['role'] != 'tutor':
        flash('Only tutors can purchase advertisements.', 'error')
        return redirect(url_for('tutor_dashboard'))
    listing = TopicListing.query.get_or_404(listing_id)
    if listing.tutor_id != session['user_id']:
        flash('You can only advertise your own courses.', 'error')
        return redirect(url_for('tutor_dashboard'))
    if listing.is_advertised and listing.ad_expiry_time and listing.ad_expiry_time > datetime.utcnow():
        flash('This course is already being advertised. Wait for it to expire.', 'warning')
        return redirect(url_for('tutor_dashboard'))

    wallet = Wallet.query.filter_by(user_id=session['user_id']).first()
    cost = round(listing.price * 0.40, 2)  # 40% of listing price
    if wallet.balance < cost:
        flash(f'Insufficient tokens. You need {cost} tokens (40% of {listing.price}) to advertise.', 'error')
        return redirect(url_for('tutor_dashboard'))

    wallet.balance -= cost
    listing.is_advertised = True
    listing.ad_expiry_time = datetime.utcnow() + timedelta(hours=24)

    hist = TransactionHistory(
        user_id=session['user_id'], amount=-cost,
        type='Advertisement', description=f"Ad for '{listing.title}' (40% = {cost} tokens, 24hr)"
    )
    db.session.add(hist)
    update_system_finance(revenue=cost * 0.50)  # BDT equivalent
    db.session.commit()

    flash(f'Course advertised for 24 hours! Cost: {cost} tokens (40% of listing price).', 'success')
    return redirect(url_for('tutor_dashboard'))

@app.route('/listing/create', methods=['GET', 'POST'])
@login_required
def create_listing():
    if session['role'] != 'tutor':
        flash('Switch to tutor role to create listings.', 'error')
        return redirect(url_for('dashboard'))
    
    user = User.query.get(session['user_id'])
    # ----------------------------
    # BUG FIX #1: Direct verification and grade existence guard
    if not user.is_verified or not user.grade_report:
        flash('Your account must be securely verified by an admin before configuring dynamic listings.', 'error')
        return redirect(url_for('tutor_dashboard'))
    # ----------------------------
        
    slots_exist = AvailabilitySlot.query.filter_by(tutor_id=user.id, is_booked=False).first()
    if not slots_exist:
        flash('You must add at least one availability slot before publishing a listing.', 'warning')
        return redirect(url_for('manage_availability'))
        
    if request.method == 'POST':
        title = request.form['title']
        category = request.form['category']
        description = request.form['description']
        price = float(request.form['price'])
        
        listing = TopicListing(tutor_id=session['user_id'], title=title, category=category, description=description, price=price)
        db.session.add(listing)
        db.session.commit()
        flash('Listing created successfully!', 'success')
        return redirect(url_for('tutor_dashboard'))
    return render_template('create_listing.html')

# /purchase_ad now redirects to the unified advertise_listing route
@app.route('/purchase_ad/<int:listing_id>', methods=['POST'])
@login_required
def purchase_ad(listing_id):
    return advertise_listing(listing_id)

@app.route('/book/<int:listing_id>', methods=['POST'])
@login_required
def book_session(listing_id):
    if session['role'] != 'learner':
        flash('You must be in Learner mode to book sessions.', 'error')
        return redirect(url_for('view_listing', listing_id=listing_id))
        
    listing = TopicListing.query.get_or_404(listing_id)
    slot_id = request.form.get('slot_id')
    if not slot_id:
        flash('Please select an available time slot.', 'error')
        return redirect(url_for('view_listing', listing_id=listing_id))
        
    slot = AvailabilitySlot.query.get_or_404(slot_id)
    if slot.is_booked:
        flash('This slot was just booked by someone else.', 'error')
        return redirect(url_for('view_listing', listing_id=listing_id))
        
    wallet = Wallet.query.filter_by(user_id=session['user_id']).first()
    
    if wallet.balance < listing.price:
        flash('Insufficient tokens. Please purchase more.', 'error')
        return redirect(url_for('wallet'))
        
    wallet.balance -= listing.price
    slot.is_booked = True
    
    hist = TransactionHistory(user_id=session['user_id'], amount=-listing.price, type='Payment', description=f"Booked {listing.title}")
    db.session.add(hist)
    
    booking = Booking(learner_id=session['user_id'], listing_id=listing.id, slot_id=slot.id, status='Pending')
    db.session.add(booking)
    db.session.commit() 
    
    escrow = EscrowTransaction(booking_id=booking.id, amount=listing.price, status='Held')
    db.session.add(escrow)
    db.session.commit()
    
    flash('Booking successful! Tokens held in escrow.', 'success')
    return redirect(url_for('learner_dashboard'))

@app.route('/booking/<int:booking_id>/confirm', methods=['POST'])
@login_required
def confirm_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.listing.tutor_id != session['user_id']:
        return "Unauthorized", 403
        
    booking.status = 'Confirmed'
    
    # Auto-create Meeting Room
    room_name = f"StudyByte_Meeting_{booking.id}_{uuid.uuid4().hex[:8]}"
    meeting = MeetingRoom(booking_id=booking.id, room_name=room_name)
    db.session.add(meeting)
    
    db.session.commit()
    
    flash('Booking confirmed! A meeting session has been generated automatically.', 'success')
    return redirect(url_for('tutor_dashboard'))

@app.route('/booking/<int:booking_id>/check_in', methods=['POST'])
@login_required
def check_in_session(booking_id):
    booking = Booking.query.get_or_404(booking_id)

    if session['user_id'] == booking.learner_id:
        if booking.learner_confirmed:
            flash('You have already confirmed this session.', 'error')
            return redirect(url_for('chat_room', booking_id=booking_id))
        booking.learner_confirmed = True
        booking.learner_join_time = datetime.utcnow()
        party = 'Learner'
        other_id = booking.listing.tutor_id
        other_label = 'Tutor'
    elif session['user_id'] == booking.listing.tutor_id:
        if booking.tutor_confirmed:
            flash('You have already confirmed this session.', 'error')
            return redirect(url_for('chat_room', booking_id=booking_id))
        booking.tutor_confirmed = True
        booking.tutor_join_time = datetime.utcnow()
        party = 'Tutor'
        other_id = booking.learner_id
        other_label = 'Learner'
    else:
        return "Unauthorized", 403

    # Notify the other party that this side confirmed
    db.session.add(Notification(
        user_id=other_id,
        message=f"✅ The {party} has confirmed session BKG-{booking.id} ({booking.listing.title}). Please confirm your side to release payment.",
        action_url=f"/booking/{booking.id}/chat"
    ))

    # ── Both sides confirmed → AUTO-DISPATCH PAYMENT ──────────────────────────
    if booking.learner_confirmed and booking.tutor_confirmed:
        booking.status = 'Completed'
        escrow = EscrowTransaction.query.filter_by(booking_id=booking.id, status='Held').first()

        if escrow:
            platform_fee  = round(escrow.amount * 0.05, 2)
            tutor_payout  = round(escrow.amount - platform_fee, 2)
            escrow.status = 'Released'

            tutor_wallet = Wallet.query.filter_by(user_id=booking.listing.tutor_id).first()
            if tutor_wallet:
                tutor_wallet.balance += tutor_payout

            update_system_finance(revenue=platform_fee)
            db.session.add(TransactionHistory(
                user_id=booking.listing.tutor_id,
                amount=tutor_payout,
                type='Received',
                description=f"Auto-released: {booking.listing.title} (BKG-{booking.id}, after 5% fee)"
            ))
            db.session.add(TransactionHistory(
                user_id=booking.listing.tutor_id,
                amount=platform_fee,
                type='Commission',
                description=f"Platform Fee 5% — BKG-{booking.id}"
            ))

            # Notify both parties of successful release
            db.session.add(Notification(
                user_id=booking.listing.tutor_id,
                message=f"🎉 Payment auto-released! {tutor_payout} tokens received for '{booking.listing.title}' (BKG-{booking.id}).",
                action_url='/wallet'
            ))
            db.session.add(Notification(
                user_id=booking.learner_id,
                message=f"✅ Session '{booking.listing.title}' (BKG-{booking.id}) completed & payment released. Leave a review!",
                action_url=f"/booking/{booking.id}/review"
            ))
            released_amount = tutor_payout
        else:
            released_amount = 0

        db.session.commit()
        flash(f'🎉 Both parties confirmed! Payment of {released_amount} tokens auto-released to tutor.', 'success')
        return redirect(url_for('chat_room', booking_id=booking_id))

    # ── Only one side confirmed ────────────────────────────────────────────────
    db.session.commit()
    flash(f'✅ {party} confirmed. Waiting for {other_label} to confirm. Payment will release automatically when both confirm.', 'success')
    return redirect(url_for('chat_room', booking_id=booking_id))


@app.route('/booking/<int:booking_id>/review', methods=['GET', 'POST'])
@login_required
def review(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.learner_id != session['user_id'] or booking.status != 'Completed' or booking.has_review:
        return redirect(url_for('learner_dashboard'))
        
    if request.method == 'POST':
        rating = int(request.form['rating'])
        comment = request.form['comment']
        
        rev = Review(booking_id=booking.id, rating=rating, comment=comment)
        booking.has_review = True
        
        tutor = booking.listing.tutor
        total_score = tutor.rating * tutor.review_count + rating
        tutor.review_count += 1
        tutor.rating = total_score / tutor.review_count
        
        db.session.add(rev)
        db.session.commit()
        flash('Thanks for the review!', 'success')
        return redirect(url_for('learner_dashboard'))
        
    return render_template('review.html', booking=booking, tutor=booking.listing.tutor, listing=booking.listing)

@app.route('/wallet', methods=['GET', 'POST'])
@login_required
def wallet():
    transactions = TransactionHistory.query.filter_by(user_id=session['user_id']).order_by(TransactionHistory.timestamp.desc()).all()
    purchases = TokenPurchaseRequest.query.filter_by(user_id=session['user_id']).order_by(TokenPurchaseRequest.timestamp.desc()).all()
    withdrawals = WithdrawalRequest.query.filter_by(user_id=session['user_id']).order_by(WithdrawalRequest.timestamp.desc()).all()
    return render_template('wallet.html', transactions=transactions, purchases=purchases, withdrawals=withdrawals)

import requests

def initiate_payment_gateway(method, amount, req_id):
    """ Realistic Mock for Payment Gateway API Handshake """
    # In a real environment, you'd use credentials to get a token, then call Create Payment API
    # headers = {'Authorization': 'Bearer token', 'X-APP-Key': 'key'}
    # res = requests.post(f"https://checkout.{method.lower()}.com/api/v1/payment/create", json={...})
    
    # We return a simulated PG URL
    return url_for('simulate_pg', method=method, req_id=req_id, amount=amount)

@app.route('/wallet/purchase', methods=['POST'])
@login_required
def purchase_tokens():
    method = request.form['method']
    bdt_amount = float(request.form['bdt_amount'])
    token_amount = bdt_amount / 0.50
    
    if method not in ['bKash', 'Nagad']:
        flash('Invalid payment method selected.', 'error')
        return redirect(url_for('wallet'))
        
    # 1. Create Pending Request
    req = TokenPurchaseRequest(user_id=session['user_id'], method=method, mobile_number="Pending", 
                               transaction_id="Pending", bdt_amount=bdt_amount, token_amount=token_amount, status='Initiated')
    db.session.add(req)
    db.session.commit()
        
    # 2. Handshake with API
    payment_url = initiate_payment_gateway(method, bdt_amount, req.id)
    return redirect(payment_url)

@app.route('/payment_gateway/simulate')
@login_required
def simulate_pg():
    """ Simulated specific Gateway Front-End """
    method = request.args.get('method')
    req_id = request.args.get('req_id')
    amount = request.args.get('amount')
    return render_template('payment_gateway.html', method=method, req_id=req_id, bdt_amount=amount)


@app.route('/payment/callback', methods=['POST'])
@login_required
def payment_callback():
    status = request.form['status']
    req_id = request.form['req_id']
    account_no = request.form.get('account_no')
    pin = request.form.get('pin')
    
    req = TokenPurchaseRequest.query.get_or_404(req_id)
    
    if req.status != 'Initiated':
        flash('Transaction already processed or invalid state.', 'error')
        return redirect(url_for('wallet'))
    
    if status == 'success':
        transaction_id = request.form.get('transaction_id')
        if not transaction_id:
            flash('Transaction ID is required.', 'error')
            return redirect(url_for('wallet'))
            
        req.status = 'Pending Verification'
        req.transaction_id = transaction_id
        db.session.commit()
        
        flash(f'Payment submitted successfully! Your tokens will be added once an admin verifies the Transaction ID: {transaction_id}', 'success')
    else:
        req.status = 'Cancelled'
        db.session.commit()
        flash('Payment cancelled.', 'error')
        
    return redirect(url_for('wallet'))

@app.route('/wallet/withdraw', methods=['POST'])
@login_required
def withdraw_funds():
    if session['role'] != 'tutor':
        flash('Only tutors can withdraw funds.', 'error')
        return redirect(url_for('wallet'))
        
    user = User.query.get(session['user_id'])
    if not user.is_verified:
        flash('Unverified users cannot withdraw money or access tutor financial features.', 'error')
        return redirect(url_for('wallet'))
        
    token_amount = float(request.form['token_amount'])
    mobile_num = request.form['mobile_number']
    method = request.form['method']
    
    if not (mobile_num.startswith('01') and len(mobile_num) == 11 and mobile_num.isdigit()):
        flash('Invalid mobile number. Must be exactly 11 digits starting with 01.', 'error')
        return redirect(url_for('wallet'))
        
    if method == "Rocket":
        flash('Rocket is no longer supported.', 'error')
        return redirect(url_for('wallet'))

    wallet = Wallet.query.filter_by(user_id=session['user_id']).first()
    
    if token_amount < 1000:
        flash('Minimum withdrawal is 500 BDT (1000 Tokens).', 'error')
        return redirect(url_for('wallet'))
        
    if token_amount > wallet.balance:
        flash('Insufficient token balance.', 'error')
        return redirect(url_for('wallet'))
    
    wallet.balance -= token_amount
    bdt_amount = token_amount * 0.50
    
    req = WithdrawalRequest(user_id=session['user_id'], method=request.form['method'], mobile_number=request.form['mobile_number'], 
                            token_amount=token_amount, bdt_amount=bdt_amount)
    
    hist = TransactionHistory(user_id=session['user_id'], amount=-token_amount, type='Withdrawal', description=f"Withdrawal request pending")
    db.session.add(hist)
    db.session.add(req)
    db.session.commit()
    
    flash(f'Withdrawal request for {token_amount} tokens ({bdt_amount} BDT) submitted.', 'success')
    return redirect(url_for('wallet'))

@app.route('/admin/withdraw/<int:w_id>/<action>', methods=['POST'])
@login_required
def admin_withdraw(w_id, action):
    if session['role'] != 'admin':
        return "Unauthorized", 403
    req = WithdrawalRequest.query.get_or_404(w_id)
    if action == 'approve':
        req.status = 'Approved'
        flash('Withdrawal approved.', 'success')
    else:
        req.status = 'Rejected'
        wallet = Wallet.query.filter_by(user_id=req.user_id).first()
        wallet.balance += req.token_amount
        hist = TransactionHistory(user_id=req.user_id, amount=req.token_amount, type='Refund', description='Withdrawal request rejected')
        db.session.add(hist)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/purchase/<int:p_id>/<action>', methods=['POST'])
@login_required
def admin_purchase(p_id, action):
    if session['role'] != 'admin':
        return "Unauthorized", 403
    req = TokenPurchaseRequest.query.get_or_404(p_id)
    if action == 'approve':
        req.status = 'Approved'
        wallet = Wallet.query.filter_by(user_id=req.user_id).first()
        wallet.balance += req.token_amount
        hist = TransactionHistory(user_id=req.user_id, amount=req.token_amount, type='Purchase', description=f"Manual Buy {req.method} ({req.transaction_id})")
        db.session.add(hist)
        flash('Purchase approved and tokens added.', 'success')
    else:
        req.status = 'Rejected'
        flash('Purchase rejected.', 'error')
    db.session.commit()
    return redirect(url_for('admin_dashboard'))



@app.route('/admin/user/<int:u_id>/toggle_suspend', methods=['POST'])
@login_required
def toggle_suspend(u_id):
    if session['role'] != 'admin':
        return "Unauthorized", 403
    u = User.query.get_or_404(u_id)
    user_wallet = Wallet.query.filter_by(user_id=u.id).first()
    if u.status == 'Active':
        u.status = 'Suspended'
        flash(f'User {u.name} suspended. Tokens remaining: {user_wallet.balance}', 'warning')
    else:
        u.status = 'Active'
        flash(f'User {u.name} activated.', 'success')
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/user/<int:u_id>/set_password', methods=['POST'])
@login_required
def admin_set_password(u_id):
    if session['role'] != 'admin':
        return "Unauthorized", 403
    u = User.query.get_or_404(u_id)
    new_pw = request.form.get('new_password', '')

    if not (6 <= len(new_pw) <= 32):
        flash('Password must be between 6 and 32 characters.', 'error')
        return redirect(url_for('admin_dashboard'))
    if not re.search(r'[a-z]', new_pw) or not re.search(r'[A-Z]', new_pw):
        flash('Password must contain both uppercase and lowercase letters.', 'error')
        return redirect(url_for('admin_dashboard'))
    if not re.search(r'[0-9]', new_pw):
        flash('Password must contain at least one number.', 'error')
        return redirect(url_for('admin_dashboard'))
    if not re.search(r'[@#_]', new_pw):
        flash('Password must contain at least one special character (@, #, _).', 'error')
        return redirect(url_for('admin_dashboard'))
    if ' ' in new_pw:
        flash('Password cannot contain spaces.', 'error')
        return redirect(url_for('admin_dashboard'))

    u.password_hash = generate_password_hash(new_pw)
    db.session.commit()
    log_activity(session['user_id'], 'ADMIN_SET_PW', f"Admin force-reset password for {u.name} (UID:{u.id})")
    flash(f'Password for {u.name} has been updated successfully.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/support/new', methods=['GET', 'POST'])
@login_required
def report_support_ticket():
    if request.method == 'POST':
        subject = request.form.get('subject')
        message = request.form.get('message')
        if not subject or not message:
            flash('Please fill out all fields.', 'error')
            return redirect(url_for('report_support_ticket'))
            
        ticket = SupportTicket(user_id=session['user_id'], subject=subject, message=message)
        db.session.add(ticket)
        db.session.commit()
        flash('Support ticket perfectly submitted. An admin will get back to you soon.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('report_support.html')

@app.route('/admin/support/<int:ticket_id>/reply', methods=['POST'])
@login_required
def admin_reply_support(ticket_id):
    if session.get('role') != 'admin':
        return "Unauthorized", 403
    ticket = SupportTicket.query.get_or_404(ticket_id)
    reply = request.form.get('admin_reply')
    if reply:
        ticket.admin_reply = reply
        ticket.status = 'Closed'
        
        # Notify the user
        notif = Notification(user_id=ticket.user_id, message=f"Admin replied to your ticket: {ticket.subject}", action_url='/dashboard')
        db.session.add(notif)
        db.session.commit()
        flash('Support ticket replied to successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

def upload_to_cloud(file):
    # Stub for Cloud Storage (S3 / Cloudinary)
    filename = secure_filename(f"{uuid.uuid4().hex}_{file.filename}")
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    return url_for('uploaded_file', filename=filename)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        new_name = request.form['name']
        
        # No duplicate tutor name check
        if user.role == 'tutor' or session.get('role') == 'tutor':
            existing_tutor = User.query.filter_by(name=new_name, role='tutor').first()
            if existing_tutor and existing_tutor.id != user.id:
                flash('This name is already in use by another tutor/course issuer. Please pick a unique name.', 'error')
                return redirect(url_for('profile'))
                
        user.name = new_name
        user.bio = request.form.get('bio', '')
        user.skills = request.form.get('skills', '')
        user.social_links = request.form.get('social_links', '')
        user.education = request.form.get('education', '')
        
        if user.role != 'admin':
            user.department = request.form.get('department', '')
            
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file.filename != '':
                user.profile_pic = upload_to_cloud(file)
                
        if 'cover_photo' in request.files:
            file = request.files['cover_photo']
            if file.filename != '':
                user.cover_photo = upload_to_cloud(file)
                
        db.session.commit()
        flash('Profile updated.', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html', user=user)

# --- NEW MODULES ADDED ---

@app.route('/booking/<int:booking_id>/cancel', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.status not in ['Pending', 'Confirmed']:
        flash('Booking cannot be cancelled at this stage.', 'error')
        if session['role'] == 'tutor':
            return redirect(url_for('tutor_dashboard'))
        return redirect(url_for('learner_dashboard'))
        
    is_learner = session['user_id'] == booking.learner_id
    is_tutor = session['user_id'] == booking.listing.tutor_id
    
    if not (is_learner or is_tutor):
        return "Unauthorized", 403
        
    wallet_learner = Wallet.query.filter_by(user_id=booking.learner_id).first()
    wallet_tutor = Wallet.query.filter_by(user_id=booking.listing.tutor_id).first()
    
    fee = 0.0
    refund_amount = booking.listing.price
    if booking.status == 'Confirmed':
        fee = refund_amount * 0.20
        refund_amount = refund_amount - fee
        
    booking.slot.is_booked = False
    
    escrow = EscrowTransaction.query.filter_by(booking_id=booking.id, status='Held').first()
    if escrow:
        escrow.status = 'Refunded'
        
    booking.status = 'Cancelled'

    if is_learner:
        wallet_learner.balance += refund_amount
        db.session.add(TransactionHistory(user_id=booking.learner_id, amount=refund_amount, type='Refund', description=f"Cancelled booking {booking.id} (-20% fee)"))
        if fee > 0:
            update_system_finance(revenue=fee)
    else:
        # Tutor cancelled — 40% penalty: 20% to learner, 20% to system
        price = booking.listing.price
        penalty_total = price * 0.40
        learner_comp   = price * 0.20
        system_share   = price * 0.20
        # Full refund + 20% compensation to learner
        wallet_learner.balance += price + learner_comp
        db.session.add(TransactionHistory(user_id=booking.learner_id, amount=price, type='Refund', description=f"Refund: tutor cancelled booking {booking.id}"))
        db.session.add(TransactionHistory(user_id=booking.learner_id, amount=learner_comp, type='Compensation', description=f"Tutor cancellation compensation 20% (BKG-{booking.id})"))
        # 40% penalty deducted from tutor
        wallet_tutor.balance -= penalty_total
        db.session.add(TransactionHistory(user_id=booking.listing.tutor_id, amount=-penalty_total, type='Penalty', description=f"Cancellation penalty 40% (BKG-{booking.id})"))
        # 20% to platform
        update_system_finance(revenue=system_share)
        
    db.session.commit()
    flash('Booking cancelled successfully.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/booking/<int:booking_id>/chat')
@login_required
def chat_room(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if not (session['user_id'] == booking.learner_id or session['user_id'] == booking.listing.tutor_id or session.get('role') == 'admin'):
        return "Unauthorized", 403
        
    if session['user_id'] == booking.learner_id and not booking.learner_join_time:
        booking.learner_join_time = datetime.utcnow()
        db.session.commit()
    elif session['user_id'] == booking.listing.tutor_id and not booking.tutor_join_time:
        booking.tutor_join_time = datetime.utcnow()
        db.session.commit()
    if booking.status != 'Confirmed' and booking.status != 'Completed':
        flash('Chat is only available for confirmed or completed bookings.', 'error')
        return redirect(url_for('dashboard'))
        
    messages = ChatMessage.query.filter_by(booking_id=booking.id).order_by(ChatMessage.timestamp.asc()).all()
    meeting = MeetingRoom.query.filter_by(booking_id=booking.id).first()
    materials = CourseMaterial.query.filter_by(booking_id=booking.id).order_by(CourseMaterial.timestamp.desc()).all()
    
    return render_template('chat_room.html', booking=booking, messages=messages, meeting=meeting, materials=materials)

@app.route('/booking/<int:booking_id>/upload_material', methods=['POST'])
@login_required
def upload_material(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if session['user_id'] != booking.listing.tutor_id:
        return "Unauthorized", 403
        
    if 'material' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('chat_room', booking_id=booking_id))
        
    file = request.files['material']
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('chat_room', booking_id=booking_id))
        
    if file:
        original_name = file.filename
        filename = secure_filename(f"mat_{booking.id}_{uuid.uuid4().hex[:6]}_{original_name}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        mat = CourseMaterial(booking_id=booking.id, uploaded_by=session['user_id'], filename=filename, original_name=original_name)
        db.session.add(mat)
        db.session.commit()
        flash('Material uploaded successfully.', 'success')
        
    return redirect(url_for('chat_room', booking_id=booking_id))

@app.route('/material/<int:mat_id>/download')
@login_required
def download_material(mat_id):
    mat = CourseMaterial.query.get_or_404(mat_id)
    booking = Booking.query.get(mat.booking_id)
    if not (session['user_id'] == booking.learner_id or session['user_id'] == booking.listing.tutor_id):
        return "Unauthorized", 403
    return send_from_directory(app.config['UPLOAD_FOLDER'], mat.filename, as_attachment=True, download_name=mat.original_name)

# Socket IO Events
@socketio.on('join')
def on_join(data):
    room = str(data['room'])
    join_room(room)
    sender_id = session.get('user_id')
    booking = Booking.query.get(int(room))
    if sender_id and booking:
        now = datetime.utcnow()
        if sender_id == booking.learner_id and not booking.learner_join_time:
            booking.learner_join_time = now
            db.session.commit()
        elif sender_id == booking.listing.tutor_id and not booking.tutor_join_time:
            booking.tutor_join_time = now
            db.session.commit()

@socketio.on('leave')
def on_leave(data):
    room = str(data['room'])
    leave_room(room)
    sender_id = session.get('user_id')
    booking = Booking.query.get(int(room))
    if sender_id and booking:
        now = datetime.utcnow()
        if sender_id == booking.learner_id:
            booking.learner_left_time = now
            db.session.commit()
        elif sender_id == booking.listing.tutor_id:
            booking.tutor_left_time = now
            db.session.commit()

@socketio.on('send_message')
def handle_message(data):
    room = str(data['room'])
    message = data['message']
    sender_id = session.get('user_id')
    
    if sender_id and message:
        msg = ChatMessage(booking_id=int(room), sender_id=sender_id, message=message)
        db.session.add(msg)
        db.session.commit()
        
        sender = User.query.get(sender_id)
        
        # Identify receiver
        booking = Booking.query.get(int(room))
        if booking:
            receiver_id = booking.listing.tutor_id if sender_id == booking.learner_id else booking.learner_id
            
            notif = Notification(
                user_id=receiver_id,
                message=f"New message from {sender.name}: {message[:40]}...",
                action_url=f"/booking/{room}/chat"
            )
            db.session.add(notif)
            db.session.commit()
        
        emit('receive_message', {
            'sender_name': sender.name,
            'sender_id': sender.id,
            'message': message,
            'timestamp': msg.timestamp.strftime('%H:%M')
        }, room=room)

@app.route('/dispute/<int:booking_id>', methods=['GET', 'POST'])
@login_required
def report_dispute(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if session['user_id'] not in [booking.learner_id, booking.listing.tutor_id]:
        return "Unauthorized", 403

    # Allow disputes for any active or recently-ended booking
    allowed_statuses = ('Confirmed', 'Pending', 'Completed', 'Payment Under Review')
    if booking.status not in allowed_statuses:
        flash('Disputes cannot be filed for cancelled or expired bookings.', 'error')
        return redirect(url_for('chat_room', booking_id=booking_id))

    if request.method == 'POST':
        reason   = request.form.get('reason', '').strip()
        category = request.form.get('category', 'Other')

        if not reason:
            flash('Please describe the issue.', 'error')
            return redirect(url_for('report_dispute', booking_id=booking_id))

        # Check for existing open dispute from same user
        existing = Dispute.query.filter_by(
            booking_id=booking.id,
            user_id=session['user_id'],
            status='Open'
        ).first()
        if existing:
            flash('You already have an open dispute for this booking. Admin is reviewing it.', 'warning')
            return redirect(url_for('chat_room', booking_id=booking_id))

        dispute = Dispute(
            booking_id=booking.id,
            user_id=session['user_id'],
            reason=reason,
            category=category
        )
        db.session.add(dispute)

        # Mark booking as under review
        booking.status = 'Payment Under Review'

        # Notify admin
        admin = User.query.filter_by(role='admin').first()
        if admin:
            db.session.add(Notification(
                user_id=admin.id,
                message=f"⚖️ New dispute [{category}] filed for BKG-{booking.id} — '{booking.listing.title}'. Action required.",
                action_url='/admin/disputes'
            ))

        # Notify the other party
        reporter   = User.query.get(session['user_id'])
        other_id   = booking.listing.tutor_id if session['user_id'] == booking.learner_id else booking.learner_id
        db.session.add(Notification(
            user_id=other_id,
            message=f"⚠️ {reporter.name} has filed a dispute for BKG-{booking.id} ({category}). Admin will review and contact both parties.",
            action_url=f"/booking/{booking.id}/chat"
        ))

        db.session.commit()
        flash('Dispute submitted. Admin will review and take action on the escrow.', 'success')
        return redirect(url_for('chat_room', booking_id=booking_id))

    return render_template('report_dispute.html', booking=booking)

@app.route('/admin/disputes')
@login_required
def admin_disputes():
    if session['role'] != 'admin':
        return "Unauthorized", 403
    disputes = Dispute.query.order_by(Dispute.status.desc(), Dispute.timestamp.desc()).all()
    # Add System Finance to the context
    sf = SystemFinance.query.first()
    return render_template('admin_disputes.html', disputes=disputes, sf=sf)

@app.route('/admin/resolve_dispute/<int:dispute_id>', methods=['POST'])
@login_required
def admin_resolve_dispute(dispute_id):
    if session['role'] != 'admin':
        return "Unauthorized", 403
        
    dispute = Dispute.query.get_or_404(dispute_id)
    booking = dispute.booking
    
    action = request.form.get('action') # release, refund, split, penalty, close_only
    admin_notes = request.form.get('admin_notes', '')
    
    dispute.admin_notes = admin_notes
    dispute.status = 'Resolved'
    
    if action == 'close_only':
        db.session.commit()
        flash('Dispute strictly closed with no transaction side effects.', 'success')
        return redirect(url_for('admin_dashboard'))
    
    escrow = EscrowTransaction.query.filter_by(booking_id=booking.id, status='Held').first()
    if not escrow:
        flash('Escrow missing or already resolved.', 'error')
        return redirect(url_for('admin_dashboard'))
        
    learner_wallet = Wallet.query.filter_by(user_id=booking.learner_id).first()
    tutor_wallet = Wallet.query.filter_by(user_id=booking.listing.tutor_id).first()
    
    if action == 'release':
        platform_fee = escrow.amount * 0.05
        tutor_payout = escrow.amount - platform_fee
        tutor_wallet.balance += tutor_payout
        update_system_finance(revenue=platform_fee)
        db.session.add(TransactionHistory(user_id=tutor_wallet.user_id, amount=platform_fee, type='Commission', description=f"Platform Fee (BKG-{booking.id})"))
        escrow.status = 'Released'
        booking.status = 'Completed'
        db.session.add(TransactionHistory(user_id=tutor_wallet.user_id, amount=tutor_payout, type='Received', description=f"Admin released Escrow (BKG-{booking.id})"))
        
    elif action == 'refund':
        learner_wallet.balance += escrow.amount
        escrow.status = 'Refunded'
        booking.status = 'Cancelled'
        db.session.add(TransactionHistory(user_id=learner_wallet.user_id, amount=escrow.amount, type='Refund', description=f"Admin refunded Escrow (BKG-{booking.id})"))
        
    elif action == 'split':
        half = escrow.amount / 2
        learner_wallet.balance += half
        tutor_wallet.balance += half
        escrow.status = 'Split'
        booking.status = 'Completed'
        db.session.add(TransactionHistory(user_id=learner_wallet.user_id, amount=half, type='Refund', description=f"Admin Split Refund (BKG-{booking.id})"))
        db.session.add(TransactionHistory(user_id=tutor_wallet.user_id, amount=half, type='Received', description=f"Admin Split Payout (BKG-{booking.id})"))
        
    elif action == 'penalty':
        # 40% penalty from tutor: 20% to learner, 20% to system
        price = escrow.amount
        penalty_total = price * 0.40
        learner_comp  = price * 0.20
        system_share  = price * 0.20
        # Full refund + 20% comp to learner
        learner_wallet.balance += price + learner_comp
        db.session.add(TransactionHistory(user_id=learner_wallet.user_id, amount=price, type='Refund', description=f"Admin dispute refund (BKG-{booking.id})"))
        db.session.add(TransactionHistory(user_id=learner_wallet.user_id, amount=learner_comp, type='Compensation', description=f"Admin penalty compensation 20% (BKG-{booking.id})"))
        # 40% deducted from tutor
        tutor_wallet.balance -= penalty_total
        db.session.add(TransactionHistory(user_id=tutor_wallet.user_id, amount=-penalty_total, type='Penalty', description=f"Admin penalty 40% (BKG-{booking.id})"))
        # 20% to platform
        update_system_finance(revenue=system_share)
        escrow.status = 'Refunded'
        booking.status = 'Cancelled'
        
    log_activity(session['user_id'], 'ADMIN_DISPUTE', f"Resolved dispute #{dispute.id} with action: {action}")
    db.session.commit()
    flash(f'Dispute resolved with action: {action}', 'success')
    return redirect(url_for('admin_disputes'))

# ── Admin: Force-Close a Session ─────────────────────────────────────────────
@app.route('/admin/booking/<int:booking_id>/force_close', methods=['POST'])
@login_required
def force_close_session(booking_id):
    """Admin can forcefully close any active (Confirmed or Pending) session.
    - Refunds learner from escrow if held.
    - Notifies both parties.
    - Logs admin action.
    """
    if session['role'] != 'admin':
        return "Unauthorized", 403

    booking = Booking.query.get_or_404(booking_id)
    if booking.status not in ('Confirmed', 'Pending'):
        flash('Session is already resolved or completed.', 'error')
        return redirect(url_for('admin_sessions'))

    reason = request.form.get('reason', 'Admin intervention').strip() or 'Admin intervention'

    escrow = EscrowTransaction.query.filter_by(booking_id=booking.id, status='Held').first()
    if escrow:
        learner_wallet = Wallet.query.filter_by(user_id=booking.learner_id).first()
        if learner_wallet:
            learner_wallet.balance += escrow.amount
            db.session.add(TransactionHistory(
                user_id=booking.learner_id,
                amount=escrow.amount,
                type='Refund',
                description=f"Admin force-closed session BKG-{booking.id}: {reason}"
            ))
        escrow.status = 'Refunded'

    booking.status = 'Cancelled'

    # Notify both parties
    db.session.add(Notification(
        user_id=booking.learner_id,
        message=f"⚠️ Your session BKG-{booking.id} was force-closed by an admin. Reason: {reason}. Your payment has been refunded.",
        action_url='/learner/dashboard'
    ))
    db.session.add(Notification(
        user_id=booking.listing.tutor_id,
        message=f"⚠️ Your session BKG-{booking.id} was force-closed by an admin. Reason: {reason}.",
        action_url='/tutor/dashboard'
    ))

    log_activity(session['user_id'], 'ADMIN_FORCE_CLOSE', f"Force-closed BKG-{booking.id}. Reason: {reason}")
    db.session.commit()
    flash(f'Session BKG-{booking.id} has been force-closed. Learner refunded.', 'success')
    return redirect(url_for('admin_sessions'))

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=debug_mode)
