from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime
import os, random, string, re, uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'studybyte-super-secret-ewu'
database_url = os.environ.get('DATABASE_URL')
if not database_url:
    if os.environ.get('VERCEL'):
        database_url = 'sqlite:////tmp/studybyte_v5.db' # Vercel-safe fallback
    else:
        database_url = 'sqlite:///studybyte_v5.db' # Local Windows fallback
elif database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'uploads')

try:
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
except OSError:
    # Fallback for Vercel read-only serverless environments
    app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

db = SQLAlchemy(app)
socketio = SocketIO(app)

# ----------------- MODELS -----------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
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
    grade_report = db.Column(db.String(255), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    
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
    tutor = db.relationship('User', foreign_keys=[tutor_id])

class TopicListing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tutor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Float, nullable=False)
    is_advertised = db.Column(db.Boolean, default=False)
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

_db_initialized = False

@app.before_request
def initialize_database():
    global _db_initialized
    if not _db_initialized:
        try:
            db.create_all()
            if not User.query.filter_by(role='admin').first():
                admin = User(name='Platform Admin', email='admin@studybyte.edu', password_hash=generate_password_hash('admin123'), role='admin')
                db.session.add(admin)
                db.session.commit()
            _db_initialized = True
        except Exception as e:
            print(f"CRITICAL DATABASE ERROR: {e}")
            _db_initialized = True # Prevent infinite retry loops that drain database connections

# ----------------- UTILS -----------------

@app.context_processor
def inject_user():
    user = None
    wallet = None
    notifications = []
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            wallet = Wallet.query.filter_by(user_id=user.id).first()
            notifications = Notification.query.filter_by(user_id=user.id, is_read=False).order_by(Notification.timestamp.desc()).all()
    return dict(current_user=user, wallet=wallet, unread_notifications=notifications)

def login_required(f):
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first.', 'error')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if user and user.status == 'Suspended':
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
    if modified:
        db.session.commit()

# ----------------- ROUTES -----------------

