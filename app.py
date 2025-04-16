import os
import atexit
import logging
from dotenv import load_dotenv

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix

# .env dosyasını yükle (varsa)
base_dir = os.path.abspath(os.path.dirname(__file__))
env_path = os.path.join(base_dir, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
    print(f".env dosyası yüklendi: {env_path}")
else:
    print(f".env dosyası bulunamadı: {env_path}, sistem değişkenleri kullanılacak")


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)
# create the app
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "secure_reservation_system")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1) # needed for url_for to generate with https

# login manager ayarları
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Bu sayfaya erişmek için lütfen giriş yapın.'
login_manager.login_message_category = 'warning'

@login_manager.user_loader
def load_user(user_id):
    from models import User
    return User.query.get(int(user_id))

# configure the database
database_url = os.environ.get("DATABASE_URL")

# Eğer database_url PostgreSQL URL'iyse kullan
if database_url:
    # PostgreSQL kullanıldığında ek yapılandırma
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_recycle": 280,
        "pool_pre_ping": True,
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 30
    }
    print("PostgreSQL veritabanı kullanılıyor:", database_url.split("@")[1] if "@" in database_url else "Belirtilmemiş")
else:
    # PostgreSQL yoksa, SQLite kullan (persist yapılandırmasıyla)
    sqlite_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'instance', 'reservation_system.db')
    # Dizin yoksa oluştur
    os.makedirs(os.path.dirname(sqlite_path), exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{sqlite_path}"
    print("SQLite veritabanı kullanılıyor:", sqlite_path)
# initialize the app with the extension, flask-sqlalchemy >= 3.0.x
db.init_app(app)

with app.app_context():
    # Make sure to import the models here or their tables won't be created
    import models  # noqa: F401
    
    # Sadece tabloları oluştur, örnek veri ekleme (bu işlem routes.py'deki init_data ile yapılacak)
    db.create_all()
    print("Veritabanı tabloları oluşturuldu/doğrulandı")

# Import routes after app is created to avoid circular imports
from routes import *
from routes_monthly_reports import *

# Start the Telegram bot
def start_bot():
    try:
        from telegram_service import start_telegram_bot, bot_is_running
        import threading
        
        # Önce botun zaten çalışıp çalışmadığını kontrol et
        if bot_is_running():
            print("Telegram bot already running, skipping start")
            return
            
        # Start the bot in a separate thread
        bot_thread = threading.Thread(
            target=start_telegram_bot,
            daemon=True
        )
        bot_thread.start()
        print("Telegram bot started in background thread")
    except Exception as e:
        print(f"Failed to start Telegram bot: {str(e)}")
        import traceback
        print(traceback.format_exc())

# Clean up and stop bot when app shuts down
def stop_bot():
    try:
        from telegram_service import stop_telegram_bot, bot_is_running
        
        # Botun çalışıp çalışmadığını kontrol et
        if not bot_is_running():
            print("Telegram bot not running, skipping stop")
            return
            
        stop_telegram_bot()
        print("Telegram bot stopped")
    except Exception as e:
        print(f"Failed to stop Telegram bot: {str(e)}")
        import traceback
        print(traceback.format_exc())

# Register shutdown hook
atexit.register(stop_bot)

# Aylık rapor zamanlayıcısını başlat
def start_scheduler():
    try:
        from scheduler import initialize_scheduler
        scheduler = initialize_scheduler()
        print("Aylık rapor zamanlayıcısı başlatıldı")
        return scheduler
    except Exception as e:
        print(f"Zamanlayıcı başlatılamadı: {str(e)}")
        return None

# Zamanlayıcıyı durdur
def stop_scheduler(scheduler):
    if scheduler:
        try:
            scheduler.shutdown()
            print("Zamanlayıcı durduruldu")
        except Exception as e:
            print(f"Zamanlayıcı durdurulurken hata: {str(e)}")

# Start bot and scheduler when app starts
if os.environ.get("FLASK_ENV") != "test":  # Don't start during testing
    with app.app_context():
        start_bot()
        # Zamanlayıcıyı başlat ve global değişkene ata
        background_scheduler = start_scheduler()
        # Uygulama kapatıldığında zamanlayıcıyı durdur
        if background_scheduler:
            atexit.register(lambda: stop_scheduler(background_scheduler))
