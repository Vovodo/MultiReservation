from app import db
from datetime import datetime
from sqlalchemy import ForeignKey, Table, Column
from sqlalchemy.orm import relationship
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

class Setting(db.Model):
    __tablename__ = 'settings'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.String(500))
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @classmethod
    def get(cls, key, default=None):
        """Get a setting value by key"""
        setting = cls.query.filter_by(key=key).first()
        if setting:
            return setting.value
        return default
    
    @classmethod
    def set(cls, key, value, description=None):
        """Set a setting value"""
        setting = cls.query.filter_by(key=key).first()
        if setting:
            setting.value = value
            setting.updated_at = datetime.utcnow()
            if description:
                setting.description = description
        else:
            setting = cls(key=key, value=value, description=description)
            db.session.add(setting)
        db.session.commit()
        return setting

class Branch(db.Model):
    __tablename__ = 'branches'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200))
    telegram_chat_id = db.Column(db.String(100), nullable=True)
    telegram_enabled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    staff = relationship("Staff", back_populates="branch")
    reservations = relationship("Reservation", back_populates="branch")
    
    def __repr__(self):
        return f'<Branch {self.name}>'

class Staff(db.Model):
    __tablename__ = 'staff'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    branch_id = db.Column(db.Integer, ForeignKey('branches.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    branch = relationship("Branch", back_populates="staff")
    reservations = relationship("Reservation", back_populates="staff")
    
    def __repr__(self):
        return f'<Staff {self.name}>'

class Customer(db.Model):
    __tablename__ = 'customers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False, unique=True)
    email = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    reservations = relationship("Reservation", back_populates="customer")
    
    def __repr__(self):
        return f'<Customer {self.name}>'
    
    @property
    def total_visits(self):
        """Get total number of visits"""
        # Silinmiş müşterileri analiz ekranında gösterme
        if self.name == "Silinmiş Müşteri":
            return 0
        return len(self.reservations)
    
    @property
    def total_spending(self):
        """Calculate total spending of customer"""
        # Silinmiş müşterileri analiz ekranında gösterme
        if self.name == "Silinmiş Müşteri":
            return 0
        return sum([r.total_price for r in self.reservations if r.payment_status == 'PAID'])
    
    @property
    def preferred_payment_method(self):
        """Determine most common payment method"""
        # Silinmiş müşterileri analiz ekranında gösterme
        if self.name == "Silinmiş Müşteri":
            return None
            
        payment_types = {}
        for r in self.reservations:
            payment_types[r.payment_type] = payment_types.get(r.payment_type, 0) + 1
        
        if not payment_types:
            return None
            
        return max(payment_types.items(), key=lambda x: x[1])[0]
    
    @property
    def average_group_size(self):
        """Calculate average group size"""
        # Silinmiş müşterileri analiz ekranında gösterme
        if self.name == "Silinmiş Müşteri":
            return 0
            
        if not self.reservations:
            return 0
        return sum([r.num_people for r in self.reservations]) / len(self.reservations)
    
    @property
    def last_visit_date(self):
        """Get date of last visit"""
        # Silinmiş müşterileri analiz ekranında gösterme
        if self.name == "Silinmiş Müşteri":
            return None
            
        if not self.reservations:
            return None
        latest = max(self.reservations, key=lambda r: r.reservation_date)
        return latest.reservation_date

# Kullanıcı-Rol ilişkisi için ara tablo
user_roles = db.Table('user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id'), primary_key=True)
)

