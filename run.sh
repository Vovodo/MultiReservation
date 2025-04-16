#!/bin/bash
# Rezervasyon Sistemi Başlatma Betiği

# Geliştirme ortamı için basit bir başlatma betiği
# Üretim ortamında Supervisor veya systemd kullanın

# Dizin kontrolü
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd $DIR

# Sanal ortamı etkinleştir (varsa)
if [ -d "venv" ]; then
    source venv/bin/activate
    echo "Sanal ortam etkinleştirildi"
else
    echo "Sanal ortam bulunamadı, sistem Python kullanılıyor"
fi

# Logs dizini oluştur
mkdir -p logs

# .env dosyası kontrolü
if [ -f ".env" ]; then
    echo ".env dosyası bulundu"
else
    echo "UYARI: .env dosyası bulunamadı, .env.example'dan kopyalanıyor"
    cp .env.example .env
    echo "Lütfen .env dosyasını düzenleyip gerçek değerleri girin"
fi

# Bağımlılıkları kontrol et
pip install -r vps_requirements.txt

# Veritabanı tabloları kontrolü
echo "Veritabanı tabloları kontrol ediliyor..."
python -c "from app import app, db; app.app_context().push(); db.create_all()"

# Uygulamayı başlat
echo "Uygulama başlatılıyor..."
exec gunicorn --workers 2 --bind 0.0.0.0:5000 --reload wsgi:app