from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, SelectField, TextAreaField, EmailField
from wtforms.validators import DataRequired, Email, EqualTo, ValidationError, Length, Optional
from models import User, Role

class LoginForm(FlaskForm):
    username = StringField('Kullanıcı Adı', validators=[DataRequired()])
    password = PasswordField('Şifre', validators=[DataRequired()])
    remember_me = BooleanField('Beni Hatırla')
    submit = SubmitField('Giriş Yap')
    
class UserForm(FlaskForm):
    username = StringField('Kullanıcı Adı', validators=[DataRequired(), Length(min=3, max=64)])
    name = StringField('Ad Soyad', validators=[DataRequired(), Length(max=100)])
    password = PasswordField('Şifre', validators=[
        Optional(),
        Length(min=6, message='Şifre en az 6 karakter olmalıdır.')
    ])
    password2 = PasswordField('Şifreyi Tekrar Girin', validators=[
        Optional(),
        EqualTo('password', message='Şifreler eşleşmelidir.')
    ])
    email = EmailField('E-posta', validators=[Optional(), Email()])
    # Şube seçimi tamamen kaldırıldı, sistem kullanıcıları tüm şubeleri yönetir
    is_active = BooleanField('Aktif', default=True)
    roles = SelectField('Roller', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Kaydet')
    
    def __init__(self, *args, **kwargs):
        self.user_id = kwargs.pop('user_id', None)
        super(UserForm, self).__init__(*args, **kwargs)
    
    def validate_username(self, username):
        # Kullanıcı adının benzersiz olduğunu kontrol et
        user = User.query.filter_by(username=username.data).first()
        if user and (not self.user_id or user.id != self.user_id):
            raise ValidationError('Bu kullanıcı adı zaten kullanılıyor.')

class RoleForm(FlaskForm):
    name = StringField('Rol Adı', validators=[DataRequired(), Length(min=3, max=50)])
    description = TextAreaField('Açıklama', validators=[Optional(), Length(max=200)])
    color = StringField('Renk', validators=[DataRequired(), Length(min=7, max=7)])
    is_superadmin = BooleanField('Süper Admin')
    
    # İzinler
    can_create_reservation = BooleanField('Rezervasyon Oluşturabilir')
    can_view_reports = BooleanField('Raporları Görebilir')
    can_view_logs = BooleanField('Logları Görebilir')
    can_view_settings = BooleanField('Ayarları Görebilir')
    can_view_management = BooleanField('Yönetim Panelini Görebilir')
    
    submit = SubmitField('Kaydet')
    
    def __init__(self, *args, **kwargs):
        self.role_id = kwargs.pop('role_id', None)
        super(RoleForm, self).__init__(*args, **kwargs)
    
    def validate_name(self, name):
        # Rol adının benzersiz olduğunu kontrol et
        role = Role.query.filter_by(name=name.data).first()
        if role and (not self.role_id or role.id != self.role_id):
            raise ValidationError('Bu rol adı zaten kullanılıyor.')