class Role(db.Model):
    __tablename__ = 'roles'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))
    color = db.Column(db.String(7), default="#808080")  # HEX renk kodu
    is_superadmin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # İzinler
    can_create_reservation = db.Column(db.Boolean, default=False)
    can_view_reports = db.Column(db.Boolean, default=False)
    can_view_logs = db.Column(db.Boolean, default=False)
    can_view_settings = db.Column(db.Boolean, default=False)
    can_view_management = db.Column(db.Boolean, default=False)
    
    # Superadmin izinleri otomatik olarak true
    def __init__(self, **kwargs):
        super(Role, self).__init__(**kwargs)
        if self.is_superadmin:
            self.can_create_reservation = True
            self.can_view_reports = True
            self.can_view_logs = True
            self.can_view_settings = True
            self.can_view_management = True
    
    def __repr__(self):
        return f'<Role {self.name}>'

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(512))  # Modern hash algoritmaları için genişletildi
    name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'))
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=True)  # Personel hesabıysa
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    
    # İlişkiler
    branch = relationship("Branch")
    staff = relationship("Staff")
    roles = relationship("Role", secondary=user_roles, backref=db.backref("users", lazy="dynamic"))
    logs = relationship("Log", backref="user")
    
    def __repr__(self):
        return f'<User {self.username}>'
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    @property
    def is_superadmin(self):
        for role in self.roles:
            if role.is_superadmin:
                return True
        return False
    
    def has_permission(self, permission_name):
        if self.is_superadmin:
            return True
            
        for role in self.roles:
            if getattr(role, permission_name, False):
                return True
        return False

class Log(db.Model):
    __tablename__ = 'logs'
    
    id = db.Column(db.Integer, primary_key=True)
    log_type = db.Column(db.String(20), nullable=False)  # RESERVATION, TIME, CUSTOMER, SYSTEM
    action = db.Column(db.String(20), nullable=False)    # CREATE, UPDATE, DELETE
    details = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, ForeignKey('users.id'), nullable=True)
    branch_id = db.Column(db.Integer, ForeignKey('branches.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    branch = relationship("Branch")
    
    def __repr__(self):
        return f'<Log {self.log_type} {self.action} at {self.created_at}>'
    
    @classmethod
    def add_log(cls, log_type, action, details, branch_id=None, user_id=None):
        """Add a new log entry"""
        log = cls(
            log_type=log_type,
            action=action,
            details=details,
            branch_id=branch_id,
            user_id=user_id
        )
        db.session.add(log)
        db.session.commit()
        return log

class Reservation(db.Model):
    __tablename__ = 'reservations'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, ForeignKey('customers.id'), nullable=True)
    customer_name = db.Column(db.String(100), nullable=False)
    customer_phone = db.Column(db.String(20), nullable=False)
    num_people = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    advance_payment_percentage = db.Column(db.Float, default=0)
    payment_type = db.Column(db.String(10), nullable=False)  # Cash, POS, IBAN
    payment_status = db.Column(db.String(10), default='PENDING')  # PENDING, ADVANCE, PAID
    branch_id = db.Column(db.Integer, ForeignKey('branches.id'), nullable=False)
    staff_id = db.Column(db.Integer, ForeignKey('staff.id'), nullable=False)
    reservation_date = db.Column(db.Date, nullable=False)
    reservation_time = db.Column(db.Time, nullable=False)
    is_canceled = db.Column(db.Boolean, default=False)  # İptal edilmiş mi?
    cancel_type = db.Column(db.String(20), nullable=True)  # NORMAL (ön ödeme iadesi yok) veya REFUND (tam iade)
    cancel_revenue = db.Column(db.Float, nullable=True)  # İptal edildiğinde ciroya ne kadar eklenecek (ön ödeme tutarı)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    branch = relationship("Branch", back_populates="reservations")
    staff = relationship("Staff", back_populates="reservations")
    customer = relationship("Customer", back_populates="reservations")
    
    def __repr__(self):
        return f'<Reservation {self.customer_name} on {self.reservation_date} at {self.reservation_time}>'
    
    @property
    def advance_payment_amount(self):
        """Calculate advance payment amount based on percentage"""
        return (self.advance_payment_percentage / 100) * self.total_price
        
    def save_with_customer(self):
        """Save reservation and associate with customer record (or create one)"""
        from sqlalchemy.orm import Session
        
        # Check if customer already exists by phone number
        customer = Customer.query.filter_by(phone=self.customer_phone).first()
        
        if not customer:
            # Create a new customer record
            customer = Customer(
                name=self.customer_name,
                phone=self.customer_phone
            )
            db.session.add(customer)
            db.session.flush()  # Flush to get the ID without committing
            
            # Log new customer - do this later to prevent slowing down the reservation process
            # We'll handle this in routes.py after commit
        
        # Link customer to this reservation
        self.customer_id = customer.id
        
        return self