@app.route('/db-test')
def db_test():
    global _db_initialized
    try:
        db.create_all()
        return "Database connected and tables created successfully! Your URL is correct."
    except Exception as e:
        return f"DATABASE CONNECTION FAILED. ERROR DETAILS: {str(e)} <br><br> Make sure you did NOT leave brackets [ ] around your password in the Supabase URL, and if your password contains special characters like @ or #, you MUST change your database password in Supabase to only use letters and numbers!"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        student_id = request.form['student_id']
        email = request.form['email']
        password = request.form['password']
        department = request.form['department']
        role = request.form['role']
        
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
            name=name, email=email, 
            password_hash=generate_password_hash(password),
            role=role,
            studentId=student_id, department=department
        )
        
        # ----------------------------
        # BUG FIX #1: Strict unverified nature for all new bounds.
        # Learners default to false, ensuring a swap later blocks them properly.
        user.is_verified = False
        
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
        
        # First 5 users get bonus
        user_count = User.query.count()
        if user_count <= 5:
            bonus = 100.0
        else:
            bonus = 0.0
            
        wallet = Wallet(user_id=user.id, balance=bonus)
        db.session.add(wallet)
        if bonus > 0:
            bonus_history = TransactionHistory(user_id=user.id, amount=bonus, type='Bonus', description='Sign-up Bonus')
            db.session.add(bonus_history)
        db.session.commit()
        
        if bonus > 0:
            flash(f'Welcome! {int(bonus)} tokens have been added to your wallet as a sign-up bonus.', 'success')
        else:
            flash('Welcome! Registration successful.', 'success')
        return redirect(url_for('login'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        selected_role = request.form.get('role', 'learner')
        
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            if user.status == 'Suspended':
                flash('Your account has been suspended.', 'error')
                return redirect(url_for('login'))
                
            session['user_id'] = user.id
            
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
            if selected_role == 'tutor':
                return redirect(url_for('tutor_dashboard'))
            else:
                return redirect(url_for('learner_dashboard'))
                
        flash('Invalid credentials.', 'error')
    return render_template('login.html')

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
        user.is_verified = False
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
    upcoming = Booking.query.filter_by(learner_id=user.id).filter(Booking.status.in_(['Pending', 'Confirmed'])).all()
    past = Booking.query.filter_by(learner_id=user.id).filter(Booking.status.in_(['Completed', 'Cancelled'])).all()
    suggested = TopicListing.query.filter_by(is_advertised=True).join(User).filter(User.is_verified == True).limit(5).all()
    return render_template('learner_dashboard.html', upcoming_bookings=upcoming, past_bookings=past, suggested_listings=suggested)

@app.route('/tutor/dashboard')
@login_required
def tutor_dashboard():
    user = User.query.get(session['user_id'])
    listings = TopicListing.query.filter_by(tutor_id=user.id).all()
    
    listing_ids = [l.id for l in listings]
    bookings = Booking.query.filter(Booking.listing_id.in_(listing_ids)).order_by(Booking.timestamp.desc()).all()
    
    escrow_total = sum([tx.amount for tx in EscrowTransaction.query.filter(EscrowTransaction.booking_id.in_([b.id for b in bookings]), EscrowTransaction.status == 'Held').all()])
    
    return render_template('tutor_dashboard.html', listings=listings, bookings=bookings, escrow_balance=escrow_total)

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
    }
    
    pending_tutors = User.query.filter(User.grade_report != None, User.is_verified == False, User.rejection_reason == None).all()
    recent_purchases = TokenPurchaseRequest.query.order_by(TokenPurchaseRequest.timestamp.desc()).limit(15).all()
    withdrawals = WithdrawalRequest.query.filter_by(status='Pending').all()
    disputes = EscrowTransaction.query.filter_by(status='Held').all()
    all_users = User.query.all()
    
    return render_template('admin_dashboard.html', stats=stats, pending_tutors=pending_tutors, 
                           purchases=recent_purchases, withdrawals=withdrawals, disputes=disputes, users=all_users)

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
        tutor.is_verified = True
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
    query = User.query.filter_by(role='tutor', is_verified=True)
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
        return "Unauthorized", 403
    listing = TopicListing.query.get_or_404(listing_id)
    if listing.tutor_id != session['user_id']:
        return "Unauthorized", 403
        
    wallet = Wallet.query.filter_by(user_id=session['user_id']).first()
    cost = 40.0
    if wallet.balance < cost:
        flash('Insufficient tokens to advertise this course (40 Tokens required).', 'error')
        return redirect(url_for('tutor_dashboard'))
        
    wallet.balance -= cost
    listing.is_advertised = True
    
    hist = TransactionHistory(user_id=session['user_id'], amount=-cost, type='Advertisement', description=f"Paid for advertising course: {listing.title}")
    db.session.add(hist)
    db.session.commit()
    
    flash('Course successfully advertised!', 'success')
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
            flash('You have already confirmed.', 'error')
            return redirect(url_for('dashboard'))
        booking.learner_confirmed = True
        party = 'Learner'
    elif session['user_id'] == booking.listing.tutor_id:
        if booking.tutor_confirmed:
            flash('You have already confirmed.', 'error')
            return redirect(url_for('dashboard'))
        booking.tutor_confirmed = True
        party = 'Tutor'
    else:
        return "Unauthorized", 403
        
    db.session.commit()

    if booking.learner_confirmed and booking.tutor_confirmed:
        booking.status = 'Completed'
        escrow = EscrowTransaction.query.filter_by(booking_id=booking.id).first()
        if escrow and escrow.status == 'Held':
            escrow.status = 'Released'
            tutor_wallet = Wallet.query.filter_by(user_id=booking.listing.tutor_id).first()
            
            # Platform Fee: 5% deduction
            platform_fee = escrow.amount * 0.05
            tutor_payout = escrow.amount - platform_fee
            
            tutor_wallet.balance += tutor_payout
            
            hist = TransactionHistory(user_id=booking.listing.tutor_id, amount=tutor_payout, type='Received', description=f"Escrow released: {booking.listing.title} (after 5% fee)")
            db.session.add(hist)
            
            fee_hist = TransactionHistory(user_id=booking.listing.tutor_id, amount=platform_fee, type='Penalty', description=f"Platform Fee for {booking.listing.title}")
            db.session.add(fee_hist)
            
        db.session.commit()
        flash('Both parties confirmed! Session Verified and Escrow automatically released.', 'success')
    else:
        flash(f'{party} check-in recorded. Waiting for the other party to check in.', 'success')
        
    return redirect(url_for('dashboard'))

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

def verify_payment_api(method, payment_id):
    """ Realistic Mock for Payment Gateway Execute & Verify API """
    # Real logic: res = requests.post(f"https://checkout.{method.lower()}.com/api/v1/payment/execute", json={"paymentID": payment_id})
    # data = res.json()
    # return data.get('transactionStatus') == 'Completed', data.get('trxID')
    
    # Simulated successful transaction ID
    import string, random
    trx_id = f"TRX{method[:2].upper()}" + "".join(random.choices(string.digits + string.ascii_uppercase, k=8))
    return True, trx_id

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
        if not account_no or not account_no.startswith('01') or len(account_no) != 11:
            flash('Invalid account number provided. Transaction failed.', 'error')
            return redirect(url_for('wallet'))
            
        if not pin or len(pin) < 4:
            flash('Invalid PIN. Transaction failed.', 'error')
            return redirect(url_for('wallet'))
            
        # 3. Verify Payment
        # (In reality, we'd use a payment_id returned by the gateway, simulating it here)
        is_valid, final_trx_id = verify_payment_api(req.method, f"temp_{req.id}")
        
        if is_valid:
            req.status = 'Approved'
            req.transaction_id = final_trx_id
            req.mobile_number = account_no
            
            # 4. Automatically Credit Tokens
            wallet = Wallet.query.filter_by(user_id=req.user_id).first()
            wallet.balance += req.token_amount
            
            hist = TransactionHistory(user_id=req.user_id, amount=req.token_amount, type='Purchase', description=f"Bought via {req.method} ({final_trx_id})")
            db.session.add(hist)
            db.session.commit()
            
            flash(f'Payment successful! {req.token_amount} tokens added automatically. TRX ID: {final_trx_id}', 'success')
        else:
            req.status = 'Failed'
            db.session.commit()
            flash('Payment verification failed.', 'error')
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
        flash('Withdrawal rejected. Tokens refunded to user.', 'success')
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/dispute/<int:tx_id>', methods=['POST'])
@login_required
def resolve_dispute(tx_id):
    if session['role'] != 'admin':
        return "Unauthorized", 403
    
    action = request.form.get('action')
    tx = EscrowTransaction.query.get_or_404(tx_id)
    booking = Booking.query.get(tx.booking_id)

    if action == 'refund':
        tx.status = 'Refunded'
        booking.status = 'Cancelled'
        wallet = Wallet.query.filter_by(user_id=booking.learner_id).first()
        wallet.balance += tx.amount
        hist = TransactionHistory(user_id=booking.learner_id, amount=tx.amount, type='Refund', description=f"Admin dispute won - refund for {booking.listing.title}")
        db.session.add(hist)
        flash('Dispute resolved: Transaction refunded to learner.', 'success')
    
    elif action == 'pay_tutor':
        tx.status = 'Released'
        booking.status = 'Completed'
        tutor_wallet = Wallet.query.filter_by(user_id=booking.listing.tutor_id).first()
        tutor_wallet.balance += tx.amount
        hist = TransactionHistory(user_id=booking.listing.tutor_id, amount=tx.amount, type='Received', description=f"Admin dispute won - payment for {booking.listing.title}")
        db.session.add(hist)
        flash('Dispute resolved: Escrow forcefully cleared to Tutor.', 'success')
        
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
    
    wallet_learner = Wallet.query.filter_by(user_id=booking.learner_id).first()
    wallet_tutor = Wallet.query.filter_by(user_id=booking.listing.tutor_id).first()
    
    if is_learner:
        wallet_learner.balance += refund_amount
        wallet_tutor.balance += fee
        db.session.add(TransactionHistory(user_id=booking.learner_id, amount=refund_amount, type='Refund', description=f"Cancelled booking {booking.id} (-20% fee)"))
        if fee > 0:
             db.session.add(TransactionHistory(user_id=booking.listing.tutor_id, amount=fee, type='Compensation', description=f"Learner cancelled booking {booking.id} fee"))
    else:
        wallet_learner.balance += booking.listing.price
        db.session.add(TransactionHistory(user_id=booking.learner_id, amount=booking.listing.price, type='Refund', description=f"Tutor cancelled booking {booking.id}"))
        if fee > 0:
            wallet_tutor.balance -= fee
            db.session.add(TransactionHistory(user_id=booking.listing.tutor_id, amount=-fee, type='Penalty', description=f"Cancellation penalty booking {booking.id}"))
        
    db.session.commit()
    flash('Booking cancelled successfully.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/booking/<int:booking_id>/chat')
@login_required
def chat_room(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if not (session['user_id'] == booking.learner_id or session['user_id'] == booking.listing.tutor_id):
        return "Unauthorized", 403
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

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000, allow_unsafe_werkzeug=True)
