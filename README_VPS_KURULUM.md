# VPS Kurulum Kılavuzu - Rezervasyon Sistemi

Bu belge, rezervasyon sisteminin VPS (Virtual Private Server) üzerinde nasıl kurulacağını ve yapılandırılacağını açıklar.

## Sistem Gereksinimleri

- Ubuntu 20.04 LTS veya daha yeni
- Python 3.8 veya daha yeni
- PostgreSQL 12 veya daha yeni
- Nginx (Web sunucusu olarak)
- Supervisor (Süreç yönetimi için)

## 1. Sistem Paketlerini Kurma

```bash
# Sistem paketlerini güncelle
sudo apt update
sudo apt upgrade -y

# Gerekli paketleri kur
sudo apt install -y python3-pip python3-dev python3-venv postgresql postgresql-contrib 
sudo apt install -y nginx supervisor git curl build-essential

# PostgreSQL'i başlat
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

## 2. PostgreSQL Veritabanı Oluşturma

```bash
# PostgreSQL kullanıcısına geç
sudo -u postgres psql

# Veritabanı ve kullanıcı oluştur (psql kabuğu içinde)
CREATE DATABASE reservationdb;
CREATE USER rezervasyonuser WITH PASSWORD 'guclu_parola';
GRANT ALL PRIVILEGES ON DATABASE reservationdb TO rezervasyonuser;
\q
```

## 3. Projeyi Kurma

```bash
# Uygun bir dizine git
cd /var/www/

# Projeyi kopyala
sudo git clone https://github.com/kullanici/rezervasyon-sistemi.git
cd rezervasyon-sistemi

# İzinleri ayarla
sudo chown -R $USER:$USER /var/www/rezervasyon-sistemi

# Sanal ortam oluştur
python3 -m venv venv
source venv/bin/activate

# Bağımlılıkları kur
pip install -r vps_requirements.txt
```

## 4. Çevre Değişkenlerini Yapılandırma

```bash
# .env örnek dosyasını kopyala
cp .env.example .env

# .env dosyasını düzenle
nano .env
```

Şu değerleri güncelleyin:

- `DATABASE_URL`: PostgreSQL bağlantı bilgileri
- `PGUSER`, `PGPASSWORD`, `PGDATABASE`: PostgreSQL kullanıcı bilgileri
- `TELEGRAM_BOT_TOKEN`: Telegram bot token'ı
- `FLASK_SECRET_KEY`: Güvenli bir rastgele değer
- Diğer ayarları ihtiyacınıza göre düzenleyin

## 5. Supervisor Yapılandırması

```bash
# Örnek supervisor dosyasını kopyala
cp supervisor.conf.example /etc/supervisor/conf.d/rezervasyon.conf

# Düzenle ve kendi yollarınızı belirt
sudo nano /etc/supervisor/conf.d/rezervasyon.conf
```

## 6. Nginx Yapılandırması

Aşağıdaki içeriği `/etc/nginx/sites-available/rezervasyon` dosyasına ekleyin:

```
server {
    listen 80;
    server_name sizin-domain-adresiniz.com www.sizin-domain-adresiniz.com;

    location /static {
        alias /var/www/rezervasyon-sistemi/static;
    }

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Nginx yapılandırmasını etkinleştirme:

```bash
sudo ln -s /etc/nginx/sites-available/rezervasyon /etc/nginx/sites-enabled
sudo nginx -t  # Yapılandırmayı test et
sudo systemctl restart nginx
```

## 7. Servisleri Başlatma

```bash
# Logs dizininin var olduğundan emin olun
mkdir -p /var/www/rezervasyon-sistemi/logs

# Supervisor'ı yeniden yükle ve güncelle
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start rezervasyon_system
```

## 8. SSL Yapılandırması (Önerilen)

Certbot ile Let's Encrypt SSL sertifikası kurun:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d sizin-domain-adresiniz.com -d www.sizin-domain-adresiniz.com
```

## 9. Telegram Webhook Yapılandırması (İsteğe Bağlı)

Eğer webhook kullanmak isterseniz, `.env` dosyasında aşağıdaki değişiklikleri yapın:

```
USE_WEBHOOK=true
WEBHOOK_URL=https://sizin-domain-adresiniz.com/webhook
```

Webhook için Nginx yapılandırmasına şu satırları ekleyin:

```
location /webhook {
    proxy_pass http://localhost:5000/webhook;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection 'upgrade';
    proxy_set_header Host $host;
    proxy_cache_bypass $http_upgrade;
}
```

## Sorun Giderme

### Logları Kontrol Etme

```bash
# Supervisor logları
sudo tail -f /var/www/rezervasyon-sistemi/logs/supervisor.log

# Supervisor daemon logları
sudo tail -f /var/www/rezervasyon-sistemi/logs/supervisord.log

# Uygulama logları
sudo tail -f /var/www/rezervasyon-sistemi/logs/bot.log

# Nginx hata logları
sudo tail -f /var/log/nginx/error.log
```

### Uygulamayı Yeniden Başlatma

```bash
sudo supervisorctl restart rezervasyon_system
```

### Veritabanı Bağlantı Sorunları

PostgreSQL servisinin çalıştığını kontrol edin:

```bash
sudo systemctl status postgresql
```

### Telegram Bot Sorunları

Telegram bot token'ının doğru olduğunu ve `.env` dosyasında belirtildiğini kontrol edin. Telegram API'ın erişilebilir olduğundan emin olun.