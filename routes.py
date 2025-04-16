from flask import render_template, request, redirect, url_for, jsonify, flash, session, send_file
from app import app, db, login_manager
from models import Branch, Staff, Reservation, Customer, Log, Setting, User, Role
from forms import LoginForm, UserForm, RoleForm
from datetime import datetime, timedelta, date, time
from sqlalchemy import func, extract, and_, case, or_, text
from flask_login import login_user, logout_user, login_required, current_user
import calendar
import asyncio
import logging
from threading import Thread
# Telegram servisini aktif hale getiriyoruz
from telegram_service import send_message, send_reservation_notification, send_cancellation_notification
from functools import wraps
import os

def get_date_range(period, request_obj):
    """
    Belirtilen dönem ve isteğe bağlı tarihler için tarih aralığı oluşturur
    
    Args:
        period: Dönem tanımı (this_week, this_month, last_month, this_year, custom)
        request_obj: Flask request nesnesi (custom dönem için start_date/end_date parametrelerini almak için)
    
    Returns:
        tuple: (start_date, end_date) - başlangıç ve bitiş tarihleri
    """
    # Define date range based on selected period - with Turkey timezone (UTC+3)
    utc_now = datetime.now()
    turkey_time_offset = timedelta(hours=3)
    now = utc_now + turkey_time_offset  # Türkiye saati
    today = now.date()
    
    if period == 'this_week':
        # Pazartesi-Pazar olarak bu hafta
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
    elif period == 'this_month':
        # Bu ayın tamamı
        start_date = date(today.year, today.month, 1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        end_date = date(today.year, today.month, last_day)
    elif period == 'last_month':
        # Geçen ayın tamamı
        last_month = today.month - 1 if today.month > 1 else 12
        last_month_year = today.year if today.month > 1 else today.year - 1
        start_date = date(last_month_year, last_month, 1)
        last_day = calendar.monthrange(last_month_year, last_month)[1]
        end_date = date(last_month_year, last_month, last_day)
    elif period == 'this_year':
        # Bu yıl başından bugüne kadar
        start_date = date(today.year, 1, 1)
        end_date = today
    elif period == 'custom':
        # Özel tarih aralığı
        try:
            start_date = datetime.strptime(request_obj.args.get('start_date'), '%Y-%m-%d').date()
            end_date = datetime.strptime(request_obj.args.get('end_date'), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            # Geçersiz veya eksik tarihler için bu ayı kullan
            start_date = date(today.year, today.month, 1)
            last_day = calendar.monthrange(today.year, today.month)[1]
            end_date = date(today.year, today.month, last_day)
    else:
        # Bilinmeyen dönem için bu ayı kullan
        start_date = date(today.year, today.month, 1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        end_date = date(today.year, today.month, last_day)
        
    return start_date, end_date

# Logger kurulumu
logger = logging.getLogger(__name__)

# Kullanıcı izin kontrolü için dekoratör
def role_required(permission):
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Bu sayfaya erişmek için giriş yapmalısınız.', 'warning')
                return redirect(url_for('login', next=request.url))
            
            if not current_user.has_permission(permission):
                flash('Bu işlemi yapmak için yetkiniz bulunmuyor.', 'danger')
                return redirect(url_for('home'))
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Eğer kullanıcı zaten giriş yapmışsa ana sayfaya yönlendir
    if current_user.is_authenticated:
        return redirect(url_for('home'))
        
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        
        if user and user.check_password(form.password.data):
            if not user.is_active:
                flash('Bu hesap devre dışı bırakılmış. Lütfen yöneticinize başvurun.', 'danger')
                return render_template('login.html', form=form)
                
            login_user(user, remember=form.remember_me.data)
            
            # Son giriş tarihini güncelle
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            # Log ekle
            Log.add_log(
                log_type="SYSTEM",
                action="LOGIN",
                details=f"User {user.username} logged in",
                user_id=user.id,
                branch_id=user.branch_id
            )
            
            next_page = request.args.get('next')
            return redirect(next_page or url_for('home'))
        else:
            flash('Kullanıcı adı veya şifre hatalı.', 'danger')
            
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    # Log ekle
    Log.add_log(
        log_type="SYSTEM",
        action="LOGOUT",
        details=f"User {current_user.username} logged out",
        user_id=current_user.id,
        branch_id=current_user.branch_id
    )
    
    logout_user()
    flash('Başarıyla çıkış yaptınız.', 'success')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def home():
    branches = Branch.query.all()
    selected_branch_id = request.args.get('branch_id', None)
    
    # If no branch is selected and branches exist, select the first one
    if not selected_branch_id and branches:
        selected_branch_id = branches[0].id
    
    # Store the selected branch in session
    if selected_branch_id:
        session['selected_branch_id'] = int(selected_branch_id)
    
    return render_template('home.html', branches=branches, selected_branch_id=selected_branch_id)

@app.route('/reservation')
def reservation():
    # Get branches and staff for the forms
    branches = Branch.query.all()
    
    # Get the selected branch_id from the session or query parameter
    branch_id = request.args.get('branch_id', session.get('selected_branch_id'))
    
    if not branch_id and branches:
        branch_id = branches[0].id
        session['selected_branch_id'] = int(branch_id)
    
    # Get staff for the selected branch
    staff = []
    if branch_id:
        staff = Staff.query.filter_by(branch_id=branch_id).all()
    
    # Get current date as the starting date - manually set to UTC+3 (Turkey time)
    # Sunucu UTC olduğu için +3 saat ekleyelim (Türkiye saati)
    utc_now = datetime.now()
    turkey_time_offset = timedelta(hours=3)
    now = utc_now + turkey_time_offset  # Türkiye saati
    today = now.date()
    current_time = now.time()
    
    # Bir sonraki saat için hesaplama yapalım
    current_hour = now.hour
    next_hour = (current_hour + 1)
    
    # Debug: Şu anki saati görelim
    print(f"DEBUG - UTC time: {utc_now}, Turkey time: {now}, Current hour: {current_hour}")
    
    # Get date range from the query parameters or use default
    start_date_str = request.args.get('start_date')
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        except ValueError:
            start_date = today
    else:
        start_date = today
    
    # Generate dates for the next 7 days starting from start_date
    dates = [start_date + timedelta(days=i) for i in range(7)]
    
    # Get working hours from the database or session
    # If not set yet, use default hours
    default_hours = [f"{i:02d}:00" for i in range(9, 23)]  # 9 AM - 10 PM
    hours = session.get('working_hours', default_hours)
    
    # Get custom working hours from query parameters
    custom_hours = request.args.get('hours')
    if custom_hours:
        try:
            # Parse hours from the format like "09:00,10:00,11:00,..."
            hours = custom_hours.split(',')
            session['working_hours'] = hours
        except:
            # If parsing fails, keep using the current hours
            pass
    
    # Get existing reservations for this branch and selected date range
    reservations = {}
    if branch_id:
        for d in dates:
            for h in hours:
                time_obj = datetime.strptime(h, "%H:%M").time()
                res = Reservation.query.filter(
                    Reservation.branch_id == branch_id,
                    Reservation.reservation_date == d,
                    Reservation.reservation_time == time_obj,
                    Reservation.is_canceled == False  # İptal edilmeyen rezervasyonları göster
                ).first()
                
                if res:
                    key = f"{d.isoformat()}-{h}"
                    reservations[key] = {
                        'id': res.id,
                        'customer_name': res.customer_name,
                        'num_people': res.num_people,
                        'payment_status': res.payment_status,
                        'advance_payment_percentage': res.advance_payment_percentage
                    }
    
    # Previous and next week links
    prev_date = start_date - timedelta(days=7)
    next_date = start_date + timedelta(days=7)
    
    return render_template(
        'reservation.html', 
        branches=branches,
        selected_branch_id=branch_id,
        staff=staff,
        dates=dates,
        hours=hours,
        reservations=reservations,
        today=today,
        now=now,
        current_time=current_time,
        current_hour=current_hour,
        next_hour=next_hour,
        start_date=start_date,
        timedelta=timedelta,
        prev_date=prev_date,
        next_date=next_date
    )

@app.route('/api/get_staff', methods=['GET'])
def get_staff():
    branch_id = request.args.get('branch_id')
    if not branch_id:
        return jsonify({'error': 'Missing branch_id parameter'}), 400
        
    staff = Staff.query.filter_by(branch_id=branch_id).all()
    return jsonify([{'id': s.id, 'name': s.name} for s in staff])

@app.route('/api/save_reservation', methods=['POST'])
def save_reservation():
    try:
        # Get form data
        data = request.form
        
        # Debug log to track request
        print(f"Saving reservation: Customer={data.get('customerName')}, Date={data.get('reservationDate')}, Time={data.get('reservationTime')}")
        
        # Form token kontrolünü geçici olarak devre dışı bırakıyoruz
        form_token = data.get('form_token')
        if form_token:
            print(f"Form token received: {form_token}")
            
        # Create new reservation
        new_reservation = Reservation(
            customer_name=data['customerName'],
            customer_phone=data['customerPhone'],
            num_people=int(data['numPeople']),
            total_price=float(data['totalPrice']),
            advance_payment_percentage=float(data['advancePaymentPercentage']),
            payment_type=data['paymentType'],
            payment_status=data.get('paymentStatus', 'PENDING'),
            branch_id=int(data['branchId']),
            staff_id=int(data['staffId']),
            reservation_date=datetime.strptime(data['reservationDate'], "%Y-%m-%d").date(),
            reservation_time=datetime.strptime(data['reservationTime'], "%H:%M").time(),
        )
        
        # Use save_with_customer method to automatically associate with customer record
        # This no longer creates logs directly
        new_reservation.save_with_customer()
        db.session.add(new_reservation)
        db.session.commit()
        
        # Check if a new customer was created during reservation and log it
        customer = Customer.query.filter_by(phone=new_reservation.customer_phone).first()
        is_first_reservation = Reservation.query.filter_by(customer_id=customer.id).count() == 1
        
        # Add logs after commit to improve performance
        if is_first_reservation:
            Log.add_log(
                log_type="CUSTOMER",
                action="CREATE",
                details=f"New customer created: {new_reservation.customer_name} ({new_reservation.customer_phone})",
                branch_id=new_reservation.branch_id
            )
            
        # Add reservation log entry
        Log.add_log(
            log_type="RESERVATION",
            action="CREATE",
            details=f"New reservation created: {new_reservation.customer_name} on {new_reservation.reservation_date} at {new_reservation.reservation_time}",
            branch_id=new_reservation.branch_id
        )
        
        # Get branch and staff details for response
        branch = Branch.query.get(new_reservation.branch_id)
        staff = Staff.query.get(new_reservation.staff_id)
        
        response = {
            'success': True, 
            'id': new_reservation.id,
            # Include details for client-side Telegram notification if needed
            'telegram_enabled': branch.telegram_enabled if branch else False,
            'telegram_chat_id': branch.telegram_chat_id if branch else None,
            'branch_name': branch.name if branch else 'Unknown',
            'staff_name': staff.name if staff else 'Unknown'
        }
        
        return jsonify(response)
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})
        
@app.route('/api/send_telegram_notification', methods=['POST'])
def send_telegram_notification():
    """Send a Telegram notification from a separate endpoint to avoid session conflicts"""
    try:
        # Get the data from request
        data = request.json
        
        # Check if we have the required data
        if not data or not data.get('reservation_id'):
            return jsonify({'success': False, 'error': 'Geçersiz veri'})
            
        # Create a separate session to avoid conflicts
        from telegram_service import send_message
        
        # Ödeme tipini Türkçeleştir
        payment_type = data.get('payment_type', '-')
        payment_type_tr = {
            "CASH": "🧾 Nakit",
            "POS": "💳 Kredi Kartı",
            "IBAN": "🏦 Havale/EFT",
            "OTHER": "📝 Diğer"
        }.get(payment_type, payment_type)
        
        # Ödeme durumunu emojilerle belirt
        payment_status = data.get('payment_status', 'PENDING')
        payment_status_text = {
            "PENDING": "⏳ Ödeme Bekliyor",
            "ADVANCE": "💰 Ön Ödeme Yapıldı",
            "PAID": "✅ Tamamen Ödendi"
        }.get(payment_status, payment_status)
        
        # Create the message using the provided data
        message = f"""
<b>🎉 YENİ REZERVASYON OLUŞTURULDU 🎉</b>
━━━━━━━━━━━━━━━━━━━━━━━

🏢 <b>Şube:</b> {data.get('branch_name', 'Belirtilmemiş')}
👤 <b>Müşteri:</b> {data.get('customer_name', 'Belirtilmemiş')}
📞 <b>Telefon:</b> {data.get('customer_phone', 'Belirtilmemiş')}
👥 <b>Kişi Sayısı:</b> {data.get('num_people', '0')}
🗓️ <b>Tarih/Saat:</b> {data.get('reservation_date', '-')} | ⏰ {data.get('reservation_time', '-')}
👨‍💼 <b>Personel:</b> {data.get('staff_name', 'Belirtilmemiş')}

💵 <b>Toplam Ücret:</b> ₺{float(data.get('total_price', 0)):.2f}
💸 <b>Ön Ödeme:</b> ₺{float(data.get('advance_payment', 0)):.2f} (%{float(data.get('advance_payment_percentage', 0))})
💱 <b>Kalan Tutar:</b> ₺{float(data.get('remaining_amount', 0)):.2f}
💳 <b>Ödeme Tipi:</b> {payment_type_tr}
📊 <b>Ödeme Durumu:</b> {payment_status_text}

🆔 <b>Rezervasyon ID:</b> #{data.get('reservation_id', '0')}
━━━━━━━━━━━━━━━━━━━━━━━
<i>Bu mesaj otomatik olarak gönderilmiştir.</i>
"""
        
        # Send message directly
        chat_id = data.get('telegram_chat_id')
        if not chat_id:
            return jsonify({'success': False, 'error': 'Telegram chat ID mevcut değil'})
            
        result = send_message(chat_id, message)
        
        if result:
            print(f"Telegram notification sent successfully for reservation ID: {data.get('reservation_id')}")
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Telegram bildirimi gönderilirken bir hata oluştu'})
            
    except Exception as e:
        print(f"Error sending Telegram notification: {e}")
        import traceback
        print(f"Detailed error: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/branch_summary')
def branch_summary():
    """Tüm şubelerin özet raporu"""
    branches = Branch.query.all()
    selected_period = request.args.get('period', 'this_month')
    
    # Store selected branch in session (for consistency across pages, even if not needed here)
    branch_id = request.args.get('branch_id', session.get('selected_branch_id'))
    if branch_id:
        session['selected_branch_id'] = int(branch_id)
    
    # Tarih aralığını belirle
    start_date, end_date = get_date_range(selected_period, request)
    
    branch_data = []
    total_reservation_count = 0
    total_guests = 0
    total_revenue = 0
    
    # Her şube için verileri topla
    for branch in branches:
        # Aktif rezervasyon sayısı
        active_reservation_count = Reservation.query.filter(
            Reservation.branch_id == branch.id,
            Reservation.reservation_date >= start_date,
            Reservation.reservation_date <= end_date,
            Reservation.is_canceled == False
        ).count()
        
        # İptal edilen rezervasyon sayısı
        canceled_reservation_count = Reservation.query.filter(
            Reservation.branch_id == branch.id,
            Reservation.reservation_date >= start_date,
            Reservation.reservation_date <= end_date,
            Reservation.is_canceled == True
        ).count()
        
        # Toplam rezervasyon sayısı (aktif + iptal)
        branch_reservation_count = active_reservation_count + canceled_reservation_count
        
        # Misafir sayısı (sadece aktif rezervasyonlar)
        branch_total_guests = db.session.query(func.sum(Reservation.num_people)).filter(
            Reservation.branch_id == branch.id,
            Reservation.reservation_date >= start_date,
            Reservation.reservation_date <= end_date,
            Reservation.is_canceled == False
        ).scalar() or 0
        
        # Toplam ciro - aktif rezervasyonlar
        active_reservations_revenue = db.session.query(func.sum(Reservation.total_price)).filter(
            Reservation.branch_id == branch.id,
            Reservation.reservation_date >= start_date,
            Reservation.reservation_date <= end_date,
            Reservation.is_canceled == False
        ).scalar() or 0
        
        # İptal edilen rezervasyonlardan kalan gelir (iade olmayan iptal işlemlerindeki ön ödemeler)
        canceled_reservations_revenue = db.session.query(func.sum(Reservation.cancel_revenue)).filter(
            Reservation.branch_id == branch.id,
            Reservation.reservation_date >= start_date,
            Reservation.reservation_date <= end_date,
            Reservation.is_canceled == True,
            Reservation.cancel_revenue > 0
        ).scalar() or 0
        
        # Toplam gelir = aktif rezervasyonlar + iptal edilenlerden kalan ön ödemeler
        branch_total_revenue = active_reservations_revenue + canceled_reservations_revenue
        
        # Genel toplamlara ekle
        total_reservation_count += branch_reservation_count
        total_guests += branch_total_guests
        total_revenue += branch_total_revenue
        
        # Şube verilerini ekle
        branch_data.append({
            'id': branch.id,
            'name': branch.name,
            'active_count': active_reservation_count,
            'canceled_count': canceled_reservation_count,
            'reservation_count': branch_reservation_count,
            'total_guests': branch_total_guests,
            'total_revenue': branch_total_revenue,
            'revenue_percentage': 0  # Daha sonra hesaplanacak
        })
    
    # Ciro oranlarını hesapla (toplam veriler toplandıktan sonra)
    for branch in branch_data:
        branch['revenue_percentage'] = (branch['total_revenue'] / total_revenue * 100) if total_revenue > 0 else 0
    
    # Aktif ve iptal edilmiş rezervasyon sayılarını hesapla
    total_active_count = sum(branch['active_count'] for branch in branch_data)
    total_canceled_count = sum(branch['canceled_count'] for branch in branch_data)
    
    # Toplam verileri
    total_data = {
        'reservation_count': total_reservation_count,
        'active_count': total_active_count,
        'canceled_count': total_canceled_count,
        'total_guests': total_guests,
        'total_revenue': total_revenue
    }
    
    return render_template(
        'branch_summary.html',
        branches=branches,
        branch_data=branch_data,
        total_data=total_data,
        selected_period=selected_period,
        start_date=start_date.strftime('%Y-%m-%d') if start_date else '',
        end_date=end_date.strftime('%Y-%m-%d') if end_date else ''
    )

@app.route('/reports')
def reports():
    """Report & Statistics page"""
    branches = Branch.query.all()
    
    # Get selected branch_id from query param or session
    branch_id = request.args.get('branch_id', session.get('selected_branch_id'))
    
    if not branch_id and branches:
        branch_id = branches[0].id
        session['selected_branch_id'] = int(branch_id)
    
    # Set default period to current month
    selected_period = request.args.get('period', 'month')
    
    # Get staff data for selected branch
    staff_data = []
    branch_data = {}
    
    if branch_id:
        branch_id = int(branch_id)
        
        # Define date range based on selected period - with Turkey timezone (UTC+3)
        utc_now = datetime.now()
        turkey_time_offset = timedelta(hours=3)
        now = utc_now + turkey_time_offset  # Türkiye saati
        today = now.date()
        
        if selected_period == 'day':
            start_date = today
            end_date = today
        elif selected_period == 'week':
            start_date = today - timedelta(days=today.weekday())
            end_date = start_date + timedelta(days=6)
        elif selected_period == 'month':
            start_date = date(today.year, today.month, 1)
            last_day = calendar.monthrange(today.year, today.month)[1]
            end_date = date(today.year, today.month, last_day)
        else:  # all-time
            start_date = date(1900, 1, 1)  # Beginning of time
            end_date = date(2100, 12, 31)  # Far in the future
        
        # Get data for each staff
        staff_members = Staff.query.filter_by(branch_id=branch_id).all()
        
        for staff in staff_members:
            # Aktif rezervasyon sayısı
            active_reservation_count = Reservation.query.filter(
                Reservation.staff_id == staff.id,
                Reservation.branch_id == branch_id,
                Reservation.reservation_date >= start_date,
                Reservation.reservation_date <= end_date,
                Reservation.is_canceled == False
            ).count()
            
            # İptal edilen rezervasyon sayısı
            canceled_reservation_count = Reservation.query.filter(
                Reservation.staff_id == staff.id,
                Reservation.branch_id == branch_id,
                Reservation.reservation_date >= start_date,
                Reservation.reservation_date <= end_date,
                Reservation.is_canceled == True
            ).count()
            
            # Toplam rezervasyon sayısı (aktif + iptal)
            reservation_count = active_reservation_count + canceled_reservation_count
            
            # Misafir sayısını sadece aktif rezervasyonlardan hesapla
            total_guests = db.session.query(func.sum(Reservation.num_people)).filter(
                Reservation.staff_id == staff.id,
                Reservation.branch_id == branch_id,
                Reservation.reservation_date >= start_date,
                Reservation.reservation_date <= end_date,
                Reservation.is_canceled == False
            ).scalar() or 0
            
            # Personelin aktif rezervasyonlarından gelir
            active_reservations_revenue = db.session.query(func.sum(Reservation.total_price)).filter(
                Reservation.staff_id == staff.id,
                Reservation.branch_id == branch_id,
                Reservation.reservation_date >= start_date,
                Reservation.reservation_date <= end_date,
                Reservation.is_canceled == False
            ).scalar() or 0
            
            # Personelin iptal edilen rezervasyonlarından kalan gelir
            canceled_reservations_revenue = db.session.query(func.sum(Reservation.cancel_revenue)).filter(
                Reservation.staff_id == staff.id,
                Reservation.branch_id == branch_id,
                Reservation.reservation_date >= start_date,
                Reservation.reservation_date <= end_date,
                Reservation.is_canceled == True,
                Reservation.cancel_revenue > 0
            ).scalar() or 0
            
            # Toplam gelir
            total_revenue = active_reservations_revenue + canceled_reservations_revenue
            
            staff_data.append({
                'name': staff.name,
                'reservation_count': reservation_count,
                'active_count': active_reservation_count,
                'canceled_count': canceled_reservation_count,
                'total_guests': total_guests,
                'total_revenue': total_revenue,
                'active_revenue': active_reservations_revenue,
                'canceled_revenue': canceled_reservations_revenue
            })
        
        # Get branch summary data - Aktif rezervasyonlar
        active_reservation_count = Reservation.query.filter(
            Reservation.branch_id == branch_id,
            Reservation.reservation_date >= start_date,
            Reservation.reservation_date <= end_date,
            Reservation.is_canceled == False
        ).count()
        
        # İptal edilmiş rezervasyonlar
        canceled_reservation_count = Reservation.query.filter(
            Reservation.branch_id == branch_id,
            Reservation.reservation_date >= start_date,
            Reservation.reservation_date <= end_date,
            Reservation.is_canceled == True
        ).count()
        
        # Toplam rezervasyon sayısı (aktif + iptal)
        branch_reservation_count = active_reservation_count + canceled_reservation_count
        
        # Misafir sayısını sadece aktif rezervasyonlardan hesapla
        branch_total_guests = db.session.query(func.sum(Reservation.num_people)).filter(
            Reservation.branch_id == branch_id,
            Reservation.reservation_date >= start_date,
            Reservation.reservation_date <= end_date,
            Reservation.is_canceled == False
        ).scalar() or 0
        
        # Aktif rezervasyonların toplam geliri
        active_reservations_revenue = db.session.query(func.sum(Reservation.total_price)).filter(
            Reservation.branch_id == branch_id,
            Reservation.reservation_date >= start_date,
            Reservation.reservation_date <= end_date,
            Reservation.is_canceled == False
        ).scalar() or 0
        
        # İptal edilmiş rezervasyonlardan kalan gelir (ön ödemeler)
        canceled_reservations_revenue = db.session.query(func.sum(Reservation.cancel_revenue)).filter(
            Reservation.branch_id == branch_id,
            Reservation.reservation_date >= start_date,
            Reservation.reservation_date <= end_date,
            Reservation.is_canceled == True,
            Reservation.cancel_revenue > 0
        ).scalar() or 0
        
        # Toplam gelir = aktif rezervasyonlar + iptal edilenlerden kalan ön ödemeler
        branch_total_revenue = active_reservations_revenue + canceled_reservations_revenue
        
        branch_data = {
            'reservation_count': branch_reservation_count,
            'active_count': active_reservation_count,
            'canceled_count': canceled_reservation_count,
            'total_guests': branch_total_guests,
            'total_revenue': branch_total_revenue,
            'active_revenue': active_reservations_revenue,
            'canceled_revenue': canceled_reservations_revenue
        }
    
    return render_template(
        'reports.html',
        branches=branches,
        selected_branch_id=branch_id,
        selected_period=selected_period,
        staff_data=staff_data,
        branch_data=branch_data
    )

@app.route('/branches')
def branches():
    """Branch management page"""
    branches = Branch.query.all()
    
    return render_template('branches.html', branches=branches)

@app.route('/api/add_branch', methods=['POST'])
def add_branch():
    """Add a new branch"""
    try:
        # Get form data
        branch_name = request.form.get('branchName')
        branch_address = request.form.get('branchAddress')
        
        # Validate data
        if not branch_name:
            return jsonify({'success': False, 'error': 'Şube adı gereklidir'})
        
        # Create new branch
        new_branch = Branch(
            name=branch_name,
            address=branch_address
        )
        
        db.session.add(new_branch)
        db.session.commit()
        
        return jsonify({'success': True, 'id': new_branch.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/update_branch', methods=['POST'])
def update_branch():
    """Update an existing branch"""
    try:
        # Get form data - support both camelCase and snake_case for compatibility
        branch_id = request.form.get('branch_id', request.form.get('branchId'))
        branch_name = request.form.get('branch_name', request.form.get('branchName'))
        branch_address = request.form.get('branch_address', request.form.get('branchAddress'))
        
        # Debug log
        print(f"Update branch called with: {request.form}")
        
        # Validate data
        if not branch_id:
            return jsonify({'success': False, 'error': 'Şube ID gereklidir'})
        
        # Find branch
        branch = Branch.query.get(branch_id)
        if not branch:
            return jsonify({'success': False, 'error': 'Şube bulunamadı'})
        
        # Update branch name and address if provided
        if branch_name:
            branch.name = branch_name
        if branch_address:
            branch.address = branch_address
        
        # Update Telegram settings if provided
        telegram_chat_id = request.form.get('telegram_chat_id', request.form.get('telegramChatId'))
        
        # Check for enabled status in different formats
        telegram_enabled = False
        if 'telegram_enabled' in request.form:
            telegram_enabled_value = request.form.get('telegram_enabled')
            telegram_enabled = telegram_enabled_value.lower() in ('true', 'yes', 'on', '1')
        elif 'telegramEnabled' in request.form:
            telegram_enabled = True
            
        if telegram_chat_id is not None:
            branch.telegram_chat_id = telegram_chat_id
            
        branch.telegram_enabled = telegram_enabled
        
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/delete_branch', methods=['POST'])
def delete_branch():
    """Delete a branch and all related staff and reservations"""
    try:
        # Get branch ID
        branch_id = request.form.get('branchId')
        
        if not branch_id:
            return jsonify({'success': False, 'error': 'Şube ID gereklidir'})
        
        # Find branch
        branch = Branch.query.get(branch_id)
        if not branch:
            return jsonify({'success': False, 'error': 'Şube bulunamadı'})
        
        # Delete related staff and reservations
        Staff.query.filter_by(branch_id=branch_id).delete()
        Reservation.query.filter_by(branch_id=branch_id).delete()
        
        # Delete branch
        db.session.delete(branch)
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/staff')
def staff():
    """Staff management page"""
    branches = Branch.query.all()
    
    # Get selected branch_id from query param or session
    selected_branch_id = request.args.get('branch_id', 'all')
    
    # Get staff list based on branch selection
    if selected_branch_id == 'all':
        staff_list = Staff.query.all()
    else:
        staff_list = Staff.query.filter_by(branch_id=selected_branch_id).all()
    
    return render_template('staff.html', branches=branches, staff_list=staff_list, selected_branch_id=selected_branch_id)

@app.route('/api/add_staff', methods=['POST'])
def add_staff():
    """Add a new staff member"""
    try:
        # Get form data
        staff_name = request.form.get('staffName')
        staff_phone = request.form.get('staffPhone')
        staff_branch_id = request.form.get('staffBranchId')
        
        # Validate data
        if not staff_name or not staff_branch_id:
            return jsonify({'success': False, 'error': 'İsim ve şube gereklidir'})
        
        # Create new staff
        new_staff = Staff(
            name=staff_name,
            phone=staff_phone,
            branch_id=staff_branch_id
        )
        
        db.session.add(new_staff)
        db.session.commit()
        
        return jsonify({'success': True, 'id': new_staff.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/update_staff', methods=['POST'])
def update_staff():
    """Update an existing staff member"""
    try:
        # Get form data
        staff_id = request.form.get('staffId')
        staff_name = request.form.get('staffName')
        staff_phone = request.form.get('staffPhone')
        staff_branch_id = request.form.get('staffBranchId')
        
        # Validate data
        if not staff_id or not staff_name or not staff_branch_id:
            return jsonify({'success': False, 'error': 'ID, isim ve şube gereklidir'})
        
        # Find staff
        staff = Staff.query.get(staff_id)
        if not staff:
            return jsonify({'success': False, 'error': 'Personel bulunamadı'})
        
        # Update staff
        staff.name = staff_name
        staff.phone = staff_phone
        staff.branch_id = staff_branch_id
        
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/delete_staff', methods=['POST'])
def delete_staff():
    """Delete a staff member and reassign their reservations"""
    try:
        # Get staff ID
        staff_id = request.form.get('staffId')
        
        if not staff_id:
            return jsonify({'success': False, 'error': 'Personel ID gereklidir'})
        
        # Find staff
        staff = Staff.query.get(staff_id)
        if not staff:
            return jsonify({'success': False, 'error': 'Personel bulunamadı'})
        
        # Delete reservations for this staff
        Reservation.query.filter_by(staff_id=staff_id).delete()
        
        # Delete staff
        db.session.delete(staff)
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/branch_comparison')
def branch_comparison():
    """Branch comparison report page"""
    branches = Branch.query.all()
    
    # Set default period to current month
    selected_period = request.args.get('period', 'this_month')
    
    # Store selected branch in session (required for navigation, even if not used in this page)
    branch_id = request.args.get('branch_id', session.get('selected_branch_id'))
    if branch_id:
        session['selected_branch_id'] = int(branch_id)
    
    # Define date range based on selected period - with Turkey timezone (UTC+3)
    utc_now = datetime.now()
    turkey_time_offset = timedelta(hours=3)
    now = utc_now + turkey_time_offset  # Türkiye saati
    today = now.date()
    
    if selected_period == 'day':
        start_date = today
        end_date = today
    elif selected_period == 'week':
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
    elif selected_period == 'month':
        start_date = date(today.year, today.month, 1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        end_date = date(today.year, today.month, last_day)
    else:  # all-time
        start_date = date(1900, 1, 1)  # Beginning of time
        end_date = date(2100, 12, 31)  # Far in the future
    
    # Get data for all branches
    branch_data = []
    
    for branch in branches:
        # Aktif rezervasyon sayısı
        active_reservation_count = Reservation.query.filter(
            Reservation.branch_id == branch.id,
            Reservation.reservation_date >= start_date,
            Reservation.reservation_date <= end_date,
            Reservation.is_canceled == False
        ).count()
        
        # İptal edilen rezervasyon sayısı
        canceled_reservation_count = Reservation.query.filter(
            Reservation.branch_id == branch.id,
            Reservation.reservation_date >= start_date,
            Reservation.reservation_date <= end_date,
            Reservation.is_canceled == True
        ).count()
        
        # Toplam rezervasyon sayısı (aktif + iptal)
        reservation_count = active_reservation_count + canceled_reservation_count
        
        # Misafir sayısını sadece aktif rezervasyonlardan hesapla
        total_guests = db.session.query(func.sum(Reservation.num_people)).filter(
            Reservation.branch_id == branch.id,
            Reservation.reservation_date >= start_date,
            Reservation.reservation_date <= end_date,
            Reservation.is_canceled == False
        ).scalar() or 0
        
        # Aktif rezervasyonlardan gelir
        active_reservations_revenue = db.session.query(func.sum(Reservation.total_price)).filter(
            Reservation.branch_id == branch.id,
            Reservation.reservation_date >= start_date,
            Reservation.reservation_date <= end_date,
            Reservation.is_canceled == False
        ).scalar() or 0
        
        # İptal edilen rezervasyonlardan kalan gelir
        canceled_reservations_revenue = db.session.query(func.sum(Reservation.cancel_revenue)).filter(
            Reservation.branch_id == branch.id,
            Reservation.reservation_date >= start_date,
            Reservation.reservation_date <= end_date,
            Reservation.is_canceled == True,
            Reservation.cancel_revenue > 0
        ).scalar() or 0
        
        # Toplam gelir
        total_revenue = active_reservations_revenue + canceled_reservations_revenue
        
        # Calculate average price per reservation (if there are active reservations)
        avg_price = active_reservations_revenue / active_reservation_count if active_reservation_count > 0 else 0
        
        # Calculate average guests per reservation (if there are active reservations)
        avg_guests = total_guests / active_reservation_count if active_reservation_count > 0 else 0
        
        branch_data.append({
            'name': branch.name,
            'reservation_count': reservation_count,
            'active_count': active_reservation_count,
            'canceled_count': canceled_reservation_count,
            'total_guests': total_guests,
            'total_revenue': total_revenue,
            'active_revenue': active_reservations_revenue,
            'canceled_revenue': canceled_reservations_revenue,
            'avg_price': avg_price,
            'avg_guests': avg_guests
        })
    
    return render_template(
        'branch_comparison.html',
        branches=branches,
        selected_period=selected_period,
        branch_data=branch_data
    )

@app.route('/api/get_reservation', methods=['GET'])
def get_reservation():
    """Get reservation details by ID"""
    reservation_id = request.args.get('id')
    
    if not reservation_id:
        return jsonify({'success': False, 'error': 'Rezervasyon ID gereklidir'})
    
    reservation = Reservation.query.get(reservation_id)
    
    if not reservation:
        return jsonify({'success': False, 'error': 'Rezervasyon bulunamadı'})
    
    return jsonify({
        'success': True,
        'reservation': {
            'id': reservation.id,
            'customer_name': reservation.customer_name,
            'customer_phone': reservation.customer_phone,
            'num_people': reservation.num_people,
            'total_price': reservation.total_price,
            'advance_payment_percentage': reservation.advance_payment_percentage,
            'payment_type': reservation.payment_type,
            'branch_id': reservation.branch_id,
            'staff_id': reservation.staff_id,
            'reservation_date': reservation.reservation_date.isoformat(),
            'reservation_time': reservation.reservation_time.strftime('%H:%M')
        }
    })

@app.route('/api/update_reservation', methods=['POST'])
def update_reservation():
    """Update an existing reservation"""
    try:
        # Get form data
        data = request.form
        reservation_id = data.get('reservationId')
        
        if not reservation_id:
            return jsonify({'success': False, 'error': 'Rezervasyon ID gereklidir'})
        
        # Find reservation
        reservation = Reservation.query.get(reservation_id)
        if not reservation:
            return jsonify({'success': False, 'error': 'Rezervasyon bulunamadı'})
        
        # Update reservation
        reservation.customer_name = data.get('customerName')
        reservation.customer_phone = data.get('customerPhone')
        reservation.num_people = int(data.get('numPeople'))
        reservation.total_price = float(data.get('totalPrice'))
        reservation.advance_payment_percentage = float(data.get('advancePaymentPercentage'))
        reservation.payment_type = data.get('paymentType')
        reservation.branch_id = int(data.get('branchId'))
        reservation.staff_id = int(data.get('staffId'))
        
        # Only update date and time if provided (might be editing without changing slot)
        if 'reservationDate' in data and 'reservationTime' in data:
            reservation.reservation_date = datetime.strptime(data.get('reservationDate'), "%Y-%m-%d").date()
            reservation.reservation_time = datetime.strptime(data.get('reservationTime'), "%H:%M").time()
        
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/delete_reservation', methods=['POST'])
def delete_reservation():
    """Mark a reservation as canceled (instead of deleting it)"""
    try:
        # Get reservation ID
        reservation_id = request.form.get('reservationId')
        with_refund = request.form.get('withRefund', 'false').lower() == 'true'
        
        if not reservation_id:
            return jsonify({'success': False, 'error': 'Rezervasyon ID gereklidir'})
        
        # Find reservation
        reservation = Reservation.query.get(reservation_id)
        if not reservation:
            return jsonify({'success': False, 'error': 'Rezervasyon bulunamadı'})
            
        # Get branch and staff info for Telegram notification
        branch = Branch.query.get(reservation.branch_id)
        staff = Staff.query.get(reservation.staff_id)
        
        # Calculate advance payment for reference and revenue tracking
        advance_payment = 0
        try:
            advance_payment = (reservation.advance_payment_percentage / 100) * reservation.total_price
        except:
            advance_payment = 0
            
        # İptal tipini belirle
        cancel_type = "REFUND" if with_refund else "NORMAL"
        cancel_type_tr = "TAM İADE" if with_refund else "NORMAL"
        
        # Rezervasyonu iptal olarak işaretle (silme)
        reservation.is_canceled = True
        reservation.cancel_type = cancel_type
        
        # İptal türüne göre gelir hesabı
        if not with_refund and advance_payment > 0:
            reservation.cancel_revenue = advance_payment
        else:
            reservation.cancel_revenue = 0
            
        # Send Telegram notification about reservation cancellation
        if branch and branch.telegram_enabled and branch.telegram_chat_id:
            try:
                # Import is at top of file now, so no need to import again here
                # Use the new function directly
                thread = Thread(
                    target=send_cancellation_notification,
                    args=(reservation, branch, staff, with_refund, "Web Kullanıcısı"),
                    daemon=True
                )
                thread.start()
                print(f"Started Telegram cancellation notification thread for reservation: {reservation.id}")
            except Exception as e:
                print(f"Failed to send Telegram cancellation notification: {str(e)}")
        
        # Log kaydı oluştur
        Log.add_log(
            log_type="RESERVATION",
            action="CANCEL",
            details=f"Rezervasyon iptal edildi ({cancel_type_tr}): {reservation.customer_name} ({reservation.reservation_date.strftime('%d.%m.%Y')} {reservation.reservation_time.strftime('%H:%M')})" +
                   (f" - İade: ₺{advance_payment:.2f}" if with_refund else ""),
            branch_id=reservation.branch_id
        )
        
        # Değişiklikleri kaydet
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})
        
@app.route('/api/init_data', methods=['POST'])
def init_data():
    """
    Initialize sample data - only runs if specifically requested with the force parameter
    and only works in development mode
    """
    try:
        # Güvenlik önlemi - bu endpoint'i sadece geliştirme modunda ve force parametresi ile çalıştır
        force_init = request.args.get('force') == 'true'
        is_dev_mode = os.environ.get('FLASK_ENV') == 'development'
        
        if not is_dev_mode and not force_init:
            return jsonify({'success': False, 'message': 'Bu endpoint sadece geliştirme modunda çalışır veya force=true parametresi gerektirir'})
            
        # Check if data already exists
        if Branch.query.count() > 0 and not force_init:
            return jsonify({'success': True, 'message': 'Data already initialized'})
            
        # Önceden force=true ile çağrıldığında, verileri temizle
        if force_init:
            try:
                # İlişkili verileri temizle
                Reservation.query.delete()
                Staff.query.delete()
                Branch.query.delete()
                db.session.commit()
                logger.info("Existing data wiped for re-initialization")
            except Exception as clear_error:
                db.session.rollback()
                logger.error(f"Error clearing existing data: {clear_error}")
                return jsonify({'success': False, 'error': f'Mevcut veri temizlenirken hata: {str(clear_error)}'})
        
        # Create branches
        branch1 = Branch(name="Ana Şube", address="Bağdat Caddesi No:123")
        branch2 = Branch(name="Merkez Şube", address="İstiklal Caddesi No:456")
        
        db.session.add_all([branch1, branch2])
        db.session.commit()
        
        # Create staff
        staff1 = Staff(name="Ahmet Yılmaz", phone="0555-123-4567", branch_id=branch1.id)
        staff2 = Staff(name="Ayşe Kaya", phone="0555-987-6543", branch_id=branch1.id)
        staff3 = Staff(name="Mehmet Demir", phone="0555-456-7890", branch_id=branch2.id)
        staff4 = Staff(name="Fatma Şahin", phone="0555-321-0987", branch_id=branch2.id)
        
        db.session.add_all([staff1, staff2, staff3, staff4])
        db.session.commit()
        
        # Log veri oluşturma
        Log.add_log(
            log_type="SYSTEM",
            action="INIT",
            details=f"Örnek veriler başarıyla oluşturuldu: 2 şube, 4 personel"
        )
        
        return jsonify({'success': True, 'message': 'Sample data initialized successfully'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error initializing data: {e}")
        return jsonify({'success': False, 'error': str(e)})

# Settings Routes

@app.route('/telegram_settings')
def telegram_settings():
    """Telegram settings page for branch notifications"""
    branches = Branch.query.all()
    
    # Store selected branch in session (for consistency across pages)
    branch_id = request.args.get('branch_id', session.get('selected_branch_id'))
    if branch_id:
        session['selected_branch_id'] = int(branch_id)
    
    # Check if Telegram bot is configured
    # First try to get from database
    from models import Setting
    
    telegram_token = Setting.get('telegram_bot_token')
    # If not in DB, try environment variable
    if not telegram_token:
        telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    
    bot_configured = bool(telegram_token)
    
    # Get partial token for display (show only first few chars)
    bot_token_partial = None
    if telegram_token and len(telegram_token) > 10:
        bot_token_partial = telegram_token[:6] + "..." + telegram_token[-4:]
    
    return render_template(
        'telegram_settings.html', 
        branches=branches,
        bot_configured=bot_configured,
        bot_token_partial=bot_token_partial
    )

@app.route('/api/update_telegram_token', methods=['POST'])
def update_telegram_token():
    """Update Telegram bot token"""
    try:
        token = request.form.get('token')
        
        if not token:
            return jsonify({'success': False, 'error': 'Token gereklidir'})
        
        # Update token in database
        from models import Setting
        Setting.set('telegram_bot_token', token, 'Telegram Bot Token')
        
        # Update environment variable
        os.environ['TELEGRAM_BOT_TOKEN'] = token
        
        # Update telegram_service module with new token
        import telegram_service
        
        # Get bot token using the get_bot_token function
        # to ensure we use the new function that checks both db and env
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/test_telegram', methods=['POST'])
def test_telegram():
    """Test Telegram bot connection for a branch"""
    try:
        # Log all request data for debugging
        print(f"Telegram test request data: {request.form}")
        
        branch_id = request.form.get('branch_id')
        test_message = request.form.get('test_message', 'Bu bir test mesajıdır!')
        
        print(f"Testing Telegram for branch_id: {branch_id}")
        
        if not branch_id:
            print("Error: Missing branch_id")
            return jsonify({'success': False, 'error': 'Şube ID gereklidir'}), 400
            
        branch = Branch.query.get(branch_id)
        if not branch:
            print(f"Error: Branch with ID {branch_id} not found")
            return jsonify({'success': False, 'error': 'Şube bulunamadı'}), 404
            
        print(f"Branch found: {branch.name}, Chat ID: {branch.telegram_chat_id}")
        
        if not branch.telegram_chat_id:
            print("Error: Missing Telegram Chat ID for this branch")
            return jsonify({'success': False, 'error': 'Bu şube için Telegram Chat ID tanımlanmamış'}), 400
            
        # Try to send a test message
        print(f"Attempting to send test message to chat ID: {branch.telegram_chat_id}")
        
        # Make sure we're using the latest token
        from telegram_service import get_bot_token
        token = get_bot_token()
        if not token:
            print("Error: No Telegram Bot Token set")
            return jsonify({'success': False, 'error': 'Telegram Bot Token ayarlanmamış'}), 400
        
        print(f"Using token starting with: {token[:6]}...")
        from telegram_service import send_message
        test_successful = send_message(branch.telegram_chat_id, test_message)
        
        if test_successful:
            print("Message sent successfully!")
            return jsonify({'success': True, 'message': 'Test mesajı başarıyla gönderildi'})
        else:
            print("Failed to send message")
            return jsonify({'success': False, 'error': 'Mesaj gönderilemedi, lütfen ayarları kontrol edin'})
            
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Exception in test_telegram: {str(e)}")
        print(f"Detailed error: {error_details}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/staff_performance')
def staff_performance():
    """Show staff performance metrics"""
    branches = Branch.query.all()
    
    # Get selected branch_id from query param or session
    branch_id = request.args.get('branch_id', session.get('selected_branch_id'))
    
    if not branch_id and branches:
        branch_id = branches[0].id
        session['selected_branch_id'] = int(branch_id)
    elif branch_id:
        # Şubeyi seçip session'a kaydet
        session['selected_branch_id'] = int(branch_id)
        
    # Set default period to current month
    selected_period = request.args.get('period', 'month')
    
    # Get staff data
    staff_performance = []
    
    try:
        if branch_id:
            branch_id = int(branch_id)
            
            # Define date range based on selected period - with Turkey timezone (UTC+3)
            utc_now = datetime.now()
            turkey_time_offset = timedelta(hours=3)
            now = utc_now + turkey_time_offset  # Türkiye saati
            today = now.date()
            
            if selected_period == 'day':
                start_date = today
                end_date = today
            elif selected_period == 'week':
                start_date = today - timedelta(days=today.weekday())
                end_date = start_date + timedelta(days=6)
            elif selected_period == 'month':
                start_date = date(today.year, today.month, 1)
                last_day = calendar.monthrange(today.year, today.month)[1]
                end_date = date(today.year, today.month, last_day)
            else:  # all-time
                start_date = date(1900, 1, 1)
                end_date = date(2100, 12, 31)
            
            # Şube kontrolü
            branch = Branch.query.get(branch_id)
            if not branch:
                print(f"Hata: {branch_id} ID'li şube bulunamadı")
                if branches:
                    branch_id = branches[0].id
                    session['selected_branch_id'] = branch_id
                
            # Get staff members for the branch
            staff_members = Staff.query.filter_by(branch_id=branch_id).all()
            
            for staff in staff_members:
                # Aktif rezervasyonları al
                active_reservations = Reservation.query.filter(
                    Reservation.staff_id == staff.id,
                    Reservation.reservation_date >= start_date,
                    Reservation.reservation_date <= end_date,
                    Reservation.is_canceled == False
                ).all()
                
                # İptal edilen rezervasyonları al (gelir hesabı için)
                canceled_reservations = Reservation.query.filter(
                    Reservation.staff_id == staff.id,
                    Reservation.reservation_date >= start_date,
                    Reservation.reservation_date <= end_date,
                    Reservation.is_canceled == True
                ).all()
                
                # Misafir sayısı sadece aktif rezervasyonlar için
                total_guests = sum(r.num_people for r in active_reservations)
                
                # Aktif rezervasyonların geliri
                active_revenue = sum(r.total_price for r in active_reservations)
                
                # İptal edilmiş rezervasyonlardan kalan gelir (iade olmayan iptallerdeki ön ödemeler)
                cancel_revenue = sum(r.cancel_revenue or 0 for r in canceled_reservations)
                
                # Toplam gelir
                total_revenue = active_revenue + cancel_revenue
                
                # Toplam rezervasyon sayısı (iptal edilenler dahil)
                active_reservation_count = len(active_reservations)
                canceled_reservation_count = len(canceled_reservations)
                reservation_count = active_reservation_count + canceled_reservation_count
                
                # Ortalama misafir sayısı (sadece aktif rezervasyonlar için)
                avg_guests = total_guests / active_reservation_count if active_reservation_count > 0 else 0
                
                # Ortalama gelir (tüm gelirin aktif rezervasyonlara bölümü)
                avg_revenue = total_revenue / active_reservation_count if active_reservation_count > 0 else 0
                
                staff_performance.append({
                    'id': staff.id,
                    'name': staff.name,
                    'phone': staff.phone,
                    'reservation_count': reservation_count,
                    'active_reservations': active_reservation_count,
                    'canceled_reservations': canceled_reservation_count,
                    'total_guests': total_guests,
                    'total_revenue': total_revenue,
                    'active_revenue': active_revenue,
                    'canceled_revenue': cancel_revenue,
                    'avg_guests_per_reservation': avg_guests,
                    'avg_revenue_per_reservation': avg_revenue
                })
    except Exception as e:
        import traceback
        print(f"Personel performansı hatası: {str(e)}")
        print(traceback.format_exc())
    
    return render_template(
        'staff_performance.html',
        branches=branches,
        selected_branch_id=branch_id,
        selected_period=selected_period,
        staff_performance=staff_performance
    )

@app.route('/time_settings')
@login_required
@role_required("can_view_settings")
def time_settings():
    """Working hours settings page"""
    
    # Store selected branch in session (for consistency across pages)
    branch_id = request.args.get('branch_id', session.get('selected_branch_id'))
    if branch_id:
        session['selected_branch_id'] = int(branch_id)
    
    # Get current working hours from session
    default_hours = [f"{i:02d}:00" for i in range(9, 23)]  # 9 AM - 10 PM
    hours = session.get('working_hours', default_hours)
    
    return render_template('time_settings.html', hours=hours)
    
@app.route('/api/factory_reset', methods=['POST'])
@login_required
@role_required("can_view_settings")
def factory_reset():
    """Factory reset - delete all data and reset to initial state except superadmin Jaemor"""
    try:
        # Check if user is a superadmin
        if not current_user.is_superadmin:
            return jsonify({'success': False, 'error': 'Bu işlem için süper admin yetkisi gereklidir.'}), 403
            
        # Get the superadmin user with username 'Jaemor'
        jaemor_user = User.query.filter_by(username='Jaemor').first()
        
        # If jaemor user doesn't exist, create it with default settings
        if not jaemor_user:
            # Find existing superadmin role or create one
            superadmin_role = Role.query.filter_by(is_superadmin=True).first()
            if not superadmin_role:
                superadmin_role = Role(
                    name="Süper Admin",
                    description="Tam yetkili sistem yöneticisi",
                    color="#ff5555",
                    is_superadmin=True
                )
                db.session.add(superadmin_role)
                db.session.flush()
            
            # Create jaemor user with superadmin role
            jaemor_user = User(
                username='Jaemor',
                name='Süper Admin',
                is_active=True
            )
            jaemor_user.set_password('1234')
            jaemor_user.roles.append(superadmin_role)
            db.session.add(jaemor_user)
            db.session.flush()
        
        # Save the Jaemor user's role IDs
        jaemor_role_ids = [role.id for role in jaemor_user.roles]
        
        # Bu sefer tamamen farklı bir yaklaşım kullanalım
        # Önce tüm tablolardaki FK constraint'leri devre dışı bırakalım
        # Sonra temizlik işlemi yapalım ve committen sonra tekrar aktif edelim
        try:
            # Direct SQL komutları postgres için
            # Log tablosunu FK constraint'ten temizle
            db.session.execute(text("""
                -- Log tablosundaki referansları temizle
                UPDATE logs SET branch_id = NULL, user_id = NULL;
                
                -- Reservation tablosundaki referansları temizle
                UPDATE reservations SET branch_id = NULL, staff_id = NULL, customer_id = NULL;
                
                -- User tablosundaki referansları temizle
                UPDATE users SET branch_id = NULL, staff_id = NULL;
            """))
            
            # Şimdi tüm verileri temizle
            db.session.execute(text("""
                DELETE FROM reservations;
                DELETE FROM customers;
                DELETE FROM staff;
                DELETE FROM logs;
                DELETE FROM branches;
            """))
            
            # Kullanıcıları ve rolleri temizle (Jaemor hariç)
            db.session.execute(text(f"""
                DELETE FROM users WHERE username != 'Jaemor';
                DELETE FROM roles WHERE id NOT IN ({",".join([str(r) for r in jaemor_role_ids])});
                DELETE FROM settings;
            """))
            
            # Commit the changes
            db.session.commit()
            
            # Başlangıç verilerini oluştur
            # 1. Yaygın şubeler
            branch1 = Branch(name="Ana Şube", address="Bağdat Caddesi No:123")
            branch2 = Branch(name="Merkez Şube", address="İstiklal Caddesi No:456")
            
            db.session.add_all([branch1, branch2])
            db.session.commit()
            
            # 2. Personeller
            staff1 = Staff(name="Ahmet Yılmaz", phone="0555-123-4567", branch_id=branch1.id)
            staff2 = Staff(name="Ayşe Kaya", phone="0555-987-6543", branch_id=branch1.id)
            staff3 = Staff(name="Mehmet Demir", phone="0555-456-7890", branch_id=branch2.id)
            staff4 = Staff(name="Fatma Şahin", phone="0555-321-0987", branch_id=branch2.id)
            
            db.session.add_all([staff1, staff2, staff3, staff4])
            db.session.commit()
            
            # 3. Default settings
            Setting.set('working_hours', '10:00,10:30,11:00,11:30,12:00,12:30,13:00,13:30,14:00,14:30,15:00,15:30,16:00,16:30,17:00,17:30,18:00,18:30,19:00,19:30,20:00,20:30,21:00,21:30', 'Çalışma saatleri (virgülle ayrılmış)')
            
            # 4. Log kaydı - başarılı sıfırlama
            Log.add_log(
                log_type="SYSTEM",
                action="RESET",
                details=f"Sistem fabrika ayarlarına sıfırlandı (Kullanıcı: {current_user.username})",
                user_id=current_user.id
            )
            
            return jsonify({'success': True, 'message': 'Sistem başarıyla fabrika ayarlarına sıfırlandı'})
        except Exception as e:
            db.session.rollback()
            import traceback
            print(traceback.format_exc())
            return jsonify({'success': False, 'error': str(e)}), 500
        
    except Exception as e:
        db.session.rollback()
        import traceback
        print(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/update_working_hours', methods=['POST'])
def update_working_hours():
    """Update working hours settings"""
    try:
        # Önce hangi mod kullanıldığını kontrol edelim: automatic veya manual
        # Not: ContentType application/json kullanıldığında, request.form yerine request.json kullanılır
        if request.is_json:
            data = request.json
            mode = data.get('mode', 'manual')
            
            # Manuel mod: Özel saatler listesi kullanılıyor
            if mode == 'manual':
                custom_times = data.get('custom_times', [])
                
                # Listeyi doğrulayalım
                if not custom_times:
                    return jsonify({'success': False, 'error': 'En az bir saat eklenmelidir'})
                
                # Saatleri sıralayalım
                hours = sorted(custom_times, key=lambda x: [int(i) for i in x.split(':')])
                
                # Saatleri session'a kaydedelim
                session['working_hours'] = hours
                
                return jsonify({'success': True, 'hours': hours})
        
        # Form verilerini kontrol edelim (otomatik mod için veya JSON kullanılmadığında)
        mode = request.form.get('mode', 'automatic')
        
        if mode == 'automatic':
            start_hour = int(request.form.get('start_hour', 9))
            start_minute = int(request.form.get('start_minute', 0))
            end_hour = int(request.form.get('end_hour', 22))
            end_minute = int(request.form.get('end_minute', 0))
            interval = int(request.form.get('interval', 60))  # dakika
            
            # Verileri doğrulayalım
            if start_hour < 0 or start_hour > 23:
                return jsonify({'success': False, 'error': 'Başlangıç saati 0-23 arasında olmalıdır'})
                
            if end_hour < 0 or end_hour > 23:
                return jsonify({'success': False, 'error': 'Bitiş saati 0-23 arasında olmalıdır'})
            
            if start_minute < 0 or start_minute > 59 or end_minute < 0 or end_minute > 59:
                return jsonify({'success': False, 'error': 'Dakika değeri 0-59 arasında olmalıdır'})
                
            # Toplam dakika cinsinden kontrol edelim
            start_total_minutes = start_hour * 60 + start_minute
            end_total_minutes = end_hour * 60 + end_minute
            
            if start_total_minutes >= end_total_minutes:
                return jsonify({'success': False, 'error': 'Başlangıç saati bitiş saatinden küçük olmalıdır'})
                
            if interval <= 0 or interval > 120:
                return jsonify({'success': False, 'error': 'Aralık 1-120 dakika arasında olmalıdır'})
                
            # Saat listesini oluşturalım
            hours = []
            current_time = datetime.combine(date.today(), time(start_hour, start_minute))
            end_time = datetime.combine(date.today(), time(end_hour, end_minute))
            
            while current_time <= end_time:
                hours.append(current_time.strftime('%H:%M'))
                current_time += timedelta(minutes=interval)
                
            # Saatleri session'a kaydedelim
            old_hours = session.get('working_hours', [])
            session['working_hours'] = hours
            
            # Log the change
            Log.add_log(
                log_type="TIME",
                action="UPDATE",
                details=f"Working hours updated: {len(hours)} time slots"
            )
            
            return jsonify({'success': True, 'hours': hours})
        
        return jsonify({'success': False, 'error': 'Geçersiz mod değeri'})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/logs')
def logs():
    """System logs page"""
    branches = Branch.query.all()
    
    # Store selected branch in session (for consistency across pages, even if not directly used here)
    selected_branch = request.args.get('branch_id', session.get('selected_branch_id'))
    if selected_branch and selected_branch != 'all':
        session['selected_branch_id'] = int(selected_branch)
    
    # Get log type filter from query params
    log_type = request.args.get('log_type', 'all')
    branch_id = request.args.get('branch_id', 'all')
    
    # Base query
    query = Log.query
    
    # Apply filters
    if log_type != 'all':
        query = query.filter(Log.log_type == log_type)
        
    if branch_id != 'all' and branch_id:
        query = query.filter(Log.branch_id == branch_id)
    
    # Sort by most recent first and limit to 15 entries
    logs_list = query.order_by(Log.created_at.desc()).limit(15).all()
    
    log_types = ['RESERVATION', 'TIME', 'CUSTOMER', 'SYSTEM']
    
    return render_template(
        'logs.html',
        logs=logs_list,
        log_types=log_types,
        selected_log_type=log_type,
        selected_branch_id=branch_id,
        branches=branches
    )

@app.route('/customers')
@login_required
def customers():
    """Customers management page"""
    branches = Branch.query.all()
    
    # Store selected branch in session (for consistency across pages)
    branch_id = request.args.get('branch_id', session.get('selected_branch_id'))
    if branch_id:
        session['selected_branch_id'] = int(branch_id)
    
    # Search query
    search_query = request.args.get('search', '')
    
    # Base query
    query = Customer.query
    
    # Apply search filter if present
    if search_query:
        search_term = f"%{search_query}%"
        query = query.filter(
            or_(
                Customer.name.ilike(search_term),
                Customer.phone.ilike(search_term),
                Customer.email.ilike(search_term)
            )
        )
    
    # Sort by most recent first
    customers_list = query.order_by(Customer.updated_at.desc()).limit(50).all()
    
    return render_template(
        'customers.html',
        customers=customers_list,
        search_query=search_query,
        branches=branches
    )

# Kullanıcı ve Rol Yönetimi Route'ları
@app.route('/users')
@login_required
@role_required('can_view_management')
def users():
    """Kullanıcı yönetimi sayfası"""
    users = User.query.all()
    return render_template('users.html', users=users)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
@role_required('can_view_management')
def add_user():
    """Yeni kullanıcı ekleme sayfası"""
    form = UserForm()
    
    # Rol seçeneklerini doldur
    form.roles.choices = [(r.id, r.name) for r in Role.query.all()]
    
    if form.validate_on_submit():
        # Rastgele şifre oluştur (eğer şifre verilmediyse)
        random_password = None
        if not form.password.data:
            import random, string
            random_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            
        user = User(
            username=form.username.data,
            name=form.name.data,
            email=form.email.data,
            is_active=form.is_active.data
        )
        
        # Şube ID'si formda artık olmadığı için bu kısmı kaldırdık
        # Kullanıcılar artık şubeye bağlı değil
        
        # Şifre ayarla
        if form.password.data:
            user.set_password(form.password.data)
        elif random_password:
            user.set_password(random_password)
            
        db.session.add(user)
        
        # Rol ata
        role = Role.query.get(form.roles.data)
        if role:
            user.roles.append(role)
        
        db.session.commit()
        
        # Log ekle - branch_id null olabileceği için kontrol ediyoruz
        branch_id = current_user.branch_id if hasattr(current_user, 'branch_id') else None
        Log.add_log(
            log_type="SYSTEM",
            action="CREATE",
            details=f"User {user.username} created by {current_user.username}",
            user_id=current_user.id,
            branch_id=branch_id
        )
        
        if random_password:
            flash(f'Kullanıcı başarıyla oluşturuldu. Otomatik oluşturulan şifre: {random_password}', 'success')
        else:
            flash('Kullanıcı başarıyla oluşturuldu.', 'success')
        return redirect(url_for('users'))
    
    return render_template('user_form.html', form=form, user=None)

@app.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
@role_required('can_view_management')
def edit_user(user_id):
    """Kullanıcı düzenleme sayfası"""
    user = User.query.get_or_404(user_id)
    form = UserForm(user_id=user_id)
    
    # Rol seçeneklerini doldur
    form.roles.choices = [(r.id, r.name) for r in Role.query.all()]
    
    if request.method == 'GET':
        form.username.data = user.username
        form.name.data = user.name
        form.email.data = user.email
        form.is_active.data = user.is_active
        
        # Mevcut rolü seç (eğer varsa)
        if user.roles:
            form.roles.data = user.roles[0].id
    
    if form.validate_on_submit():
        user.username = form.username.data
        user.name = form.name.data
        user.email = form.email.data
        user.is_active = form.is_active.data
        
        # Şube ID artık formda olmadığı için bu kısmı kaldırdık
        
        # Şifre güncelle (sadece girilmişse)
        if form.password.data:
            user.set_password(form.password.data)
        
        # Rolleri güncelle
        user.roles = []
        role = Role.query.get(form.roles.data)
        if role:
            user.roles.append(role)
        
        db.session.commit()
        
        # Log ekle - branch_id null olabileceği için kontrol ediyoruz
        branch_id = current_user.branch_id if hasattr(current_user, 'branch_id') else None
        Log.add_log(
            log_type="SYSTEM",
            action="UPDATE",
            details=f"User {user.username} updated by {current_user.username}",
            user_id=current_user.id,
            branch_id=branch_id
        )
        
        flash('Kullanıcı başarıyla güncellendi.', 'success')
        return redirect(url_for('users'))
    
    return render_template('user_form.html', form=form, user=user)

@app.route('/users/toggle_status/<int:user_id>')
@login_required
@role_required('can_view_management')
def toggle_user_status(user_id):
    """Kullanıcı aktif/pasif durumunu değiştirme"""
    user = User.query.get_or_404(user_id)
    
    # Süper adminleri hiç bir şekilde pasifleştirmeye çalışmayalım
    if user.is_superadmin:
        # Süper admin durumunu değiştirmek için süper admin olmalı
        if not current_user.is_superadmin():
            flash('Süper admin hesabını değiştirmek için süper admin yetkisine sahip olmalısınız.', 'danger')
            return redirect(url_for('users'))
    
    # Kullanıcı kendini pasifleştirmesin
    if user.id == current_user.id:
        flash('Kendi hesabınızı pasifleştiremezsiniz.', 'danger')
        return redirect(url_for('users'))
    
    # Aktif rolde kullanıcı varsa o rolü pasifleştiremeyiz
    if user.roles and user.is_active:
        role = user.roles[0]
        active_users_with_role = db.session.query(User).filter(
            User.roles.any(Role.id == role.id),
            User.is_active == True,
            User.id != user.id
        ).count()
        
        if active_users_with_role == 0:
            flash(f'Bu rolde ({role.name}) en az bir aktif kullanıcı olmalıdır. Önce başka bir kullanıcıyı bu role atayın veya aktifleştirin.', 'danger')
            return redirect(url_for('users'))
    
    # Durumu tersine çevir
    user.is_active = not user.is_active
    db.session.commit()
    
    status_text = "aktifleştirildi" if user.is_active else "pasifleştirildi"
    
    # Log ekle - branch_id null olabileceği için kontrol ediyoruz
    branch_id = current_user.branch_id if hasattr(current_user, 'branch_id') else None
    Log.add_log(
        log_type="SYSTEM",
        action="UPDATE",
        details=f"Kullanıcı {user.username} {status_text} (by {current_user.username})",
        user_id=current_user.id,
        branch_id=branch_id
    )
    
    flash(f'Kullanıcı {status_text}.', 'success')
    return redirect(url_for('users'))

@app.route('/users/delete/<int:user_id>')
@login_required
@role_required('can_view_management')
def delete_user(user_id):
    """Kullanıcı silme işlemi"""
    user = User.query.get_or_404(user_id)
    
    # Kendini silemez
    if user.id == current_user.id:
        flash('Kendi hesabınızı silemezsiniz.', 'danger')
        return redirect(url_for('users'))
    
    # Süper admin kullanıcıları sadece diğer süper adminler silebilir
    if user.is_superadmin:
        if not current_user.is_superadmin():
            flash('Süper admin hesabını silmek için süper admin yetkisine sahip olmalısınız.', 'danger')
            return redirect(url_for('users'))
    
    # Aktif rolde kullanıcı varsa o rolü silemeyiz
    if user.roles and user.is_active:
        role = user.roles[0]
        active_users_with_role = db.session.query(User).filter(
            User.roles.any(Role.id == role.id),
            User.is_active == True,
            User.id != user.id
        ).count()
        
        if active_users_with_role == 0:
            flash(f'Bu rolde ({role.name}) en az bir aktif kullanıcı olmalıdır. Önce başka bir kullanıcıyı bu role atayın veya aktifleştirin.', 'danger')
            return redirect(url_for('users'))
    
    # Kullanıcıyı sil
    username = user.username
    db.session.delete(user)
    db.session.commit()
    
    # Log ekle - branch_id null olabileceği için kontrol ediyoruz
    branch_id = current_user.branch_id if hasattr(current_user, 'branch_id') else None
    Log.add_log(
        log_type="SYSTEM",
        action="DELETE",
        details=f"User {username} deleted by {current_user.username}",
        user_id=current_user.id,
        branch_id=branch_id
    )
    
    flash('Kullanıcı başarıyla silindi.', 'success')
    return redirect(url_for('users'))

@app.route('/roles')
@login_required
@role_required('can_view_management')
def roles():
    """Rol yönetimi sayfası"""
    roles = Role.query.all()
    return render_template('roles.html', roles=roles)

@app.route('/roles/add', methods=['GET', 'POST'])
@login_required
@role_required('can_view_management')
def add_role():
    """Yeni rol ekleme sayfası"""
    form = RoleForm()
    
    if form.validate_on_submit():
        role = Role(
            name=form.name.data,
            description=form.description.data,
            color=form.color.data,
            is_superadmin=form.is_superadmin.data,
            can_create_reservation=form.can_create_reservation.data,
            can_view_reports=form.can_view_reports.data,
            can_view_logs=form.can_view_logs.data,
            can_view_settings=form.can_view_settings.data,
            can_view_management=form.can_view_management.data
        )
        
        db.session.add(role)
        db.session.commit()
        
        # Log ekle - branch_id null olabileceği için kontrol ediyoruz
        branch_id = current_user.branch_id if hasattr(current_user, 'branch_id') else None
        Log.add_log(
            log_type="SYSTEM",
            action="CREATE",
            details=f"Role {role.name} created by {current_user.username}",
            user_id=current_user.id,
            branch_id=branch_id
        )
        
        flash('Rol başarıyla oluşturuldu.', 'success')
        return redirect(url_for('roles'))
    
    return render_template('role_form.html', form=form, role=None)

@app.route('/roles/edit/<int:role_id>', methods=['GET', 'POST'])
@login_required
@role_required('can_view_management')
def edit_role(role_id):
    """Rol düzenleme sayfası"""
    role = Role.query.get_or_404(role_id)
    
    # Süper admin rollerini yalnızca süper admin düzenleyebilir
    if role.is_superadmin and not current_user.is_superadmin():
        flash('Süper admin rolünü düzenlemek için süper admin yetkisine sahip olmalısınız.', 'danger')
        return redirect(url_for('roles'))
        
    form = RoleForm(role_id=role_id)
    
    if request.method == 'GET':
        form.name.data = role.name
        form.description.data = role.description
        form.color.data = role.color
        form.is_superadmin.data = role.is_superadmin
        form.can_create_reservation.data = role.can_create_reservation
        form.can_view_reports.data = role.can_view_reports
        form.can_view_logs.data = role.can_view_logs
        form.can_view_settings.data = role.can_view_settings
        form.can_view_management.data = role.can_view_management
    
    if form.validate_on_submit():
        role.name = form.name.data
        role.description = form.description.data
        role.color = form.color.data
        role.is_superadmin = form.is_superadmin.data
        
        # İzinleri güncelle (süper admin değilse)
        if not role.is_superadmin:
            role.can_create_reservation = form.can_create_reservation.data
            role.can_view_reports = form.can_view_reports.data
            role.can_view_logs = form.can_view_logs.data
            role.can_view_settings = form.can_view_settings.data
            role.can_view_management = form.can_view_management.data
        
        db.session.commit()
        
        # Log ekle
        Log.add_log(
            log_type="SYSTEM",
            action="UPDATE",
            details=f"Role {role.name} updated by {current_user.username}",
            user_id=current_user.id,
            branch_id=current_user.branch_id
        )
        
        flash('Rol başarıyla güncellendi.', 'success')
        return redirect(url_for('roles'))
    
    return render_template('role_form.html', form=form, role=role)

@app.route('/roles/delete/<int:role_id>')
@login_required
@role_required('can_view_management')
def delete_role(role_id):
    """Rol silme işlemi"""
    role = Role.query.get_or_404(role_id)
    
    # Süper admin rolü silinemez
    if role.is_superadmin:
        flash('Süper admin rolü silinemez.', 'danger')
        return redirect(url_for('roles'))
    
    # Role sahip kullanıcıların rollerini kaldır
    role_name = role.name
    for user in role.users:
        user.roles.remove(role)
    
    # Rolü sil
    db.session.delete(role)
    db.session.commit()
    
    # Log ekle
    Log.add_log(
        log_type="SYSTEM",
        action="DELETE",
        details=f"Role {role_name} deleted by {current_user.username}",
        user_id=current_user.id,
        branch_id=current_user.branch_id
    )
    
    flash('Rol başarıyla silindi.', 'success')
    return redirect(url_for('roles'))

def customers():
    """Customers management page"""
    branches = Branch.query.all()
    
    # Search query
    search_query = request.args.get('search', '')
    
    # Base query
    query = Customer.query
    
    # Apply search filter if present
    if search_query:
        search_term = f"%{search_query}%"
        query = query.filter(
            or_(
                Customer.name.ilike(search_term),
                Customer.phone.ilike(search_term),
                Customer.email.ilike(search_term)
            )
        )
    
    # Sort by most recent first
    customers_list = query.order_by(Customer.updated_at.desc()).limit(50).all()
    
    return render_template(
        'customers.html',
        customers=customers_list,
        search_query=search_query,
        branches=branches
    )

@app.route('/customer/<int:customer_id>')
def customer_detail(customer_id):
    """Customer detail page"""
    branches = Branch.query.all()
    
    # Get customer
    customer = Customer.query.get_or_404(customer_id)
    
    # Silinmişse engelleyelim
    if customer.name == "Silinmiş Müşteri":
        flash('Bu müşteri kaydı silinmiştir.', 'warning')
        return redirect(url_for('customers'))
    
    # Get customer reservations
    reservations = Reservation.query.filter_by(customer_id=customer_id).order_by(Reservation.reservation_date.desc()).all()
    
    return render_template(
        'customer_detail.html',
        customer=customer,
        reservations=reservations,
        branches=branches
    )

@app.route('/api/update_customer', methods=['POST'])
def update_customer():
    """Update customer details"""
    try:
        customer_id = request.form.get('customerId')
        customer_name = request.form.get('customerName')
        customer_phone = request.form.get('customerPhone')
        customer_email = request.form.get('customerEmail')
        customer_notes = request.form.get('customerNotes')
        
        if not customer_id:
            return jsonify({'success': False, 'error': 'Müşteri ID gereklidir'})
        
        # Find customer
        customer = Customer.query.get(customer_id)
        if not customer:
            return jsonify({'success': False, 'error': 'Müşteri bulunamadı'})
        
        # Update customer
        if customer_name:
            customer.name = customer_name
        if customer_phone:
            customer.phone = customer_phone
        if customer_email:
            customer.email = customer_email
        if customer_notes:
            customer.notes = customer_notes
            
        customer.updated_at = datetime.now()
        
        db.session.commit()
        
        # Log the update
        Log.add_log(
            log_type="CUSTOMER",
            action="UPDATE",
            details=f"Müşteri güncellendi: {customer.name} ({customer.phone})"
        )
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/delete_customer', methods=['POST'])
def delete_customer():
    """Delete a customer and optionally their reservations"""
    try:
        customer_id = request.form.get('customerId')
        delete_reservations = request.form.get('deleteReservations') == 'true'
        
        if not customer_id:
            return jsonify({'success': False, 'error': 'Müşteri ID gereklidir'})
        
        # Find customer
        customer = Customer.query.get(customer_id)
        if not customer:
            return jsonify({'success': False, 'error': 'Müşteri bulunamadı'})
        
        # Store customer info for logging
        customer_name = customer.name
        customer_phone = customer.phone
        
        # Delete customer's reservations if requested
        if delete_reservations:
            # Get all reservations
            reservations = Reservation.query.filter_by(customer_id=customer_id).all()
            
            for reservation in reservations:
                # Log reservation deletion
                Log.add_log(
                    log_type="RESERVATION",
                    action="DELETE",
                    details=f"Müşteri silindiği için rezervasyon silindi: {reservation.customer_name} ({reservation.reservation_date.strftime('%d.%m.%Y')} {reservation.reservation_time.strftime('%H:%M')})",
                    branch_id=reservation.branch_id
                )
                
                db.session.delete(reservation)
        else:
            # Just unlink customer from reservations
            for reservation in Reservation.query.filter_by(customer_id=customer_id).all():
                reservation.customer_id = None
        
        # Delete the customer
        db.session.delete(customer)
        db.session.commit()
        
        # Log the deletion
        Log.add_log(
            log_type="CUSTOMER",
            action="DELETE",
            details=f"Müşteri silindi: {customer_name} ({customer_phone})"
        )
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/clear_customer_data', methods=['POST'])
def clear_customer_data():
    """Clear customer's personal data while keeping the reservation history"""
    try:
        customer_id = request.form.get('customerId')
        
        if not customer_id:
            return jsonify({'success': False, 'error': 'Müşteri ID gereklidir'})
        
        # Find customer
        customer = Customer.query.get(customer_id)
        if not customer:
            return jsonify({'success': False, 'error': 'Müşteri bulunamadı'})
        
        # Store original name and phone for logging
        original_name = customer.name
        original_phone = customer.phone
        
        # Anonymize customer data
        customer.name = "Silinmiş Müşteri"
        customer.phone = f"xxxx-{original_phone[-4:]}" if original_phone and len(original_phone) >= 4 else "xxxxxxxxxx"
        customer.email = None
        customer.notes = "Bilgiler müşteri isteği ile silinmiştir."
        customer.updated_at = datetime.now()
        
        # Also anonymize all associated reservations
        for reservation in Reservation.query.filter_by(customer_id=customer.id).all():
            reservation.customer_name = "Silinmiş Müşteri"
            reservation.customer_phone = f"xxxx-{original_phone[-4:]}" if original_phone and len(original_phone) >= 4 else "xxxxxxxxxx"
        
        db.session.commit()
        
        # Log the data clearing
        Log.add_log(
            log_type="CUSTOMER",
            action="CLEAR",
            details=f"Müşteri bilgileri silindi: {original_name} ({original_phone})"
        )
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})
