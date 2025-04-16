#!/usr/bin/env python3
import os
import sys
import logging
from dotenv import load_dotenv
from app import app
import telegram_service

# Dizin yolunu ayarla (göreceli yollar için)
base_dir = os.path.abspath(os.path.dirname(__file__))

# .env dosyasını yükle (varsa)
env_path = os.path.join(base_dir, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    print(f"Uyarı: {env_path} bulunamadı, çevre değişkenleri için sistem değişkenlerine bakılacak.")

# Logs klasörünü oluştur
logs_dir = os.path.join(base_dir, 'logs')
os.makedirs(logs_dir, exist_ok=True)

# Loglamayı ayarla
log_file = os.environ.get('LOG_FILE', os.path.join(logs_dir, 'bot.log'))
log_level_str = os.environ.get('LOG_LEVEL', 'INFO')
log_level = getattr(logging, log_level_str.upper(), logging.INFO)

# Kök logger'ı yapılandır
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Flask uygulamasını başlat
if __name__ == "__main__":
    logger.info("Uygulama başlatılıyor...")
    
    # Webhook kullanımı kontrol ediliyor
    use_webhook = os.environ.get('USE_WEBHOOK', 'false').lower() == 'true'
    
    try:
        # Telegram bot'u başlat
        if use_webhook:
            # Webhook ayarlarını al
            webhook_url = os.environ.get('WEBHOOK_URL')
            webhook_port = int(os.environ.get('WEBHOOK_PORT', 8443))
            cert_path = os.environ.get('WEBHOOK_CERT_PATH')
            key_path = os.environ.get('WEBHOOK_PRIVATE_KEY_PATH')
            
            if not webhook_url:
                logger.error("USE_WEBHOOK=true olarak ayarlandı ancak WEBHOOK_URL tanımlanmamış!")
                sys.exit(1)
            
            logger.info(f"Telegram botu webhook modunda başlatılıyor: {webhook_url}")
            telegram_service.start_webhook(webhook_url, webhook_port, cert_path, key_path)
        else:
            # Normal polling modunda başlat
            logger.info("Telegram botu polling modunda başlatılıyor...")
            telegram_service.start_telegram_bot()
            
        # Uygulama durduğunda bot'u da durdur
        import atexit
        atexit.register(telegram_service.stop_telegram_bot)
        
        # Geliştirme sunucusunda çalıştır (üretimde gunicorn kullan)
        app.run(host='0.0.0.0', port=5000, debug=False)
        
    except Exception as e:
        logger.error(f"Uygulama başlatılırken hata oluştu: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)